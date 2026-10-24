"""Minimal XLSX reader (stdlib only): the first worksheet as a list of dicts keyed by header.

Strings come from the shared-string table or inline strings. Numbers stay numbers, except
cells whose number format is a date, which become ISO dates. Excel stores dates as day
counts and only the cell style says "this is a date", so the style table is read too.
Formulas give their cached value. Anything unexpected is returned as text, so the
hardened parsers decide whether it can be read.
"""

from __future__ import annotations

import re
import zipfile
from datetime import date, timedelta
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
BUILTIN_DATE_FORMATS = set(range(14, 23)) | {27, 30, 36, 45, 46, 47, 50, 57}
_DATE_CODE = re.compile(r"[dmy]", re.IGNORECASE)


def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _text(node) -> str:
    return "".join(t.text or "" for t in node.iter(f"{{{NS['m']}}}t"))


def _first_sheet(z: zipfile.ZipFile) -> str:
    wb = ElementTree.fromstring(z.read("xl/workbook.xml"))
    sheet = wb.find("m:sheets/m:sheet", NS)
    rid = sheet.get(f"{{{NS['r']}}}id")
    rels = ElementTree.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = next(r.get("Target") for r in rels if r.get("Id") == rid)
    return target.lstrip("/") if target.startswith("/") else str(PurePosixPath("xl") / target)


def _date_styles(z: zipfile.ZipFile) -> set[int]:
    """Indexes of cell styles whose number format shows a date."""
    if "xl/styles.xml" not in z.namelist():
        return set()
    styles = ElementTree.fromstring(z.read("xl/styles.xml"))
    custom = {
        int(f.get("numFmtId")): f.get("formatCode", "")
        for f in styles.iterfind("m:numFmts/m:numFmt", NS)
    }
    out = set()
    for i, xf in enumerate(styles.iterfind("m:cellXfs/m:xf", NS)):
        fmt = int(xf.get("numFmtId", "0"))
        code = re.sub(r'"[^"]*"|\[[^\]]*\]', "", custom.get(fmt, ""))  # drop literals, colors
        if fmt in BUILTIN_DATE_FORMATS or (fmt in custom and _DATE_CODE.search(code)):
            out.add(i)
    return out


def _date1904(z: zipfile.ZipFile) -> bool:
    pr = ElementTree.fromstring(z.read("xl/workbook.xml")).find("m:workbookPr", NS)
    return pr is not None and pr.get("date1904") in ("1", "true")


def _serial_to_date(serial: float, date1904: bool) -> date:
    base = date(1904, 1, 1) if date1904 else date(1899, 12, 30)  # 1900 leap-year bug included
    return base + timedelta(days=int(serial))


def read_xlsx(path: Path) -> list[dict]:
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            sst = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
            shared = [_text(si) for si in sst.iterfind("m:si", NS)]
        dates, d1904 = _date_styles(z), _date1904(z)
        sheet = ElementTree.fromstring(z.read(_first_sheet(z)))
    rows: list[list] = []
    for row in sheet.iterfind("m:sheetData/m:row", NS):
        cells: dict[int, object] = {}
        for c in row.iterfind("m:c", NS):
            kind, v = c.get("t", "n"), c.find("m:v", NS)
            raw = v.text if v is not None else None
            if kind == "s" and raw is not None:
                value: object = shared[int(raw)]
            elif kind == "inlineStr":
                value = _text(c.find("m:is", NS))
            elif kind in ("str", "e"):
                value = raw
            elif kind == "b":
                value = raw == "1"
            elif raw is None:
                value = None
            else:
                number = float(raw)
                if int(c.get("s", "0")) in dates:
                    value = _serial_to_date(number, d1904).isoformat()
                else:
                    value = int(number) if number.is_integer() else number
            cells[_col(c.get("r"))] = value
        if cells:
            width = max(cells) + 1
            rows.append([cells.get(i) for i in range(width)])
    if not rows:
        return []
    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    return [
        {h: (r[i] if i < len(r) else None) for i, h in enumerate(header) if h}
        for r in rows[1:]
        if any(v not in (None, "") for v in r)
    ]
