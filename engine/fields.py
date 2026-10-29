"""Field and dataset definitions.

A Field describes one column: its name (must match the real data exactly),
what kind of values it holds, and the rules used to generate them.
A Schema is a named list of fields plus a row count and random seed.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field, asdict
from datetime import date

MAX_ROWS = 1_000_000  # stays under Excel's 1,048,576-row sheet limit

# Each kind: a friendly label, the type Tableau will see, default options,
# and whether "must be unique" is allowed.
KINDS: dict[str, dict] = {
    "whole_number": {
        "label": "Whole number",
        "tableau": "Number (whole)",
        "defaults": {"min": 0, "max": 100, "distribution": "uniform", "mean": None, "std": None},
        "can_be_unique": True,
    },
    "decimal": {
        "label": "Decimal number",
        "tableau": "Number (decimal)",
        "defaults": {"min": 0.0, "max": 100.0, "decimals": 2, "distribution": "uniform", "mean": None, "std": None},
        "can_be_unique": True,
    },
    "sequence": {
        "label": "Row number (1, 2, 3...)",
        "tableau": "Number (whole)",
        "defaults": {"start": 1, "step": 1},
        "can_be_unique": False,  # always unique already
    },
    "category": {
        "label": "Category (pick from a list)",
        "tableau": "String",
        "defaults": {"values": ["Value A", "Value B", "Value C"], "weights": None},
        "can_be_unique": True,
    },
    "id_pattern": {
        "label": "ID / code pattern",
        "tableau": "String",
        "defaults": {"pattern": "ID######"},
        "can_be_unique": True,
    },
    "person_name": {
        "label": "Person name",
        "tableau": "String",
        "defaults": {"part": "full"},
        "can_be_unique": False,
    },
    "email": {
        "label": "Email address",
        "tableau": "String",
        "defaults": {"domain": "example.edu"},
        "can_be_unique": True,
    },
    "free_text": {
        "label": "Free text (filler words)",
        "tableau": "String",
        "defaults": {"min_words": 3, "max_words": 10},
        "can_be_unique": False,
    },
    "date": {
        "label": "Date",
        "tableau": "Date",
        "defaults": {"start": "2020-01-01", "end": "2025-12-31"},
        "can_be_unique": True,
    },
    "datetime": {
        "label": "Date and time",
        "tableau": "Date & Time",
        "defaults": {"start": "2020-01-01", "end": "2025-12-31"},
        "can_be_unique": True,
    },
    "boolean": {
        "label": "True / False",
        "tableau": "Boolean",
        "defaults": {"pct_true": 50},
        "can_be_unique": False,
    },
}

DISTRIBUTIONS = {
    "uniform": "Even spread",
    "normal": "Bell curve (most values near the middle)",
    "right_skewed": "Mostly low values, a few high",
    "left_skewed": "Mostly high values, a few low",
}

NAME_PARTS = {"full": "First Last", "first": "First name only", "last": "Last name only"}


@dataclass
class Field:
    name: str
    kind: str = "category"
    options: dict = field(default_factory=dict)
    blank_pct: float = 0.0
    unique: bool = False
    description: str = ""

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"Unknown field kind '{self.kind}'")
        merged = copy.deepcopy(KINDS[self.kind]["defaults"])
        merged.update(self.options or {})
        self.options = merged

    @classmethod
    def from_dict(cls, d: dict) -> "Field":
        return cls(
            name=d.get("name", ""),
            kind=d.get("kind", "category"),
            options=d.get("options", {}),
            blank_pct=float(d.get("blank_pct", 0) or 0),
            unique=bool(d.get("unique", False)),
            description=d.get("description", ""),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def tableau_type(self) -> str:
        return KINDS[self.kind]["tableau"]


@dataclass
class Schema:
    name: str
    description: str = ""
    rows: int = 1000
    seed: int = 42
    fields: list[Field] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Schema":
        return cls(
            name=d.get("name", ""),
            description=d.get("description", ""),
            rows=int(d.get("rows", 1000)),
            seed=int(d.get("seed", 42)),
            fields=[Field.from_dict(f) for f in d.get("fields", [])],
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "rows": self.rows,
            "seed": self.seed,
            "fields": [f.to_dict() for f in self.fields],
        }


def _pattern_capacity(pattern: str) -> int:
    return 10 ** pattern.count("#") * 26 ** pattern.count("@")


def validate_field(f: Field, rows: int) -> list[str]:
    """Return a list of plain-English problems with this field (empty if fine)."""
    errs = []
    label = f"'{f.name}'" if f.name else "A field with no name"
    o = f.options
    if not f.name.strip():
        errs.append(f"{label}: every field needs a name.")
    if not 0 <= f.blank_pct <= 100:
        errs.append(f"{label}: blank % must be between 0 and 100.")
    if f.unique and not KINDS[f.kind]["can_be_unique"]:
        errs.append(f"{label}: '{KINDS[f.kind]['label']}' fields can't be set to unique.")

    if f.kind in ("whole_number", "decimal"):
        if o["min"] > o["max"]:
            errs.append(f"{label}: minimum is larger than maximum.")
        if o["distribution"] not in DISTRIBUTIONS:
            errs.append(f"{label}: unknown distribution '{o['distribution']}'.")
        if f.kind == "whole_number" and f.unique and (int(o["max"]) - int(o["min"]) + 1) < rows:
            errs.append(f"{label}: only {int(o['max']) - int(o['min']) + 1:,} possible values "
                        f"but {rows:,} rows requested, so values can't all be unique.")
    elif f.kind == "category":
        vals = o.get("values") or []
        if not vals:
            errs.append(f"{label}: add at least one category value.")
        w = o.get("weights")
        if w is not None:
            if len(w) != len(vals):
                errs.append(f"{label}: number of weights doesn't match number of values.")
            elif any(x < 0 for x in w) or sum(w) <= 0:
                errs.append(f"{label}: weights must be zero or positive and not all zero.")
        if f.unique and len(vals) < rows:
            errs.append(f"{label}: {len(vals)} values listed but {rows:,} rows requested, "
                        f"so values can't all be unique.")
    elif f.kind == "id_pattern":
        p = o.get("pattern", "")
        if "#" not in p and "@" not in p:
            errs.append(f"{label}: pattern needs at least one # (digit) or @ (letter).")
        elif f.unique and _pattern_capacity(p) < rows:
            errs.append(f"{label}: pattern '{p}' only allows {_pattern_capacity(p):,} "
                        f"different IDs but {rows:,} rows requested.")
    elif f.kind in ("date", "datetime"):
        try:
            s, e = date.fromisoformat(str(o["start"])[:10]), date.fromisoformat(str(o["end"])[:10])
            if s > e:
                errs.append(f"{label}: start date is after end date.")
            elif f.kind == "date" and f.unique and (e - s).days + 1 < rows:
                errs.append(f"{label}: only {(e - s).days + 1:,} days in range but {rows:,} rows "
                            f"requested, so dates can't all be unique.")
        except ValueError:
            errs.append(f"{label}: dates must look like YYYY-MM-DD.")
    elif f.kind == "free_text":
        if o["min_words"] < 1 or o["min_words"] > o["max_words"]:
            errs.append(f"{label}: word counts must be at least 1, with min no larger than max.")
    elif f.kind == "boolean":
        if not 0 <= o["pct_true"] <= 100:
            errs.append(f"{label}: % true must be between 0 and 100.")
    elif f.kind == "person_name":
        if o["part"] not in NAME_PARTS:
            errs.append(f"{label}: unknown name part '{o['part']}'.")
    return errs


def validate_schema(s: Schema) -> list[str]:
    errs = []
    if not s.name.strip():
        errs.append("The dataset needs a name.")
    if not 1 <= s.rows <= MAX_ROWS:
        errs.append(f"Row count must be between 1 and {MAX_ROWS:,}.")
    if not s.fields:
        errs.append("Add at least one field.")
    names = [f.name.strip().lower() for f in s.fields]
    dupes = sorted({f.name for f in s.fields if names.count(f.name.strip().lower()) > 1})
    if dupes:
        errs.append("Field names must be unique (Tableau ignores capitalization): " + ", ".join(dupes))
    for f in s.fields:
        errs.extend(validate_field(f, s.rows))
    return errs


# Words people commonly use in data dictionaries, mapped to a field kind.
_TYPE_WORDS = {
    "whole_number": ["int", "integer", "whole", "bigint", "smallint", "count", "number"],
    "decimal": ["decimal", "float", "double", "numeric", "real", "money", "currency"],
    "date": ["date"],
    "datetime": ["datetime", "timestamp", "date & time", "date and time", "time"],
    "boolean": ["bool", "boolean", "true/false", "yes/no", "flag", "bit"],
    "category": ["string", "text", "varchar", "char", "nvarchar", "category"],
}


def guess_kind(type_text: str) -> str:
    t = type_text.strip().lower()
    if t in KINDS:
        return t
    for label_kind, info in KINDS.items():
        if t == info["label"].lower() or t == info["tableau"].lower():
            return label_kind
    # check longer phrases first so "date & time" beats "date"
    for kind, words in sorted(_TYPE_WORDS.items(), key=lambda kv: -max(len(w) for w in kv[1])):
        for w in sorted(words, key=len, reverse=True):
            if t == w or t.startswith(w + "(") or t.startswith(w + " "):
                return kind
    return "category"


def parse_field_list(text: str) -> list[Field]:
    """Parse lines like 'Student ID, string' or 'GPA<TAB>decimal' into fields.

    Separator can be a comma, tab or pipe. A missing type defaults to category.
    """
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        for sep in ("\t", "|", ","):
            if sep in line:
                name, _, typ = line.partition(sep)
                break
        else:
            name, typ = line, ""
        name = name.strip().strip('"')
        if name:
            out.append(Field(name=name, kind=guess_kind(typ) if typ.strip() else "category"))
    return out
