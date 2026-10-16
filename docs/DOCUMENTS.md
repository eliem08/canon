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

**Symlinks are skipped**, and so is any file whose real location is outside the contracts folder. A link would otherwise take its access rules from wherever it points.

**Access.** The nearest `_acl.json` (`{"acl": ["legal", "exec"]}`) between a file and the contracts
root sets the ACL of the documents below it; otherwise the connector default (`legal`, `exec`).

**Failures are reported, not skipped.** A corrupt PDF/DOCX, a scan when tesseract is not installed,
or a page with no text and no image produces a `ParseIssue` (`unreadable_pdf`, `unreadable_docx`,
`ocr_unavailable`, `no_text_or_image`) in `out/quarantine.json`, and no empty record.

**Arabic.** Tesseract returns right-to-left lines in visual order and sometimes reorders the label,
so the Arabic party name is read as "the Arabic words of the line containing الطرف, minus the label
words". Direction marks are stripped.

**CRM as CSV or XLSX.** `load_crm` also reads `accounts.csv` (`,` or `;` delimited, BOM tolerated)
and `accounts.xlsx` (first sheet; stdlib reader, `canon/ingest/xlsx.py`), with the same `CRMFieldMap`.
Excel date cells (day serials with a date format) become ISO dates. Identifiers that Excel stored as
numbers, such as a tax id that lost its leading zeros, are refused (`identifier_stored_as_number`),
and so are phones stored as numbers.

## OCR results (synthetic)
`uv run python scripts/ocr_benchmark.py --out docs/reports/ocr_report.md` renders all 50 synthetic
contracts as 2-page image-only PDFs and reads them back. Full table:
[`reports/ocr_report.md`](reports/ocr_report.md).

| | clean scan | 2% speckle noise |
|---|---|---|
| CER, Latin lines | 0.003 | 0.003 |
| contract number / value / start / renewal / signatory / tax id | 100% correct | 100% correct |
| Latin party name | 98% correct, **2% wrong** | 96% correct, **4% wrong** |
| Arabic party name | 95% correct, 0% wrong | 0% read, 0% wrong (refused) |
| seconds per document | 1.1 | 5.2 |

* Noisy pages are re-read with a median filter when tesseract's confidence is below 80. Without
  the filter, 2% speckle took Latin CER to 0.43 and contract values to 20% correct.
* The filter erases the dots that distinguish Arabic letters: Arabic names read from a denoised page
  were wrong 74% of the time, so they are now dropped with an `arabic_unreliable_after_denoise`
  warning.
* The Latin party name is the one field still read **wrong** without a flag (1–2 of 50 documents,
  e.g. a misread letter). It is an identity field, so entity resolution tolerates it, but it is
  not quarantined.

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
