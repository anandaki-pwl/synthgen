# SynthGen

Streamlit app for generating synthetic datasets that match the shape of real data, so Tableau
dashboards can be built without touching real data. Users are non-technical; they never edit code.

**Before making changes, read:**
- [DESIGN.md](DESIGN.md): architecture, data model, storage, roadmap, decision log
- [NOTES.md](NOTES.md): why things are written the way they are, traps already hit, how to test

**Keep them current:** update DESIGN.md when the architecture or roadmap changes, and add to
NOTES.md whenever you hit a gotcha or make a non-obvious choice.

**Quick reference**
- Run tests: `python -m pytest` from the repo root.
- When testing, set `SYNTHGEN_HOME` to a temp folder so you never write to the user's real `~/SynthGen`.
- `engine/` must not import Streamlit; UI code lives only in `app.py`.
- Never add anything that reads real data files.
