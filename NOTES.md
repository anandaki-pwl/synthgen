# SynthGen: Working Notes

Things to keep in mind while changing this code: why certain pieces are written the way they
are, traps already hit, and how to test. Architecture is in [DESIGN.md](DESIGN.md).
Add to this file whenever you learn something the code doesn't make obvious.

## Guiding principles

- **Never let real data in.** Don't add features that read real data files or infer a schema from
  them. Users type field names, types and non-sensitive labels only.
- **Tableau swap compatibility beats prettiness.** Exact field names and the right Tableau type
  per field matter more than anything else. Anything that could change a column's detected
  type (a time on a date, a blank turning ints into floats) is a bug.
- **Users never edit code.** Every setting must be reachable in the UI, and error messages must be
  plain English, naming the field and what to change.
- **Keep `engine/` free of Streamlit.** Logic goes in the engine with tests; `app.py` is just UI.

## Generation: why it's written this way

- **One RNG stream per field, seeded from `(seed, lowercased field name)`.** Adding, removing or
  reordering fields doesn't change the values in other columns, so users can tweak one field
  without everything else reshuffling. Side effects:
  - *Renaming* a field changes its values. That's expected.
  - Lowercasing matches the case-insensitive duplicate-name check (Tableau treats `GPA` and
    `gpa` as the same field).
  - Phase 3 dependent fields must keep this: derive from the field's own stream, don't share one.
- **Nullable dtypes (`Int64`, `boolean`) on purpose.** With plain numpy dtypes, adding blanks
  turns whole numbers into floats (`3` → `3.0`) and Tableau would detect Number (decimal).
  Don't "simplify" these to `int64`/`bool`.
- **Unique whole numbers ignore the distribution setting.** They're sampled evenly without
  replacement. Shaping a unique sample wasn't worth the complexity; mention this if anyone asks.
- **`_dedupe` is a fallback, not the main path.** Exact methods are used where possible: sampling
  without replacement for whole numbers, categories and dates, and a shuffled row-number suffix
  for emails. `_dedupe` redraws duplicates up to 50 rounds, mainly for ID patterns, decimals and
  datetimes. `validate_field` blocks the impossible cases. An ID pattern *close to* its capacity
  (e.g. 9,990 rows from `####`) can still exhaust the rounds and raise `SchemaError`.
- **Blanks are applied after generation.** That means `unique` covers non-blank values only, and
  blank % is approximate (random per row, not an exact count).
- **`date` values are midnight timestamps** (`datetime64`), not Python `date` objects. That keeps
  pandas/Excel handling uniform; export is responsible for dropping the time (see below).
- **Category weights:** `None` means equal weights. The UI only writes weights when at least one
  line has `| weight`; lines without one default to 1.

## Export: traps already hit

- **CSV dates must not include a time.** pandas' `date_format` applies to every datetime column,
  so `date` fields came out as `2023-07-31 00:00:00` and Tableau would read them as Date & Time.
  Fixed by passing the schema to `to_csv_bytes(df, schema)`, which formats `date` fields as
  `YYYY-MM-DD`. Any new export path needs the same treatment. Covered by `test_exports_round_trip`.
- **pandas 3: `astype(str)` keeps NaN as NaN**, not the string `"nan"`. `len()` on it crashed
  the Excel column-width code. Drop nulls and use `str(v)` when measuring text.
- **Excel date cells are datetimes with a date number format** (`yyyy-mm-dd`). Not yet verified
  that Tableau detects these as Date rather than Date & Time when connecting to the `.xlsx`.
  Worth checking once in real Tableau. If it's wrong, write those columns as Python `date` objects.
- **Excel build time:** openpyxl is slow for very large sheets, and we also loop over date cells
  to set number formats. The UI warns above 200k rows. If it becomes a problem, consider
  `xlsxwriter` (faster, write-only) as the engine. That's an extra dependency.
