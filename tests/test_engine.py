import io

import pandas as pd
import pytest

from engine import KINDS, Field, Schema, SchemaError, generate, parse_field_list, summarize
from engine import storage
from engine.export import tableau_checklist, to_csv_bytes, to_excel_bytes


def every_kind_schema(rows=500):
    fields = [
        Field("Row", "sequence"),
        Field("Student ID", "id_pattern", {"pattern": "PU@#######"}, unique=True),
        Field("Credits", "whole_number", {"min": 0, "max": 18, "distribution": "normal"}),
        Field("GPA", "decimal", {"min": 0, "max": 4, "decimals": 2, "distribution": "left_skewed"}, blank_pct=10),
        Field("College", "category", {"values": ["Engineering", "Science", "Liberal Arts"], "weights": [5, 3, 2]}),
        Field("Name", "person_name"),
        Field("Email", "email", {"domain": "example.edu"}, unique=True),
        Field("Comment", "free_text", blank_pct=50),
        Field("Admit Date", "date", {"start": "2022-01-01", "end": "2024-12-31"}),
        Field("Last Login", "datetime"),
        Field("First Gen", "boolean", {"pct_true": 30}),
    ]
    return Schema("Test", rows=rows, seed=7, fields=fields)


def test_covers_every_kind():
    assert {f.kind for f in every_kind_schema().fields} == set(KINDS)


def test_generate_shape_types_and_rules():
    df = generate(every_kind_schema())
    assert df.shape == (500, 11)
    assert list(df.columns) == [f.name for f in every_kind_schema().fields]
    assert df["Row"].tolist() == list(range(1, 501))
    assert df["Student ID"].is_unique and df["Student ID"].str.match(r"^PU[A-Z]\d{7}$").all()
    assert df["Email"].is_unique
    assert df["Credits"].between(0, 18).all() and str(df["Credits"].dtype) == "Int64"
    assert df["GPA"].dropna().between(0, 4).all()
    assert 0.03 < df["GPA"].isna().mean() < 0.2
    assert df["GPA"].dropna().mean() > 2  # left-skewed: mostly high
    assert set(df["College"]) <= {"Engineering", "Science", "Liberal Arts"}
    assert df["College"].value_counts().idxmax() == "Engineering"
    assert pd.api.types.is_datetime64_any_dtype(df["Admit Date"])
    assert df["Admit Date"].between("2022-01-01", "2024-12-31").all()
    assert 0.2 < df["First Gen"].mean() < 0.4


def test_same_seed_same_data_and_columns_independent():
    s = every_kind_schema()
    a = generate(s)
    assert a.equals(generate(s))
    s.fields = [f for f in s.fields if f.name != "Credits"][::-1]  # drop one and reorder
    b = generate(s)
    assert a["GPA"].equals(b["GPA"])


def test_validation_reports_problems():
    s = Schema("", rows=100, fields=[
        Field("X", "whole_number", {"min": 10, "max": 1}),
        Field("x", "category", {"values": ["a", "b"]}, unique=True),
        Field("D", "date", {"start": "2024-02-01", "end": "2024-01-01"}),
        Field("P", "id_pattern", {"pattern": "#"}, unique=True),
    ])
    with pytest.raises(SchemaError) as e:
        generate(s)
    text = "\n".join(e.value.problems)
    for phrase in ["needs a name", "must be unique", "minimum is larger", "can't all be unique",
                   "start date is after", "only allows 10"]:
        assert phrase in text


def test_parse_field_list():
    fields = parse_field_list("Student ID, string\nGPA\tdecimal\nAdmit Date | date\n"
                              "Updated, timestamp\nActive, yes/no\nCount, int\nJust A Name\n")
    assert [(f.name, f.kind) for f in fields] == [
        ("Student ID", "category"), ("GPA", "decimal"), ("Admit Date", "date"),
        ("Updated", "datetime"), ("Active", "boolean"), ("Count", "whole_number"),
        ("Just A Name", "category"),
    ]


def test_exports_round_trip():
    s = every_kind_schema(50)
    df = generate(s)
    csv = pd.read_csv(io.BytesIO(to_csv_bytes(df)))
    assert list(csv.columns) == list(df.columns) and len(csv) == 50
    xl = pd.read_excel(io.BytesIO(to_excel_bytes(df, s)))
    assert list(xl.columns) == list(df.columns) and len(xl) == 50
    assert pd.api.types.is_datetime64_any_dtype(xl["Admit Date"])
    assert tableau_checklist(s)["Expected Tableau type"].tolist()[3] == "Number (decimal)"
    assert set(summarize(df)["Field"]) == set(df.columns)


def test_storage_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHGEN_HOME", str(tmp_path))
    s = every_kind_schema()
    storage.save_schema(s)
    storage.save_library_item(s.fields[3])
    assert storage.list_schemas()[0].to_dict() == s.to_dict()
    assert storage.list_library()[0].name == "GPA"
    (tmp_path / "schemas" / "broken.json").write_text("{not json")
    assert len(storage.list_schemas()) == 1  # damaged file is skipped
    storage.delete_schema("Test")
    storage.delete_library_item("GPA")
    assert storage.list_schemas() == [] and storage.list_library() == []
