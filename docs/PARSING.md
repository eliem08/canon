# Value parsing and quarantine

`canon/ingest/parsing.py` parses amounts, dates and phone numbers for every connector under one rule:
**refuse rather than guess.** A refused value produces no `Fact`. Instead, a `ParseIssue(record_id, field, raw, reason)` is attached
to the source record, stored in the `parse_issues` table and written to `out/quarantine.json`. `canon resolve` prints the count.

| Input | Accepted | Refused (reason code) |
|---|---|---|
| Amounts | `1,426,000.00`, `1.426.000,00`, `1 426 000,00` (incl. no-break/thin spaces), `1'426'000.50`, `٬`-grouped Arabic-Indic digits, `450k`, `1,2 million`, `مليون`, currency `MAD/DH/dirhams/درهم/د.م.` before or after | `ambiguous_separator` (`1.426,000`, `1234.567`), `malformed_grouping` (`1.42.000`, `12,34,567`), `multiple_amounts`, `negative_or_signed`, `unexpected_currency:EUR`, `mixed_currencies`, `implausible_value`, `malformed_amount` (`1e6`) |
| Dates | ISO (with time), `dd/mm/yyyy` `-` `.` (order from `dayfirst`), `17 mars 2026`, `1er mars`, `March 1, 2028`, `1st March 2028`, `17 مارس 2026`, Moroccan/Maghreb month names (`غشت`, `شتنبر`, `جوان`…), Arabic-Indic digits | `impossible_date` (`31/02/2026`), `two_digit_year`, `month_only` (`mars 2028`), `multiple_dates`, `implausible_year`, `conflicting_date_conventions_in_file` |
| Phones | E.164, `00` prefix, national `0…` with `IngestConfig.default_country`, `(0)` trunk, dots/dashes/spaces, labels (`Tél :`), extensions (`poste 12`), alternates (`a / b`), Arabic-Indic digits | `missing_country_or_trunk_prefix`, `bad_national_format`, `bad_length_for_country`, `invalid_prefix`, `placeholder`, `fax_number`, `contains_letters` |

**Conventions are explicit.** `IngestConfig(default_country="212", currency="MAD", dayfirst=None)` is passed to `load_all`:
- **Day/month order:** with `dayfirst=None` the CRM connector infers it per export file from dates that can only be read one way. If one file mixes both orders, its ambiguous dates are quarantined.
- **Currency:** facts carry no currency, so a value in any other currency is quarantined, never mixed in.

**Warnings** (value kept, assumption logged with severity `warning`):
- `single_separator_read_as_thousands`: `450.000` and `1,426` are read as thousands.
- `alternate=…`: a field held several phone numbers.
- `country_unverified`: an international number with an unknown calling code.

## Evidence
- `tests/fixtures/parsing_cases.json` holds 107 adversarial cases, 43 of which must be refused.
  - Parsers before this change: 56/107 correct, **32 silent wrong values**, 3 crashes. For example, `1,426,000.00` in a contract became 142,600,000, and `31/02/2026` raised an exception that aborted the whole ingest.
  - After: **107/107, zero silent wrong values, no crashes** (`tests/test_parsing.py::test_no_silent_wrong_values_and_95_percent_correct`).
- 900 randomized round trips (amount formats, date languages, Moroccan phone styles, Arabic-Indic digits): every value parses back exactly.
- No regression on the synthetic dataset: ER F1 0.991, fact accuracy 0.968, eval 60% → 97.5%. 0 values quarantined, 16 thousands-assumption warnings, all correct reads.

## Not covered yet
- **Extraction from free text** (which number in a Slack message is the contract value) is still cue-based. This module only guarantees the number is read correctly once found (STATUS.md task 4).
- **Currency conversion** and VAT (HT/TTC) normalization: `Amount.tax_basis` is detected but not used.
- **Phone rules** cover a short list of countries (`COUNTRY_RULES`). Unknown calling codes are accepted with a warning.
