# SynthGen

Make fake (synthetic) datasets with the same columns and shape as a real one, so dashboards can be
built or fixed without touching real data. When the dashboard is ready, swap in the real data with
Tableau's **Data → Replace Data Source**.

## For users

**One-time setup:** install Python from <https://www.python.org/downloads/> and tick
**"Add python.exe to PATH"** in the installer.

**To start:** double-click `launch.bat`. The first time, it spends a minute or two installing what it
needs. Then SynthGen opens in your web browser. Keep the black window open while you use it, and close
it when you're done.

**Using it:** the **How to use** page inside the app has step-by-step instructions.

**Your saved datasets and library** live in a `SynthGen` folder in your user folder (for example
`C:\Users\<you>\SynthGen`). They aren't stored in the app folder, so they survive updates. Each
dataset and library field is a small `.json` file you can copy to share with a colleague.

## For maintainers

```
app.py              Streamlit interface
engine/fields.py    Field/Schema definitions, field kinds, validation, paste-list parser
engine/generate.py  value generators and summary statistics
engine/storage.py   JSON save/load (SYNTHGEN_HOME env var overrides the folder)
engine/export.py    CSV, Excel and Tableau-checklist output
tests/              pytest suite: run `python -m pytest` from this folder
```

Adding a new field kind takes three steps: add it to `KINDS` in `fields.py` (plus any checks in
`validate_field`), write a `_gen_<kind>` function in `generate.py` and register it in `_GENERATORS`,
then add its inputs to `field_editor` in `app.py`.

Each column gets its own random stream seeded from the dataset seed and the field name, so editing
one field never changes the values in the others.

Datasets are capped at 1,000,000 rows to stay under Excel's sheet limit.
