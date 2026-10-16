"""Documents connector: text and scanned PDFs, DOCX, folder ACLs, unreadable files, CSV CRM."""

import csv
import json
import shutil
from pathlib import Path

import pytest

from canon.ingest import load_all
from canon.ingest.contracts import load_contracts, parse_contract
from canon.ingest.crm import load_crm
from canon.ingest.documents import OCRConfig, extract_text, ocr_available
from canon.ingest.testdocs import cer, docx, find_font, scanned_pdf, text_pdf

DATA = Path(__file__).resolve().parents[1] / "data" / "synthetic"
CONTRACT = DATA / "contracts" / "CN-2024-107_v2.txt"
needs_ocr = pytest.mark.skipif(
    not ocr_available() or not find_font(), reason="tesseract or DejaVu font missing"
)


def _pages(text: str) -> list[str]:
    lines = text.split("\n")
    return ["\n".join(lines[:14]), "\n".join(lines[14:])]


def _facts(record) -> dict:
    return {f.field: f.value for f in record.facts}


@pytest.fixture(scope="module")
def reference():
    return parse_contract(CONTRACT.read_text(encoding="utf-8"), "c", "x")["record"]


def test_text_pdf_reads_like_the_text_and_cites_pages(tmp_path, reference):
    pdf = tmp_path / "c.pdf"
    pdf.write_bytes(text_pdf(_pages(CONTRACT.read_text(encoding="utf-8"))))
    doc = extract_text(pdf)
    assert doc.method == "pdf" and doc.text.count("\f") == 1
    rec = parse_contract(doc.text, "c", str(pdf))["record"]
    assert _facts(rec) == _facts(reference)
    value = next(f for f in rec.facts if f.field == "contract_value")
    assert value.source_ref == f"{pdf}#p2:L2" and "461 000 MAD" in value.quote
    assert not [i for i in rec.issues if i.field == "phone"]  # no value read across a page break


def test_docx_page_breaks(tmp_path, reference):
    path = tmp_path / "c.docx"
    path.write_bytes(docx(_pages(CONTRACT.read_text(encoding="utf-8"))))
    doc = extract_text(path)
    assert doc.method == "docx" and doc.text.count("\f") == 1
    rec = parse_contract(doc.text, "c", str(path))["record"]
    assert _facts(rec) == _facts(reference) and rec.alt_names == reference.alt_names


@needs_ocr
def test_scanned_pdf_is_ocred(tmp_path, reference):
    src = CONTRACT.read_text(encoding="utf-8")
    pdf = tmp_path / "scan.pdf"
    scanned_pdf(_pages(src), pdf, find_font())
    doc = extract_text(pdf)
    assert doc.method == "ocr" and doc.ocr_confidence > 80
    latin = [ln for ln in src.split("\n") if ln.strip() and "الطرف" not in ln]
    got = [ln for ln in doc.text.replace("\f", "\n").split("\n") if "الطرف" not in ln]
    assert cer(" ".join(latin), " ".join(got)) < 0.05
    rec = parse_contract(doc.text, "c", str(pdf))["record"]
    facts = _facts(rec)
    for field in ("contract_number", "contract_value", "renewal_date", "contract_start"):
        assert facts[field] == _facts(reference)[field], field
    assert rec.name == reference.name and rec.tax_id == reference.tax_id


def test_missing_ocr_is_reported_not_skipped(tmp_path):
    pytest.importorskip("PIL")
    font = find_font()
    if not font:
        pytest.skip("no font")
    scanned_pdf(["Contrat N° : CN-9"], tmp_path / "scan.pdf", font)
    doc = extract_text(tmp_path / "scan.pdf", OCRConfig(binary="no-such-tesseract"))
    assert doc.method == "none" and doc.issues[0][0] == "ocr_unavailable"


def test_unreadable_documents_go_to_quarantine(tmp_path):
    (tmp_path / "broken.pdf").write_bytes(b"%PDF-1.4 not really")
    (tmp_path / "broken.docx").write_bytes(b"not a zip")
    (tmp_path / "notes.odt").write_bytes(b"ignored: unsupported suffix")
    unreadable: list = []
    assert load_contracts(tmp_path, unreadable=unreadable) == []
    assert {i.reason for i in unreadable} == {"unreadable_pdf", "unreadable_docx"}


def test_folder_acl_sidecar(tmp_path):
    shutil.copy(CONTRACT, tmp_path / "a.txt")
    (tmp_path / "board").mkdir()
    shutil.copy(CONTRACT, tmp_path / "board" / "b.txt")
    (tmp_path / "board" / "_acl.json").write_text(json.dumps({"acl": ["exec"]}))
    records = {r.record_id: r for r in load_contracts(tmp_path)}
    assert records["contract:a"].acl == ["legal", "exec"]
    assert records["contract:board/b"].acl == ["exec"]


