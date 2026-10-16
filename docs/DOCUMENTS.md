# Documents connector

`canon/ingest/documents.py` turns contract files into text; `canon/ingest/contracts.py` parses it.
`load_contracts` walks the contracts folder **recursively**.

| Format | How | Notes |
|---|---|---|
| `.txt` | read as UTF-8 | pages split on form feeds if present |
| `.pdf` with a text layer | `pypdf`, page by page | |
| `.pdf` scanned (page text < 20 chars) | largest embedded image per page → grayscale + 3×3 median filter → `tesseract -l fra+ara+eng --psm 6` | mean word confidence < 60 → `low_ocr_confidence` warning |
| `.png` `.jpg` `.tif` | OCR as above | |
| `.docx` | stdlib `zipfile` + XML; explicit page breaks become pages | no tables/headers yet |

**Citations.** Pages are joined with form feeds, so every contract fact cites `file#p<page>:L<line>`
plus the line's text (`source_ref`, `quote`). Field captures never run across a page break.

**Access.** The nearest `_acl.json` (`{"acl": ["legal", "exec"]}`) between a file and the contracts
root sets the ACL of the documents below it; otherwise the connector default (`legal`, `exec`).

**Failures are reported, not skipped.** A corrupt PDF/DOCX, a scan when tesseract is not installed,
or a page with no text and no image produces a `ParseIssue` (`unreadable_pdf`, `unreadable_docx`,
`ocr_unavailable`, `no_text_or_image`) in `out/quarantine.json`, and no empty record.

**Arabic.** Tesseract returns right-to-left lines in visual order and sometimes reorders the label,
so the Arabic party name is read as "the Arabic words of the line containing الطرف, minus the label
words". Direction marks are stripped.

**CRM as CSV.** `load_crm` also reads `accounts.csv` (`,` or `;` delimited, BOM tolerated) with the
same `CRMFieldMap`. XLSX: export to CSV first.

## OCR results (synthetic)
`uv run python scripts/ocr_benchmark.py --out docs/reports/ocr_report.md` renders all 50 synthetic
contracts as 2-page image-only PDFs and reads them back. Full table:
[`reports/ocr_report.md`](reports/ocr_report.md).

See the table in the report (regenerated with each change to the OCR path).

## Install
`pypdf` and `pillow` are Python dependencies. OCR needs the tesseract binary with French and Arabic:
`apt-get install tesseract-ocr tesseract-ocr-fra tesseract-ocr-ara` (CI does this), or
`brew install tesseract tesseract-lang`. Without it, scans are listed as `ocr_unavailable`.

## Known gaps
* Synthetic scans are clean renders of one font. Skew, stamps, signatures, handwriting, low-DPI faxes
  and multi-column layouts are untested. Measure CER and field accuracy on a sample of the client's
  real scans before quoting accuracy.
* No layout analysis: tables and two-column contracts come out as interleaved lines.
* Vector-only PDFs without a text layer (rare) are not rasterized; they are reported as `no_text_or_image`.
