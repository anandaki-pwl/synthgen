"""Turn a Schema into a pandas DataFrame of synthetic values."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .fields import Field, Schema, validate_schema
from .wordlists import FIRST_NAMES, LAST_NAMES, FILLER_WORDS

_LETTERS = np.array(list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
_DIGITS = np.array(list("0123456789"))


class SchemaError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def _numbers(f: Field, n: int, rng: np.random.Generator) -> np.ndarray:
    o = f.options
    lo, hi = float(o["min"]), float(o["max"])
    span = hi - lo
    dist = o["distribution"]
    if dist == "normal":
        mean = float(o["mean"]) if o.get("mean") is not None else lo + span / 2
        std = float(o["std"]) if o.get("std") else max(span / 6, 1e-9)
        vals = np.clip(rng.normal(mean, std, n), lo, hi)
    elif dist == "right_skewed":
        vals = lo + rng.beta(1.5, 5, n) * span
    elif dist == "left_skewed":
        vals = lo + rng.beta(5, 1.5, n) * span
    else:
        vals = rng.uniform(lo, hi, n)
    return vals


def _gen_whole_number(f, n, rng):
    lo, hi = int(f.options["min"]), int(f.options["max"])
    if f.unique:
        # unique values are drawn evenly from the range; the distribution setting is ignored
        pool = rng.choice(np.arange(lo, hi + 1), size=n, replace=False)
        return pd.Series(pool, dtype="Int64")
    vals = np.rint(_numbers(f, n, rng)).astype(np.int64)
    return pd.Series(np.clip(vals, lo, hi), dtype="Int64")


def _gen_decimal(f, n, rng):
    vals = np.round(_numbers(f, n, rng), int(f.options["decimals"]))
    if f.unique:
        vals = _dedupe(vals, lambda k: np.round(_numbers(f, k, rng), int(f.options["decimals"])))
    return pd.Series(vals, dtype="float64")


def _gen_sequence(f, n, rng):
    start, step = int(f.options["start"]), int(f.options["step"]) or 1
    return pd.Series(start + step * np.arange(n), dtype="Int64")


def _gen_category(f, n, rng):
    vals = list(f.options["values"])
    if f.unique:
        return pd.Series(rng.choice(vals, size=n, replace=False), dtype="object")
    w = f.options.get("weights")
    p = np.array(w, dtype=float) / sum(w) if w else None
    return pd.Series(rng.choice(vals, size=n, p=p), dtype="object")


def _pattern_values(pattern: str, n: int, rng) -> np.ndarray:
    cols = []
    for ch in pattern:
        if ch == "#":
            cols.append(rng.choice(_DIGITS, n))
        elif ch == "@":
            cols.append(rng.choice(_LETTERS, n))
        else:
            cols.append(np.full(n, ch))
    out = cols[0].astype(object)
    for c in cols[1:]:
        out = out + c.astype(object)
    return out


def _gen_id_pattern(f, n, rng):
    pat = f.options["pattern"]
    vals = _pattern_values(pat, n, rng)
    if f.unique:
        vals = _dedupe(vals, lambda k: _pattern_values(pat, k, rng))
    return pd.Series(vals, dtype="object")


def _gen_person_name(f, n, rng):
    first = rng.choice(FIRST_NAMES, n).astype(object)
    last = rng.choice(LAST_NAMES, n).astype(object)
    part = f.options["part"]
    if part == "first":
        return pd.Series(first, dtype="object")
    if part == "last":
        return pd.Series(last, dtype="object")
    return pd.Series(first + " " + last, dtype="object")


def _gen_email(f, n, rng):
    first = np.char.lower(rng.choice(FIRST_NAMES, n).astype(str)).astype(object)
    last = np.char.lower(rng.choice(LAST_NAMES, n).astype(str)).astype(object)
    domain = f.options["domain"].lstrip("@")
    if f.unique:
        # row-based suffix guarantees uniqueness; shuffle so it doesn't look sequential
        suffix = rng.permutation(n).astype(str).astype(object)
    else:
        suffix = rng.integers(1, 1000, n).astype(str).astype(object)
    return pd.Series(first + "." + last + suffix + "@" + domain, dtype="object")


def _gen_free_text(f, n, rng):
    lo, hi = int(f.options["min_words"]), int(f.options["max_words"])
    counts = rng.integers(lo, hi + 1, n)
    words = rng.choice(FILLER_WORDS, counts.sum())
    out, i = [], 0
    for c in counts:
        s = " ".join(words[i:i + c])
        out.append(s[:1].upper() + s[1:] + ".")
        i += c
    return pd.Series(out, dtype="object")


def _gen_date(f, n, rng):
    start = np.datetime64(str(f.options["start"])[:10], "D")
    end = np.datetime64(str(f.options["end"])[:10], "D")
    days = int((end - start).astype(int)) + 1
    if f.unique:
        offsets = rng.choice(days, size=n, replace=False)
    else:
        offsets = rng.integers(0, days, n)
    return pd.Series(pd.to_datetime(start + offsets.astype("timedelta64[D]")).normalize())


def _gen_datetime(f, n, rng):
    start = np.datetime64(str(f.options["start"])[:10], "s")
    end = np.datetime64(str(f.options["end"])[:10], "s") + np.timedelta64(86399, "s")
    secs = int((end - start).astype(int)) + 1

    def draw(k):
        return rng.integers(0, secs, k)

    offsets = _dedupe(draw(n), draw) if f.unique else draw(n)
    return pd.Series(pd.to_datetime(start + offsets.astype("timedelta64[s]")))


def _gen_boolean(f, n, rng):
    return pd.Series(rng.random(n) < float(f.options["pct_true"]) / 100, dtype="boolean")


_GENERATORS = {
    "whole_number": _gen_whole_number,
    "decimal": _gen_decimal,
    "sequence": _gen_sequence,
    "category": _gen_category,
    "id_pattern": _gen_id_pattern,
    "person_name": _gen_person_name,
    "email": _gen_email,
    "free_text": _gen_free_text,
    "date": _gen_date,
    "datetime": _gen_datetime,
    "boolean": _gen_boolean,
}


def _dedupe(vals: np.ndarray, redraw, max_rounds: int = 50) -> np.ndarray:
    """Replace duplicate values with fresh draws until all are unique."""
    vals = np.asarray(vals, dtype=object)
    for _ in range(max_rounds):
        _, first_idx = np.unique(vals.astype(str), return_index=True)
        dup_mask = np.ones(len(vals), dtype=bool)
        dup_mask[first_idx] = False
        k = int(dup_mask.sum())
        if k == 0:
            return vals
        vals[dup_mask] = np.asarray(redraw(k), dtype=object)
    raise SchemaError(["Couldn't make values unique; widen the range or turn off 'unique'."])


def generate_field(f: Field, n: int, rng: np.random.Generator) -> pd.Series:
    s = _GENERATORS[f.kind](f, n, rng).reset_index(drop=True)
    if f.blank_pct > 0:
        mask = rng.random(n) < f.blank_pct / 100
        if s.dtype == "object":
            s = s.where(~mask, None)
        else:
            s = s.mask(mask)
    s.name = f.name
    return s


def generate(schema: Schema, rows: int | None = None) -> pd.DataFrame:
    """Build the dataset. Raises SchemaError listing every problem if the schema is invalid.

    Each field gets its own random stream derived from (seed, field name), so adding,
    removing or reordering fields doesn't change the values in the other columns.
    """
    problems = validate_schema(schema)
    if problems:
        raise SchemaError(problems)
    n = rows if rows is not None else schema.rows
    cols = {}
    for f in schema.fields:
        name_key = [ord(c) for c in f.name.strip().lower()]
        rng = np.random.default_rng([schema.seed, *name_key])
        cols[f.name] = generate_field(f, n, rng)
    return pd.DataFrame(cols)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """One row per column: blanks, distinct values, range or most common values."""
    rows = []
    for col in df.columns:
        s = df[col]
        nonnull = s.dropna()
        info = {
            "Field": col,
            "Blank %": round(100 * s.isna().mean(), 1),
            "Distinct values": int(nonnull.nunique()),
            "Min": "",
            "Max": "",
            "Most common": "",
        }
        if len(nonnull) and (pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)
                             or pd.api.types.is_datetime64_any_dtype(s)):
            info["Min"], info["Max"] = str(nonnull.min()), str(nonnull.max())
        if len(nonnull):
            top = nonnull.astype(str).value_counts().head(3)
            info["Most common"] = ", ".join(f"{v} ({c:,})" for v, c in top.items())
        rows.append(info)
    return pd.DataFrame(rows)