- CSV is written UTF-8 **with BOM** (`utf-8-sig`) so Excel shows accented characters correctly.
  Tableau handles the BOM fine.

## Storage

- **Schemas embed full field copies; they don't link to library items.** Editing a library field
  doesn't silently change old datasets (which could break a dashboard already built on them).
  If "update all datasets that use this field" is ever wanted, make it an explicit action.
- File names are slugs, so `Student ID` and `student_id` collide. The UI warns before
  overwriting. Renaming a library item deletes the old file, then saves the new one.
- `SYNTHGEN_HOME` overrides the data folder. **Always set it to a temp folder when testing** so
  you don't write into the user's real `~/SynthGen`.

## Streamlit UI gotchas

- **Widget keys are `{form_id}_{field _id}_...`.** `form_id` is regenerated when a dataset is
  loaded (and after bulk adds), which resets every widget to the loaded values. Without it,
  Streamlit keeps stale widget state from the previous dataset.
- **Kind-specific option widgets include the kind in their key** (`{key}_{kind}_min`). Switching
  a field's type then starts from that kind's defaults instead of reusing values from another kind.
- **You can't set a widget's session-state value after the widget is drawn** in the same run.
  The library page uses a `lib_pick_next` hand-off: set it, `st.rerun()`, and apply it *before*
  the selectbox renders.
- **`st.number_input` rejects mixed int/float arguments.** That's why mean/std are cast with
  `cast(...)`/`float(...)`: JSON can load `50` where a float is expected.
- Widgets are created with both `value=` and `key=`. That's fine as long as we never write to
  those keys through `st.session_state` (we don't, except the `lib_pick` hand-off above).
- Move/remove buttons record an `action` and apply it after the loop, then `st.rerun()`.
  Changing the list while iterating it breaks the widget layout.
- Generation output is cached in `st.session_state.result` along with a snapshot of the schema.
  The "settings changed" notice compares the snapshot with the current schema.
- `.streamlit/config.toml` only applies when Streamlit runs from the repo folder (`launch.bat`
  does `cd /d "%~dp0"`).

## launch.bat

- Must keep **CRLF line endings**; `.gitattributes` enforces `*.bat eol=crlf`. Batch files with LF
  endings can misbehave in strange ways (labels and `goto` breaking).
- Reinstall detection: compares `requirements.txt` with `.venv\installed.txt` using `fc /b`.
  Changing requirements triggers a reinstall on users' next launch.
- **Windows path length:** creating a venv under a very deep path failed with `WinError 206`.
  Users should keep the app somewhere short, like `Documents\SynthGen`.
- Not yet tested on a clean machine. First real run is the true test.

## Testing

- Unit tests: `python -m pytest` from the repo root (`pytest.ini` sets `pythonpath = .`).
- UI tests: Streamlit's `streamlit.testing.v1.AppTest` works well for driving the real app
  headlessly (paste fields, change kinds, save, generate, reorder, library rename). Notes:
  - `AppTest.from_file` resolves relative paths against the *calling* file, so pass an absolute
    path to `app.py`.
  - Set `SYNTHGEN_HOME` to a temp folder first.
  - On Windows, set `PYTHONIOENCODING=utf-8` before printing labels that contain emoji.
  - Consider promoting this into `tests/test_app.py` once the UI settles.
- Visual check: run `streamlit run app.py --server.headless true` and open it in a browser.
- Versions developed and tested on: Python 3.13, pandas 3.0, numpy 2.5, streamlit 1.66,
  openpyxl 3.1. `requirements.txt` has lower floors that are **untested**. If a user on older
  versions hits problems, raise the floors.

## Open questions / to verify

- Does Tableau detect Excel date columns as Date (not Date & Time)? See the Export section.
- Do users want weighted categories entered differently (e.g. percentages that must sum to 100)?
- Phase 3 design: how should a user express "Department depends on College" in the UI?
  One idea: a two-column paste (parent, child). Not discussed with users yet.
