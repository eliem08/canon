# Paid pilot proposal (template)

*Sales material for US, UK and EU buyers. Prices are hypotheses to validate in discovery; no customer, partnership or certification exists yet. Never present synthetic-data numbers as client results. Updated 2026-10-31.*

## Who it is for

B2B companies of roughly 200–2,000 employees on Salesforce or HubSpot, with contracts as PDFs and customer
conversations in Slack or Teams, that are rolling out (or evaluating) AI agents on customer data. US first; UK and
EU where processing inside the company's environment matters.

## Scope

- One CRM export (or read-only API pull), up to 1,000 contracts, one Slack or Teams export.
- Up to 3 roles for the permission test; up to 30 questions written by your team (optional evaluation).
- Duration: 2 weeks, plus a week-2 comparison on a fresh export.

## Deliverables

Dashboard (`index.html`) and full report; `crm_fixes.csv`, `quarantine.csv`, `renewals.csv`; `review.html` for account
owners; week-2 comparison; optional agent trial and before/after evaluation; deletion receipt (`canon purge`).

## Success metrics (agree the numbers before starting)

| Metric | How it is measured | Target to agree |
|---|---|---|
| Stale CRM values confirmed real | Your team checks a random sample of 30 lines of `crm_fixes.csv` | ≥ X% confirmed |
| Duplicates resolved | Merges confirmed in `review.html` | ≥ N |
| Renewals surfaced | `renewals.csv` lines not already tracked | ≥ 1 |
| Time to deliver | Export received → report | ≤ 10 working days |
| Permission test (if included) | Agent responses citing records the role may not read | 0 |
| Week-2 progress | `--compare`: stale values fixed | Reported |

## Your responsibilities

Provide the exports and a machine; name an owner for the review page; 3–4 hours of staff time; written consent before
any hosted model sees data (otherwise use a model you host).

## Exclusions

No CRM write-back, live sync, hosted service, legal or compliance advice.

## Price (hypothesis)

Design partner: **$15,000–25,000** fixed, in exchange for a reference and permission to publish anonymised results.
Standard: **$35,000–50,000**. See `PRICING_AND_PACKAGING.md`.

## Conversion

If the metrics are met: annual subscription for recurring audits (`--compare`), the agent server for named users
and support.

## Timeline

| Day | Step |
|---|---|
| 0 | Data request (`docs/DATA_REQUEST.md`); security questions answered; machine ready |
| 1 | Intake check (`canon check`), configuration (`canon.json`) |
| 2–3 | `canon pilot`, first walkthrough |
| 4–6 | Account owners answer the review page; rerun |
| 7–10 | Final report, renewal calendar, optional agent trial and evaluation |
| +7 | Week-2 comparison on a fresh export; deletion with receipt |
