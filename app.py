"""SynthGen: build synthetic datasets that match the shape of real ones.

Run with:  streamlit run app.py   (or double-click launch.bat)
"""
from __future__ import annotations

import copy
import re
import uuid
from datetime import date

import pandas as pd
import streamlit as st

from engine import (
    DISTRIBUTIONS, KINDS, MAX_ROWS, NAME_PARTS, Field, Schema, SchemaError,
    generate, parse_field_list, summarize, validate_field,
)
from engine import storage
from engine.export import tableau_checklist, to_csv_bytes, to_excel_bytes

st.set_page_config(page_title="SynthGen", page_icon="🧪", layout="wide")

NEW_DATASET = "➕ New dataset"
PREVIEW_ROWS = 1000
SLOW_EXCEL_ROWS = 200_000


# ---------- state helpers ----------

def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def _field_state(f: Field) -> dict:
    d = f.to_dict()
    d["_id"] = _new_id()
    return d


def _to_field(fd: dict) -> Field:
    return Field.from_dict({k: v for k, v in fd.items() if k != "_id"})


def _blank_schema() -> dict:
    return {"name": "", "description": "", "rows": 1000, "seed": 42, "fields": []}


def load_schema(s: Schema | None) -> None:
    st.session_state.schema = _blank_schema() if s is None else {
        "name": s.name, "description": s.description, "rows": s.rows, "seed": s.seed,
        "fields": [_field_state(f) for f in s.fields],
    }
    st.session_state.loaded_name = s.name if s else None
    st.session_state.form_id = _new_id()  # fresh widget keys so old values don't linger
    st.session_state.pop("result", None)


def current_schema() -> Schema:
    d = st.session_state.schema
    return Schema(name=d["name"], description=d["description"], rows=int(d["rows"]),
                  seed=int(d["seed"]), fields=[_to_field(fd) for fd in d["fields"]])


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_") or "dataset"


if "schema" not in st.session_state:
    load_schema(None)


# ---------- field editor (shared by dataset builder and library) ----------

def _category_text(opts: dict) -> str:
    vals, w = opts.get("values") or [], opts.get("weights")
    if w and len(w) == len(vals) and len(set(w)) > 1:
        return "\n".join(f"{v} | {x:g}" for v, x in zip(vals, w))
    return "\n".join(str(v) for v in vals)


def _parse_category_text(text: str) -> tuple[list[str], list[float] | None]:
    vals, weights, any_weight = [], [], False
    for line in text.splitlines():
        if not line.strip():
            continue
        if "|" in line:
            v, _, w = line.rpartition("|")
            try:
                weights.append(float(w.strip()))
                vals.append(v.strip())
                any_weight = True
                continue
            except ValueError:
                pass
        vals.append(line.strip())
        weights.append(1.0)
    return vals, (weights if any_weight else None)


def _date(v) -> date:
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return date.today()


