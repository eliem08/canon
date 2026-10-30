# Buyer personas

*Part of the product document set (`docs/product/`). Code claims cite repository paths; market statements are hypotheses unless a source is linked. Written by the agent that built most of the code: treat as a self-assessment, not independent review. Updated 2026-10-30.*

| Role | Likely title | Cares about |
|---|---|---|
| Economic buyer | CEO or COO (mid-market), or the commercial director / head of sales | Renewal revenue, a reliable pipeline |
| Technical evaluator | IT or data lead, CRM admin | Will it run offline? Does it fit our exports? |
| Daily user | Sales operations, account managers, the legal assistant | Fix lists, renewal calendar, review cards |
| Gatekeeper | Legal / DPO, IT security | CNDP (Law 09-08), data never leaving the network |
| Likely blocker | Salesforce/HubSpot partner or internal CRM team | "Our CRM vendor's AI will do this" |

## Personas in practice

- **Commercial director (economic buyer).** Owns renewal revenue and the sales team. Measures: renewals lost, pipeline accuracy. Says yes to a renewal calendar with notice deadlines and a fix list the team can act on this week.
- **IT / data lead (technical evaluator).** Owns the CRM and exports. Asks: does it run offline, what does it need from us, what is left behind. Answer: `docs/DEPLOY.md`, `canon check`, `canon purge`.
- **Sales ops / CRM admin (daily user).** Loads `crm_fixes.csv`, sends `review.html` to account owners, reruns with `--compare`.
- **DPO / legal (gatekeeper).** Asks where data goes (nowhere unless a hosted model is chosen for `eval`) and retention (deleted at the end, with a receipt from `canon purge`).
- **CRM integrator (possible blocker or channel).** Fears replacement. Pitch: Canon creates work for them (fixes, merges) and an AI-readiness offer they can resell.
