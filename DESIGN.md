# SynthGen: Design

How the tool is put together and why. For gotchas and "don't change this without knowing why"
details, see [NOTES.md](NOTES.md).

## Purpose and constraints

SynthGen makes fake datasets with the same columns and shape as a real dataset, so Tableau
dashboards can be built or fixed (originally to make them ADA compliant) without anyone touching
real data. When a dashboard is done, the user points it at the real data with Tableau's
**Data → Replace Data Source**.

Requirements that drive the design:

| Constraint | Consequence |
|---|---|
| Real data must never enter the tool | Users describe fields (name, type, rules, non-sensitive labels). The tool never reads a real data file. |
| Users aren't comfortable running scripts | Browser UI (Streamlit), started by double-clicking `launch.bat`. No code edits needed. |
| Output must survive the Tableau swap | Field names must match exactly, and each kind maps to a specific Tableau type. A "Tableau field checklist" export lists both. |
| Users review the data in Excel | `.xlsx` and `.csv` output, capped at 1,000,000 rows (Excel's sheet limit is 1,048,576). |
| Field definitions shouldn't be re-entered | Per-user field library and saved dataset schemas, stored as JSON. |

## Architecture

```
launch.bat ──► .venv (created on first run) ──► streamlit run app.py
                                                    │
app.py  (UI only: pages, widgets, session state)    │
   │                                                ▼
   └──► engine/  (pure Python, no Streamlit imports; usable from scripts/tests)
          fields.py     Field + Schema dataclasses, KINDS registry, validation,
                        paste-list parser (guess_kind / parse_field_list)
          generate.py   one generator per kind, generate() pipeline, summarize()
          wordlists.py  built-in first/last names and filler words
          export.py     CSV bytes, Excel bytes, Tableau checklist DataFrame
          storage.py    JSON save/load under the user's SynthGen folder
```

The key boundary: **`engine/` never imports Streamlit.** All logic lives there and is tested
directly. `app.py` only turns widget values into `Field`/`Schema` objects and displays results.
If the UI is ever replaced (another framework, a CLI, a hosted service), the engine stays as it is.

## Data model

**Field:** one column.

| Attribute | Meaning |
|---|---|
| `name` | Column header. Must match the real data exactly. |
| `kind` | Key into `KINDS` (see below). |
| `options` | Kind-specific settings, merged over the kind's defaults in `__post_init__`. |
| `blank_pct` | % of rows set to blank (0–100). |
| `unique` | Every non-blank value must differ. Only allowed where `KINDS[kind]["can_be_unique"]`. |
| `description` | Free-text note; shows up in the Tableau checklist. |

**Schema:** one dataset: `name`, `description`, `rows`, `seed`, `fields: list[Field]`.

**KINDS registry** (`engine/fields.py`) is the single source of truth for each kind's UI label,
Tableau type, default options, and whether it can be unique:

| kind | Tableau type | pandas dtype | Options |
|---|---|---|---|
| `whole_number` | Number (whole) | `Int64` | min, max, distribution, mean, std |
| `decimal` | Number (decimal) | `float64` | min, max, decimals, distribution, mean, std |
| `sequence` | Number (whole) | `Int64` | start, step |
| `category` | String | `object` | values, weights (or `None` = equal) |
| `id_pattern` | String | `object` | pattern (`#` digit, `@` letter, other chars literal) |
| `person_name` | String | `object` | part: full / first / last |
| `email` | String | `object` | domain |
| `free_text` | String | `object` | min_words, max_words |
| `date` | Date | `datetime64` (midnight) | start, end (ISO strings) |
| `datetime` | Date & Time | `datetime64` | start, end (ISO strings; end is inclusive to 23:59:59) |
| `boolean` | Boolean | `boolean` | pct_true |

Distributions for numbers: `uniform`, `normal` (clipped to min/max; mean defaults to the
midpoint, std to range/6), `right_skewed` (Beta(1.5, 5)), `left_skewed` (Beta(5, 1.5)).

## Storage

```
<home>/SynthGen/            (or $SYNTHGEN_HOME)
  library/<slug>.json       one Field per file
  schemas/<slug>.json       one Schema per file, fields embedded in full
```

- The folder lives outside the app, so updating or reinstalling the app never touches a user's work.
- File name = slug of the item name (lowercase, non-alphanumerics → `_`). Names that slug the
  same overwrite each other; the UI warns before replacing.
- Writes go to a `.tmp` file then `replace()`, so a crash can't leave half a file.
- Damaged JSON files are skipped when listing rather than breaking the app.
- **Schemas copy fields; they don't reference library items.** Editing a library field later doesn't
  change existing datasets. This is intentional (see NOTES.md).

Example schema file:

```json
{
  "name": "Enrollment test",
  "description": "",
  "rows": 1000,
  "seed": 42,
  "fields": [
    {"name": "Student ID", "kind": "id_pattern", "options": {"pattern": "PU########"},
     "blank_pct": 0.0, "unique": true, "description": ""}
  ]
}
```

## Generation pipeline (`engine/generate.py`)

```
generate(schema)
  ├─ validate_schema → raise SchemaError(problems) if anything is wrong
  └─ for each field:
       rng = default_rng([seed, *codepoints(lowercase field name)])
       series = _GENERATORS[kind](field, n, rng)
       apply blanks (rng.random(n) < blank_pct/100)
  → DataFrame in field order
```

- Validation happens before any generation, and all problems are reported together in plain English.
- Uniqueness: exact methods where possible (sampling without replacement for whole numbers,
  categories and dates; permutation suffix for emails). Otherwise `_dedupe` redraws duplicates
  for up to 50 rounds. `validate_field` rejects impossible cases up front (e.g. a pattern with too
  few combinations).
- `summarize(df)` feeds the "Column summary" table: blank %, distinct count, min/max for
  numbers and dates, top 3 values.

## Export (`engine/export.py`)

- **CSV:** UTF-8 with BOM (so Excel opens accents correctly). `date` fields are written as
  `YYYY-MM-DD` and `datetime` fields as `YYYY-MM-DD HH:MM:SS`.
- **Excel:** openpyxl via pandas. Sheet `Data`, bold frozen header, column widths fitted from the
  first 200 rows, `yyyy-mm-dd` number format on date fields.
- **Tableau checklist:** field name, expected Tableau type, notes. Exported as CSV.

## UI (`app.py`)

Three pages chosen in the sidebar: **Build a dataset**, **My field library**, **How to use**.

- `field_editor(fd, key, rows)` is shared by the builder and the library page. It draws the
  inputs for one field and returns the updated dict, showing validation warnings inline.
- Session state:
  - `schema`: the dataset being edited (plain dicts; each field carries a random `_id`)
  - `loaded_name`: which saved dataset is open
  - `form_id`: prefix for widget keys; regenerated to reset the form
  - `result`: last generation (df, csv/xlsx/checklist bytes, snapshot of the schema)
  - `lib_*`: library page state
- Generation is triggered by a button. All output bytes are built then and cached in
  `result`, so download buttons don't rebuild files on every rerun.

## Distribution

Each user installs Python once, then double-clicks `launch.bat`, which:
1. finds `python` or `py` on PATH;
2. creates `.venv` inside the app folder on first run;
3. (re)installs `requirements.txt` whenever it differs from `.venv/installed.txt`;
4. runs `streamlit run app.py`. `.streamlit/config.toml` keeps it on localhost, turns off
   usage stats and hides the Deploy menu.

Dependencies are deliberately minimal: streamlit, pandas, numpy, openpyxl.

## Extending

**Add a field kind:**
1. `engine/fields.py`: add to `KINDS`; add checks in `validate_field`; optionally map
   data-dictionary words in `_TYPE_WORDS`.
2. `engine/generate.py`: write `_gen_<kind>(f, n, rng) -> pd.Series` and register it in `_GENERATORS`.
3. `app.py`: add an `elif kind == ...` block in `field_editor`.
4. `tests/test_engine.py`: add it to `every_kind_schema()` (`test_covers_every_kind` fails until you do).
5. If it needs special export handling (like `date`), update `engine/export.py`.

## Roadmap

**Phase 3: realism.** This matters most for dashboards looking right.
- Hierarchies, e.g. College → Department → Program with consistent parent/child values.
- Dependent fields: End Date after Start Date; Credits Earned ≤ Credits Attempted.
- Calculated fields from other columns.
- Time trends and seasonality for line charts.

These will need fields to reference other fields, which means generating in dependency order
instead of independently. Keep each field's own RNG stream so unrelated columns stay stable.

**Later, if adoption grows:**
- Shared/team libraries. Currently per-user by decision; the JSON-per-item layout should make
  a shared folder or Git-backed library straightforward.
- Import/export buttons for schemas in the UI (today: copy the JSON files).

**Out of scope (by decision):**
- Multi-table / join generation. Users enter the final, already-joined shape of the data.
- Reading real data to infer a schema. This would break the privacy model.

## Decision log

| Decision | Why |
|---|---|
| No Tableau MCP | The Server/Cloud MCP is read/query only and would send data to the model. The Desktop authoring MCP is experimental and doesn't clearly cover the formatting that ADA work needs. Workbooks can't be shared with Claude anyway, so the plan became: synthetic data here, dashboard work by the user. |
| Streamlit UI | Pure Python, forms/tables/downloads built in, fast to build. |
| No pydantic / Faker | Fewer packages to install for non-technical users; built-in word lists and dataclass validation cover it. |
| JSON files, one per item | Human-readable, easy to copy and share, Git-friendly, no database. |
| Per-user library | Simplest to start; revisit if the tool takes off. |
| Excel always offered | Synthetic sets are small enough; the row cap keeps Excel from choking. |
