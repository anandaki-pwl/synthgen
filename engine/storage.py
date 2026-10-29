"""Save and load field-library items and dataset schemas as JSON files.

Everything lives in one folder per user (default: <home>/SynthGen), so it
survives updates to the app. Set the SYNTHGEN_HOME environment variable to
use a different folder.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .fields import Field, Schema


def home_dir() -> Path:
    base = Path(os.environ.get("SYNTHGEN_HOME") or Path.home() / "SynthGen")
    for sub in ("library", "schemas"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_").lower()
    return s or "unnamed"


def _path(kind: str, name: str) -> Path:
    return home_dir() / kind / f"{_slug(name)}.json"


def _write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _list(kind: str) -> list[dict]:
    items = []
    for p in sorted((home_dir() / kind).glob("*.json")):
        try:
            items.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue  # skip a damaged file rather than breaking the whole app
    return sorted(items, key=lambda d: d.get("name", "").lower())


# ---- field library ----

def list_library() -> list[Field]:
    return [Field.from_dict(d) for d in _list("library")]


def save_library_item(f: Field) -> Path:
    p = _path("library", f.name)
    _write(p, f.to_dict())
    return p


def delete_library_item(name: str) -> None:
    _path("library", name).unlink(missing_ok=True)


def library_item_exists(name: str) -> bool:
    return _path("library", name).exists()


# ---- dataset schemas ----

def list_schemas() -> list[Schema]:
    return [Schema.from_dict(d) for d in _list("schemas")]


def save_schema(s: Schema) -> Path:
    p = _path("schemas", s.name)
    _write(p, s.to_dict())
    return p


def delete_schema(name: str) -> None:
    _path("schemas", name).unlink(missing_ok=True)


def schema_exists(name: str) -> bool:
    return _path("schemas", name).exists()