def field_editor(fd: dict, key: str, rows: int) -> dict:
    """Draw the inputs for one field and return its updated definition."""
    c1, c2 = st.columns(2)
    name = c1.text_input("Field name (must match the real data exactly)", fd["name"], key=f"{key}_name")
    kinds = list(KINDS)
    kind = c2.selectbox("Type of values", kinds, index=kinds.index(fd["kind"]),
                        format_func=lambda k: KINDS[k]["label"], key=f"{key}_kind")
    opts = copy.deepcopy(fd["options"] if kind == fd["kind"] else KINDS[kind]["defaults"])
    k = f"{key}_{kind}"  # option widgets are per-kind so switching kinds starts from defaults

    if kind in ("whole_number", "decimal"):
        whole = kind == "whole_number"
        cast = int if whole else float
        step = 1 if whole else 0.1
        a, b, c = st.columns(3)
        opts["min"] = a.number_input("Smallest value", value=cast(opts["min"]), step=step, key=f"{k}_min")
        opts["max"] = b.number_input("Largest value", value=cast(opts["max"]), step=step, key=f"{k}_max")
        if not whole:
            opts["decimals"] = c.number_input("Decimal places", 0, 6, int(opts["decimals"]), key=f"{k}_dec")
        dists = list(DISTRIBUTIONS)
        opts["distribution"] = st.selectbox("How values are spread", dists, index=dists.index(opts["distribution"]),
                                            format_func=DISTRIBUTIONS.get, key=f"{k}_dist")
        if opts["distribution"] == "normal":
            a, b = st.columns(2)
            mean, std = opts.get("mean"), opts.get("std")
            opts["mean"] = a.number_input("Center (leave blank for the middle)",
                                          value=None if mean is None else cast(mean), step=step, key=f"{k}_mean")
            opts["std"] = b.number_input("Spread / std. dev. (leave blank for automatic)",
                                         value=None if std is None else float(std), min_value=0.0, key=f"{k}_std")
    elif kind == "sequence":
        a, b = st.columns(2)
        opts["start"] = a.number_input("Start at", value=int(opts["start"]), step=1, key=f"{k}_start")
        opts["step"] = b.number_input("Count by", value=int(opts["step"]), step=1, key=f"{k}_step")
    elif kind == "category":
        text = st.text_area(
            "Values, one per line. To make a value more common, add a weight: `Engineering | 5`",
            _category_text(opts), height=130, key=f"{k}_values")
        opts["values"], opts["weights"] = _parse_category_text(text)
    elif kind == "id_pattern":
        opts["pattern"] = st.text_input("Pattern: `#` = random digit, `@` = random letter, anything else is kept as-is",
                                        opts["pattern"], key=f"{k}_pattern")
        st.caption("Example: `PU########` → PU04718263")
    elif kind == "person_name":
        parts = list(NAME_PARTS)
        opts["part"] = st.selectbox("Which part", parts, index=parts.index(opts["part"]),
                                    format_func=NAME_PARTS.get, key=f"{k}_part")
    elif kind == "email":
        opts["domain"] = st.text_input("Email domain", opts["domain"], key=f"{k}_domain")
    elif kind == "free_text":
        a, b = st.columns(2)
        opts["min_words"] = a.number_input("Fewest words", 1, 500, int(opts["min_words"]), key=f"{k}_minw")
        opts["max_words"] = b.number_input("Most words", 1, 500, int(opts["max_words"]), key=f"{k}_maxw")
    elif kind in ("date", "datetime"):
        a, b = st.columns(2)
        lo, hi = date(1900, 1, 1), date(2100, 12, 31)
        opts["start"] = a.date_input("Earliest", _date(opts["start"]), lo, hi, key=f"{k}_start").isoformat()
        opts["end"] = b.date_input("Latest", _date(opts["end"]), lo, hi, key=f"{k}_end").isoformat()
    elif kind == "boolean":
        opts["pct_true"] = st.slider("% of rows that are True", 0, 100, int(opts["pct_true"]), key=f"{k}_pct")

    a, b = st.columns(2)
    blank_pct = a.slider("% of rows left blank", 0, 100, int(fd["blank_pct"]), key=f"{key}_blank")
    unique = False
    if KINDS[kind]["can_be_unique"]:
        unique = b.checkbox("All values different", fd["unique"] if kind == fd["kind"] else False,
                            help="Use for IDs and other fields where no two rows can share a value.",
                            key=f"{k}_unique")
    description = st.text_input("Notes (optional, shown in the Tableau checklist)", fd["description"],
                                key=f"{key}_desc")

    new = {"_id": fd.get("_id"), "name": name, "kind": kind, "options": opts,
           "blank_pct": float(blank_pct), "unique": unique, "description": description}
    for problem in validate_field(_to_field(new), rows):
        st.warning(problem, icon="⚠️")
    return new


# ---------- pages ----------

