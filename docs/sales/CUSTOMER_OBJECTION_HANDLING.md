# Objection handling

*Sales material. Prices are hypotheses to validate in discovery; no customer, partnership or certification exists yet. Never present synthetic-data numbers as client results. Updated 2026-10-30.*

Answer with evidence that exists; when it does not, say so.

| Objection | Honest answer | Evidence to show |
|---|---|---|
| "Our CRM vendor's AI does this." | It works inside that CRM. Canon reconciles the CRM with contracts and chat, in French and Arabic, and runs on your machine. If your truth is all in the CRM, you may not need us. | Demo: CRM value vs contract value with citation |
| "We can build RAG ourselves." | You can, and it will be about as accurate. On our tests it read restricted data in 35 of 40 answers for a sales rep; Canon read none. It also won't produce a fix list. | `docs/reports/eval_summary.md`, `permission_report.md` |
| "Has it worked for a company like us?" | Not yet: you would be among the first. That is why the pilot is fixed-price, short, and measured against targets you set. | `docs/sales/PROOF.md` (public data only) |
| "Our data cannot leave the building." | It doesn't. Ingest runs with networking off; we delete at the end and give you a receipt. | `docs/DEPLOY.md`, `canon purge` |
| "Is it compliant with Law 09-08?" | We make no compliance claim. Processing stays on your infrastructure; your DPO decides. | `docs/product/SECURITY_REVIEW.md` |
| "What if it gets values wrong?" | It refuses what it cannot read safely and shows its sources for the rest; your team checks a sample. | `quarantine.csv`, citations in the report |
| "Arabic and scanned contracts?" | Supported, with measured limits: on public scans, 63% of dates read, 2% wrong, the rest withheld. | `docs/reports/receipts_report.md` |
| "Too expensive." | Compare with one missed renewal or one quarter of a wrong forecast; the pilot is scoped to fit a manager's budget. | Prospect's own numbers |
| "We're not doing AI yet." | The audit is useful without AI: fix list, duplicates, renewals. The agent part can wait. | `index.html` |
