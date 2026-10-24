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

## Free-form contracts (real contracts: CUAD)
Real contracts don't follow Canon's template ("Le Client :", "Date d'effet :"). When those lines are
missing, `canon/ingest/contract_terms.py` reads what most commercial contracts share, in English and
French:
- the preamble's parties: "by and between A, a Delaware corporation ("A"), and B ...",
  "Entre les soussignés : A ... et B ...", "Party A: ...";
- the agreement date, from the sentence that introduces *this* contract or a "Dated:" title line,
  skipping dates that name another document ("the Supply Agreement dated ...");
- the effective date, from a defined term (`<date> (the "Effective Date")`) or "effective as of";
- the end date (`renewal_date`), from "shall expire on / end as of / until <date>", a term range
  ("TERM: <date> to <date>", "durée : du … au …"), or computed from "a term of three (3) years from the
  Effective Date" (a term with no stated start runs from the effective date; one that starts at a later
  event is refused) or "until the end of the current calendar year". An *option* to extend is not the
  end date. A computed date carries a
  `derived_from_term_length` warning, and a stated end date wins over a computed one.

Two readings that disagree are refused (`conflicting_values_in_contract`). Numeric dates like
03/04/2021 are read only when the deployment states its date order (`ingest.dayfirst` in
`canon.json`). A contract lists every party in `parties`; which one is the **customer** is decided
only with the deployment's own legal names (`ingest.own_names`). Without them the record has no name
rather than a guessed one.

**Measured on CUAD v1** (510 public commercial contracts from SEC filings, answers normalized by
lawyers, CC BY 4.0; `uv run python scripts/cuad_benchmark.py --split all`). The rules were written
against the dev half only. Test half (267 contracts):

| field | before (template only) | recall | precision | wrong values |
|---|---|---|---|---|
| parties (one listed party found) | 0% | 57% | 99% | 1 |
| agreement date | 0% | 66% | 94% | 7 |
| effective date | 2% | 60% | 95% | 5 |
| end date | 0% | 28% | 90% | 4 |

Full table (dev and test): [`reports/cuad_report.md`](reports/cuad_report.md). The files are downloaded
at a pinned revision into `~/.cache/canon` (or `$CANON_CACHE`); no CUAD text is committed.

What this shows, and what it doesn't:
* The template-only connector read nothing from real contracts. The general reader gets the parties
  and the start dates of most contracts, with a few wrong values per hundred. The end date is still
  usually missed: real term clauses are relative ("until the later of ...", "renews each year"),
  and the reader refuses rather than guesses.
* CUAD is US and English. French rules are only tested on sentences written for the tests. The first
  French-language client corpus has to be measured the same way before any accuracy is quoted.
* Contract values aren't scored: CUAD has no normalized amount answer.

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

## OCR on real scans: receipts (SROIE)
`uv run --with pyarrow python scripts/receipts_benchmark.py --split test`
([`reports/receipts_report.md`](reports/receipts_report.md)). ICDAR 2019 SROIE: real scanned shop receipts
(Malaysia, English) with human transcriptions and labelled company, date and total; 361 held-out receipts.
The text from `ocr_image` goes through Canon's own parsers, with that deployment's conventions (day first,
two-digit years in the 2000s).

| test, 361 receipts | date correct | date wrong | date withheld | total read | company found |
|---|---|---|---|---|---|
| before (two-digit years refused, no digit mask) | 63% | 3% (12) | 13% | 78% | 84% |
| + `century: 20` | 76% | 4% (16) | 19% | 78% | 84% |
| + unsure digits withheld | 59% | **2% (8)** | 39% | 60% | 82% |
| + unsure digits re-read alone first (**default now**) | 63% | **2% (8)** | 35% | 62% | 82% |
| human transcription, parsers only | 98% | 1% (5) | 0% | 99% | 100% |

Rows don't add to 100%: some receipts have no labelled date, or one in a format that is not a date.

* OCR recovers about 80% of the transcription's words (70% once unsure digit words are withheld).
  Receipts are small, faint thermal prints.
* **The trade-off is explicit.** Withholding unsure digits halves the wrong dates (16 → 8) but loses about a
  fifth of the correct dates and totals. For an audit, a refused value is a line in the quarantine report and
  a wrong one is a wrong answer, so the default favours refusing. A deployment can set
  `OCRConfig.min_digit_confidence = 0` to keep them.
* **Unsure digits are withheld.** On the dev receipts every wrong date was a misread digit (5→6, 8→3) that
  tesseract read at confidence 58–77, so digit words below 80 become `[?]` (`OCRConfig.min_digit_confidence`)
  and the document gets an `unsure_ocr_digits` warning. Dev: wrong dates 5 → 0, correct 50 → 36; test in the
  table above.
* **Unsure digits are re-read before being withheld:** the word is cropped, enlarged 3x and read alone in single-line
  mode, and the re-read is kept only if tesseract is at least 85 sure of it. On test it recovers 14 dates and 5 totals
  without adding a wrong value, at about 3.5x the OCR time (5.5 s per receipt on one thread).
* **Two-digit years** (`20/03/18`) are on 19% of these receipts. They are read only when the deployment sets
  `ingest.century`.
* The remaining wrong dates on test come from the first date on the receipt not being the purchase date
  (the transcription-only row has 5 of those) and a few confident misreads.
* Upscaling small images before OCR was tried on dev and made results worse; it is not used.

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