def page_build():
    st.title("Build a dataset")
    saved = storage.list_schemas()
    names = [s.name for s in saved]

    def _on_pick():
        pick = st.session_state.pick_schema
        load_schema(None if pick == NEW_DATASET else next(s for s in saved if s.name == pick))

    options = [NEW_DATASET] + names
    current = st.session_state.loaded_name if st.session_state.loaded_name in names else NEW_DATASET
    st.selectbox("Open a saved dataset, or start a new one", options, index=options.index(current),
                 key="pick_schema", on_change=_on_pick)

    sd = st.session_state.schema
    fid = st.session_state.form_id
    c1, c2 = st.columns([2, 1])
    sd["name"] = c1.text_input("Dataset name", sd["name"], key=f"{fid}_sname",
                               placeholder="e.g. Enrollment dashboard")
    sd["rows"] = c2.number_input("Number of rows", 1, MAX_ROWS, int(sd["rows"]), step=100, key=f"{fid}_rows")
    sd["description"] = st.text_input("Description (optional)", sd["description"], key=f"{fid}_sdesc")
    with st.expander("Advanced"):
        sd["seed"] = st.number_input(
            "Random seed: the same seed and settings always produce the same data. "
            "Change it to get a different version.", 0, 2**31 - 1, int(sd["seed"]), key=f"{fid}_seed")

    st.subheader(f"Fields ({len(sd['fields'])})")
    if not sd["fields"]:
        st.info("No fields yet. Add some below: from your library, one at a time, or by pasting a list.")

    action = None
    for i, fd in enumerate(sd["fields"]):
        title = f"**{fd['name'] or '(unnamed)'}** · {KINDS[fd['kind']]['label']}"
        with st.expander(title, expanded=not fd["name"]):
            sd["fields"][i] = field_editor(fd, f"{fid}_{fd['_id']}", int(sd["rows"]))
            b1, b2, b3, b4 = st.columns(4)
            if b1.button("↑ Move up", key=f"{fd['_id']}_up", disabled=i == 0):
                action = ("move", i, i - 1)
            if b2.button("↓ Move down", key=f"{fd['_id']}_down", disabled=i == len(sd["fields"]) - 1):
                action = ("move", i, i + 1)
            if b3.button("💾 Save to my library", key=f"{fd['_id']}_lib", disabled=not fd["name"].strip()):
                f = _to_field(sd["fields"][i])
                existed = storage.library_item_exists(f.name)
                storage.save_library_item(f)
                st.toast(f"{'Updated' if existed else 'Saved'} '{f.name}' in your library")
            if b4.button("🗑 Remove", key=f"{fd['_id']}_del"):
                action = ("remove", i, None)
    if action:
        kind, i, j = action
        if kind == "move":
            sd["fields"][i], sd["fields"][j] = sd["fields"][j], sd["fields"][i]
        else:
            sd["fields"].pop(i)
        st.rerun()

    st.markdown("##### Add fields")
    t1, t2, t3 = st.tabs(["From my library", "New field", "Paste a list"])
    with t1:
        lib = storage.list_library()
        if not lib:
            st.caption("Your library is empty. Use **Save to my library** on any field to reuse it later.")
        else:
            picks = st.multiselect("Choose fields", [f.name for f in lib], key=f"{fid}_libpick",
                                   format_func=lambda n: f"{n} ({KINDS[next(f for f in lib if f.name == n).kind]['label']})")
            if st.button("Add selected", disabled=not picks):
                sd["fields"].extend(_field_state(f) for f in lib if f.name in picks)
                st.session_state.form_id = _new_id()
                st.rerun()
    with t2:
        if st.button("Add a blank field"):
            sd["fields"].append(_field_state(Field(name="")))
            st.rerun()
    with t3:
        pasted = st.text_area(
            "One field per line: name, then a comma (or tab) and its type. "
            "You can paste straight from a spreadsheet or data dictionary.",
            placeholder="Student ID, string\nGPA, decimal\nAdmit Date, date\nCredits, integer",
            key=f"{fid}_paste")
        if st.button("Add these fields", disabled=not pasted.strip()):
            sd["fields"].extend(_field_state(f) for f in parse_field_list(pasted))
            st.session_state.form_id = _new_id()
            st.rerun()
        st.caption("Text fields come in as categories with placeholder values; open each one to fill in real labels.")

    st.divider()
    _save_controls(sd)
    st.divider()
    _generate_controls()


def _save_controls(sd):
    name = sd["name"].strip()
    overwriting = name and storage.schema_exists(name) and name != st.session_state.loaded_name
    c1, c2, c3 = st.columns([1, 1, 1])
    confirm = True
    if overwriting:
        confirm = c3.checkbox(f"A different saved dataset is already called '{name}'. Replace it?")
    if c1.button("💾 Save dataset", type="primary", disabled=not name or not confirm):
        storage.save_schema(current_schema())
        st.session_state.loaded_name = name
        st.toast(f"Saved '{name}'")
    if st.session_state.loaded_name:
        if c2.button("🗑 Delete dataset"):
            st.session_state.confirm_delete = st.session_state.loaded_name
        if st.session_state.get("confirm_delete") == st.session_state.loaded_name:
            st.warning(f"Delete '{st.session_state.loaded_name}' permanently?")
            y, n = st.columns(2)
            if y.button("Yes, delete it"):
                storage.delete_schema(st.session_state.loaded_name)
                st.session_state.pop("confirm_delete")
                load_schema(None)
                st.rerun()
            if n.button("Cancel"):
                st.session_state.pop("confirm_delete")
                st.rerun()


