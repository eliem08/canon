# What Canon measurably does: the proof sheet

*For the founder and technical buyers. Every line links to the report that produced it and can be rerun from the repo.
Synthetic data is labelled as such; "real data" means public datasets Canon's authors did not write. No client data
yet: we will measure all of this again on yours.*

## The headline: agents stop reading what people may not see

| | Keyword RAG | Strong RAG | **Canon** |
|---|---|---|---|
| Answers whose context held a record the caller may not read (4,400 answers, 110 callers, 10 datasets) | 70% | 87% | **0%** |
| … for a caller with **no access at all** | 100% | 100% | **0%** |
| … for a sales rep | 65% | 85% | **0%** |

Source: [`reports/permission_report.md`](../reports/permission_report.md). A leak is decided by what is retrieved, not by
the model, so this holds for any model. Canon applies permissions before it scores or returns anything. A retrieval
system over the raw export has no notion of who is asking.

## Accuracy: on par with a good retrieval system, far above a naive one

| 4 open models, 40 synthetic questions | Keyword RAG | Strong RAG | **Canon** |
|---|---|---|---|
| Correct answers | 55–58% | 92.5% | **97.5%** |
| Context the model reads per answer | 2.0k chars | 3.7k chars | **1.3k chars** (−65%) |

The gap to strong RAG is **not statistically significant** (p ≥ 0.5), so we don't claim it. The gap to keyword search is
(p < 1e-4). Source: [`reports/eval_summary.md`](../reports/eval_summary.md).

## The audit finds what is wrong, and says how to fix it

- **Stale CRM values** found on the synthetic export: 62, all correct; 2 of 64 missed (precision 1.00, recall 0.97).
- **Delivered as fixes:** `crm_fixes.csv` uses the CRM's own record ids and column names, ready for a bulk update;
  `quarantine.csv` gives every refused value a reason and an action; `review.html` lets account owners confirm duplicates.

## It holds up on real data (public datasets, held-out halves)

| What | Real data | Result |
|---|---|---|
| Contract terms | 510 SEC-filed contracts (CUAD), lawyer answers | parties 57% found, 99% right; agreement date 66% / 94%; effective date 60% / 95%; end date 28% / 90%; auto-renewal period 41% found, 0 wrong; notice to stop renewal 37% found, 0 wrong |
| Duplicate customers, US listings | Fodors–Zagat | F1 0.948 (exact-name matching: 0.825) |
| Duplicate customers, French companies | INSEE SIRENE registry vs shop signs | 29% linked automatically and 28% sent to a person, 91% precision (exact names: 24% recall) |
| Arabic ↔ Latin names | 23k real Arabic names with transliterations | 97.8% of true pairs at 0.85 similarity, 0.10% false matches |
| OCR on scans | 361 real scanned receipts (SROIE) | dates 63% right, 2% wrong; the rest withheld rather than guessed |

Sources: [`cuad_report.md`](../reports/cuad_report.md), [`er_real_report.md`](../reports/er_real_report.md),
[`er_french_report.md`](../reports/er_french_report.md), [`arabic_names_report.md`](../reports/arabic_names_report.md),
[`receipts_report.md`](../reports/receipts_report.md). Each real-data test found bugs in Canon (US phone numbers refused,
French acronyms missed, date formats, misread digits). They were fixed and the fixes are measured above.

## The design choice behind every number: refuse rather than guess

When a value can't be read safely (an ambiguous date, an unsure OCR digit, two contract dates that disagree), Canon
leaves it out and says why. It does not pick one. That is why wrong values stay at 0–10% while recall varies.
For an audit, a refused value is a line in the quarantine report. A wrong one is a wrong answer given to a customer.

## What is not proven yet

- **Your data.** French and Arabic contracts, your CRM's quirks, your questions. The first audit measures this.
- **Accuracy advantage over a good RAG** on real questions. We expect parity plus the permission and citation advantages.
- **End dates in contracts** are still mostly missed on CUAD (28%). Renewal periods and notice periods are now measured on CUAD's held-out half (above); the computed next-renewal and cancel-by dates follow from them but are not scored on their own.

## Rerun any of it
```bash
uv run python scripts/permission_benchmark.py --seeds 10
uv run python scripts/cuad_benchmark.py --split all
uv run --with pyarrow python scripts/er_benchmark.py --split all
uv run --with pyarrow python scripts/french_er_benchmark.py --split all
uv run python scripts/arabic_names_benchmark.py --split all
uv run --with pyarrow python scripts/receipts_benchmark.py --split test
```
