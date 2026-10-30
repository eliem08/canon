# Objection handling

*Sales material for US, UK and EU buyers. Prices are hypotheses to validate in discovery; no customer, partnership or certification exists yet. Never present synthetic-data numbers as client results. Updated 2026-10-31.*

Answer with evidence that exists; when it does not, say so.

| Objection | Honest answer | Evidence to show |
|---|---|---|
| "Salesforce/HubSpot AI already does this." | Inside the CRM, yes. Canon reconciles the CRM with signed contracts and Slack/Teams, per fact, with sources, and runs in your environment. If all your truth is in the CRM, you may not need us. | Demo: CRM value vs contract value, with citation |
| "We use Glean / Copilot." | They retrieve documents with permissions. Canon returns one reconciled value per fact with confidence and conflicts, and gives RevOps a fix list. They can sit side by side. | `index.html`, `crm_fixes.csv` |
| "We'll build RAG ourselves." | You can; it will be about as accurate. On our synthetic US test, strong retrieval exposed restricted records in 87% of answers; Canon in none. | `docs/reports/permission_report_west.md`, `eval_summary.md` |
| "Do you have SOC 2?" | No. That's why it runs inside your environment with networking off, writes nothing to your systems, and deletes everything at the end with a receipt. We'll answer your questionnaire honestly. | `docs/product/SECURITY_REVIEW.md` |
| "Has it worked for a company like us?" | Not yet: you'd be among the first. The pilot is fixed-price, short, and measured against targets you set. | `docs/sales/PROOF.md` (public data) |
| "GDPR / data residency?" | Processing happens on your infrastructure; you remain controller; we sign a DPA. We make no compliance claim. | `docs/DEPLOY.md` |
| "What if it gets values wrong?" | It refuses what it cannot read safely and shows sources for the rest; your team checks a sample before loading fixes. | `quarantine.csv`, citations |
| "Too expensive." | Compare with one missed renewal or one quarter of wrong forecasts; the design-partner price is below a typical enterprise-search minimum. | Prospect's own numbers |
| "We're not doing AI agents yet." | The audit stands on its own: fix list, duplicates, renewals. The agent part can wait. | `index.html` |