def _generate_controls():
    st.subheader("Generate")
    schema = current_schema()
    if schema.rows > SLOW_EXCEL_ROWS:
        st.caption(f"Large datasets (over {SLOW_EXCEL_ROWS:,} rows) can take a minute or two to build the Excel file.")
    if st.button("▶ Generate data", type="primary"):
        try:
            with st.spinner("Generating..."):
                df = generate(schema)
                st.session_state.result = {
                    "snapshot": schema.to_dict(),
                    "df": df,
                    "csv": to_csv_bytes(df, schema),
                    "xlsx": to_excel_bytes(df, schema),
                    "checklist": to_csv_bytes(tableau_checklist(schema)),
                }
        except SchemaError as e:
            st.session_state.pop("result", None)
            st.error("Fix these first:\n\n" + "\n".join(f"- {p}" for p in e.problems))

    res = st.session_state.get("result")
    if not res:
        return
    if res["snapshot"] != schema.to_dict():
        st.info("Settings have changed since this data was generated. Click **Generate data** to refresh it.")
    df = res["df"]
    fname = _slug(res["snapshot"]["name"])
    d1, d2, d3 = st.columns(3)
    d1.download_button("⬇ Download Excel (.xlsx)", res["xlsx"], f"{fname}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    d2.download_button("⬇ Download CSV", res["csv"], f"{fname}.csv", "text/csv")
    d3.download_button("⬇ Tableau field checklist", res["checklist"], f"{fname}_tableau_checklist.csv", "text/csv",
                       help="Field names and the type Tableau should detect. Compare against the real data "
                            "source before using Replace Data Source.")

    st.markdown(f"##### Preview (first {min(len(df), PREVIEW_ROWS):,} of {len(df):,} rows)")
    date_cols = {f["name"]: st.column_config.DateColumn(format="YYYY-MM-DD")
                 for f in res["snapshot"]["fields"] if f["kind"] == "date"}
    st.dataframe(df.head(PREVIEW_ROWS), hide_index=True, column_config=date_cols)
    st.markdown("##### Column summary")
    st.dataframe(summarize(df), hide_index=True)


def page_library():
    st.title("My field library")
    st.caption("Reusable field definitions. Add them to any dataset from **Build a dataset → From my library**.")
    lib = storage.list_library()

    if lib:
        st.dataframe(pd.DataFrame({
            "Field": [f.name for f in lib],
            "Type": [KINDS[f.kind]["label"] for f in lib],
            "Notes": [f.description for f in lib],
        }), hide_index=True)

    NEW = "➕ New library field"
    names = [NEW] + [f.name for f in lib]
    if "lib_pick_next" in st.session_state:  # widget value can only be set before it is drawn
        st.session_state.lib_pick = st.session_state.pop("lib_pick_next")
    if st.session_state.get("lib_pick") not in names:
        st.session_state.lib_pick = NEW
    pick = st.selectbox("Edit a field", names, key="lib_pick")
    if st.session_state.get("lib_loaded") != pick:
        st.session_state.lib_loaded = pick
        src = Field(name="") if pick == NEW else next(f for f in lib if f.name == pick)
        st.session_state.lib_field = _field_state(src)
    fd = st.session_state.lib_field
    with st.container(border=True):
        fd = field_editor(fd, f"lib_{fd['_id']}", rows=1)
        st.session_state.lib_field = fd

    c1, c2 = st.columns([1, 3])
    new_name = fd["name"].strip()
    clash = new_name and storage.library_item_exists(new_name) and new_name.lower() != (
        "" if pick == NEW else pick.lower())
    if clash:
        st.warning(f"Another library field is already called '{new_name}'. Saving will replace it.")
    if c1.button("💾 Save", type="primary", disabled=not new_name):
        if pick != NEW and pick.lower() != new_name.lower():
            storage.delete_library_item(pick)  # renamed
        storage.save_library_item(_to_field(fd))
        st.session_state.lib_loaded = None
        st.session_state.lib_pick_next = new_name
        st.toast(f"Saved '{new_name}'")
        st.rerun()
    if pick != NEW and c2.button("🗑 Delete from library"):
        storage.delete_library_item(pick)
        st.session_state.lib_loaded = None
        st.session_state.lib_pick_next = NEW
        st.toast(f"Deleted '{pick}'")
        st.rerun()


def page_help():
    st.title("How to use SynthGen")
    st.markdown(f"""
**What it's for:** making fake data with the same columns and roughly the same shape as a real dataset,
so you can build or fix a Tableau dashboard without touching the real data. When the dashboard is ready,
point it at the real data with **Data → Replace Data Source** in Tableau.

**Steps**
1. **Build a dataset → Add fields.** The quickest way is *Paste a list*: copy the column names and
   types from a data dictionary.
2. Open each field and set realistic rules: ranges, category labels, date ranges, % blank.
3. **Save dataset** so you can come back and tweak it later.
4. **Generate data**, check the preview and column summary, then download Excel or CSV.
5. Open the file in Excel or connect Tableau to it.

**Getting the Tableau swap to work**
- Field names must match the real data **exactly**, including spaces. Download the
  *Tableau field checklist* and compare it with the real source.
- Use the **real category labels** (e.g. actual college names) when they aren't sensitive. Filters,
  colors and groups in Tableau remember specific values and will break if the labels differ.
- Keep ranges and row counts close to the real data so axes and color scales look right.

**Privacy:** only type in field names, types and non-sensitive labels. Never paste real records such as
IDs, names or emails.

**Where your work is saved:** `{storage.home_dir()}`
(one file per dataset and per library field. Copy them to share with a colleague.)
""")


PAGES = {"Build a dataset": page_build, "My field library": page_library, "How to use": page_help}
with st.sidebar:
    st.markdown("## 🧪 SynthGen")
    st.caption("Synthetic data for dashboard building")
    page = st.radio("Go to", list(PAGES), label_visibility="collapsed")
PAGES[page]()
