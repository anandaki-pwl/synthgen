"""Write a generated DataFrame to CSV or Excel, plus a Tableau field checklist."""
from __future__ import annotations

import io

import pandas as pd
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from .fields import Schema


def to_csv_bytes(df: pd.DataFrame, schema: Schema | None = None) -> bytes:
    # Date fields must be written without a time, or Tableau reads them as Date & Time
    # and the type won't match the real source at swap time.
    if schema is not None:
        df = df.copy()
        for f in schema.fields:
            if f.kind == "date" and f.name in df:
                df[f.name] = df[f.name].dt.strftime("%Y-%m-%d")
    # utf-8-sig so Excel opens accented characters correctly
    return df.to_csv(index=False, date_format="%Y-%m-%d %H:%M:%S").encode("utf-8-sig")


def to_excel_bytes(df: pd.DataFrame, schema: Schema, sheet_name: str = "Data") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name=sheet_name)
        ws = xw.sheets[sheet_name]
        ws.freeze_panes = "A2"
        for cell in ws[1]:
            cell.font = Font(bold=True)
        kinds = {f.name: f.kind for f in schema.fields}
        for i, col in enumerate(df.columns, start=1):
            letter = get_column_letter(i)
            sample = df[col].head(200).dropna()
            width = max([len(str(col))] + [len(str(v)) for v in sample]) + 2
            ws.column_dimensions[letter].width = min(width, 50)
            fmt = {"date": "yyyy-mm-dd", "datetime": "yyyy-mm-dd hh:mm:ss"}.get(kinds.get(col))
            if fmt:
                for (cell,) in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                    cell.number_format = fmt
    return buf.getvalue()


def tableau_checklist(schema: Schema) -> pd.DataFrame:
    """Field names and the type Tableau should detect, to compare with the real source."""
    return pd.DataFrame(
        {
            "Field name": [f.name for f in schema.fields],
            "Expected Tableau type": [f.tableau_type for f in schema.fields],
            "Notes": [f.description for f in schema.fields],
        }
    )
