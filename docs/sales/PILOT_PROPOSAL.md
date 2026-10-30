# Paid pilot proposal (template)

*Sales material. Prices are hypotheses to validate in discovery; no customer, partnership or certification exists yet. Never present synthetic-data numbers as client results. Updated 2026-10-30.*

## Who it is for

B2B companies of 100 to 1,000 employees with a CRM (Salesforce, HubSpot or Dynamics), contracts in PDF or scans, and
customer conversations in WhatsApp or Teams, typically in Morocco or the francophone Maghreb, that are preparing to
connect an AI assistant to customer data.

## Offer

- **Scope.** One CRM, up to 1,000 contracts, one chat export, up to 3 roles for the permission map, and 30 client-written questions (optional).
- **Duration.** 2 weeks, plus a week-2 comparison.
- **Deliverables.**
  - the audit report and the three CSVs;
  - the review page and the comparison report;
  - a renewal calendar;
  - an optional MCP trial and eval.
- **Success metrics, agreed up front:**
  - ≥X stale or duplicate records confirmed by the client;
  - renewals with notice deadlines listed;
  - zero permission leaks on the role test.
- **Customer responsibilities.**
  - Provide the exports, a machine and 3–4 hours of staff time.
  - Name an owner for the review cards.
- **Exclusions.** No CRM write-back, no live sync, no hosted service, no legal advice.
- **Price hypotheses.**
  - **Design-partner offer:** 25–40k MAD (roughly €2.3–3.7k), with a testimonial.
  - **Standard:** 60–90k MAD.
  - **Subscription after the pilot:** 8–15k MAD/month for monthly audits and the MCP layer.
  - *All three need validation in discovery calls.*

## Success metrics (agree the numbers before starting)

| Metric | How it is measured | Target to agree |
|---|---|---|
| Stale CRM values confirmed real | Client checks a random sample of 30 lines of `crm_fixes.csv` | ≥ X% confirmed |
| Duplicates resolved | Merges confirmed in `review.html` | ≥ N |
| Renewals with notice deadlines | `renewals.csv` lines the client did not have tracked | ≥ 1 |
| Time to deliver | Days from export received to report | ≤ 10 working days |
| Permission test (if the agent trial is included) | Responses citing restricted records, per role | 0 |
| Week-2 progress | `--compare` report: stale values fixed | Reported, no target |

## Conversion to an annual contract

Offered if the success metrics are met: monthly or quarterly audits with `--compare`, the agent server for named
users, and support. Price hypothesis in the offer above.

## Timeline

| Day | Step |
|---|---|
| 0 | Data request sent, export prepared by the client, machine available |
| 1 | Intake check, configuration (`canon.json`) |
| 2–3 | Audit run, first walkthrough |
| 4–6 | Account owners answer the review page; rerun |
| 7–10 | Final report, renewal calendar, optional agent trial and eval |
| +7 | Week-2 comparison on a fresh export; deletion with receipt |