def test_mixed_formats_resolve_like_text(tmp_path):
    """The synthetic contracts as PDFs and DOCX give the same contract facts as the .txt files."""
    src = DATA / "contracts"
    for i, path in enumerate(sorted(src.glob("*.txt"))):
        pages = _pages(path.read_text(encoding="utf-8"))
        if i % 2:
            (tmp_path / f"{path.stem}.docx").write_bytes(docx(pages))
        else:
            (tmp_path / f"{path.stem}.pdf").write_bytes(text_pdf(pages))
    mixed = {r.record_id: _facts(r) for r in load_contracts(tmp_path)}
    plain = {r.record_id: _facts(r) for r in load_contracts(src)}
    assert mixed == plain


def _write_csv(path: Path) -> None:
    rows = json.loads((DATA / "crm" / "accounts.json").read_text(encoding="utf-8"))
    columns = sorted({k for r in rows for k in r})
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, columns, delimiter=";")
        writer.writeheader()
        writer.writerows([{k: ("" if r.get(k) is None else r[k]) for k in columns} for r in rows])


def test_csv_crm_matches_json(tmp_path):
    _write_csv(tmp_path / "accounts.csv")
    from_csv = {
        r.record_id: (r.name, r.phone, _facts(r)) for r in load_crm(tmp_path / "accounts.csv")
    }
    from_json = {
        r.record_id: (r.name, r.phone, _facts(r)) for r in load_crm(DATA / "crm" / "accounts.json")
    }
    assert from_csv == from_json


def test_load_all_reads_csv_crm(tmp_path):
    (tmp_path / "crm").mkdir()
    _write_csv(tmp_path / "crm" / "accounts.csv")
    records = load_all(tmp_path)
    assert {r.source for r in records} == {"crm"} and len(records) > 20


DATE_COLUMNS = ("Renewal Date", "LastModifiedDate")


def test_xlsx_crm_matches_json(tmp_path):
    from canon.ingest.testdocs import xlsx

    rows = json.loads((DATA / "crm" / "accounts.json").read_text(encoding="utf-8"))
    path = tmp_path / "accounts.xlsx"
    path.write_bytes(xlsx(rows, DATE_COLUMNS))
    from_xlsx = {r.record_id: (r.name, r.phone, r.tax_id, _facts(r)) for r in load_crm(path)}
    from_json = {
        r.record_id: (r.name, r.phone, r.tax_id, _facts(r))
        for r in load_crm(DATA / "crm" / "accounts.json")
    }
    assert from_xlsx.keys() == from_json.keys()
    # renewal dates written as ISO in JSON come back from Excel serials unchanged
    same = sum(from_xlsx[k] == from_json[k] for k in from_json)
    assert same == len(from_json), [k for k in from_json if from_xlsx[k] != from_json[k]][:3]


def test_xlsx_reader_handles_dates_numbers_and_blank_rows(tmp_path):
    from canon.ingest.testdocs import xlsx
    from canon.ingest.xlsx import read_xlsx

    rows = [
        {"Id": "A1", "Renewal Date": "2027-03-01", "Annual Contract Value": 1426000},
        {"Id": "", "Renewal Date": "", "Annual Contract Value": None},  # blank row is dropped
        {"Id": "A2", "Renewal Date": "01/03/2027", "Annual Contract Value": "1 426 000 MAD"},
    ]
    path = tmp_path / "a.xlsx"
    path.write_bytes(xlsx(rows, ("Renewal Date",)))
    got = read_xlsx(path)
    assert got == [
        {"Id": "A1", "Renewal Date": "2027-03-01", "Annual Contract Value": 1426000},
        {"Id": "A2", "Renewal Date": "01/03/2027", "Annual Contract Value": "1 426 000 MAD"},
    ]


def test_xlsx_numeric_tax_id_lost_its_leading_zeros(tmp_path):
    """Excel turns `000133528873882` into the number 133528873882. The CRM loader must not
    silently store a different tax id: it refuses it."""
    from canon.ingest.testdocs import xlsx

    row = {"Id": "X", "Account Name": "Acme", "ICE": 133528873882, "Owner": "A B"}
    path = tmp_path / "accounts.xlsx"
    path.write_bytes(xlsx([row]))
    rec = load_crm(path)[0]
    assert rec.tax_id in (None, "000133528873882")
