# Buyer personas

*Part of the product document set. Target market: the US first, then the UK and EU (decision 94). Market statements are hypotheses unless a source is linked; no customer has been interviewed. Written by the agent that built most of the code. Updated 2026-10-31.*

| Role | Typical title (US) | Cares about | What convinces them |
|---|---|---|---|
| Economic buyer | VP Revenue Operations, CRO, VP Sales | Forecast accuracy, renewal revenue, safe AI rollout | Renewal calendar with notice deadlines; a fix list their team can load this week |
| Technical evaluator | RevOps engineer, Salesforce/HubSpot admin, data or AI platform lead | Fits our exports; runs in our VPC; no write access | `canon check` on a sample export; Docker run with networking off |
| Daily user | Sales ops analyst, CRM admin, account managers | Fewer duplicates, correct owners | `crm_fixes.csv` in CRM ids; review page; week-2 comparison |
| Gatekeeper | Security / IT, privacy counsel or DPO (EU) | Where data goes; retention; access control | On-prem run, hashed tokens, audit log, `canon purge` receipt; honest list of what is not certified |
| Likely blocker | Incumbent CRM partner; internal data team | "Our CRM vendor's AI does this"; "we'll build RAG" | Cross-source evidence (contracts + Slack); measured permission leaks of a RAG baseline |

## Personas in practice

- **VP RevOps (economic buyer).** Owns the CRM as a revenue system and is asked to "make it AI-ready". Measured on
  forecast accuracy and renewal rate. Buys a fixed-scope audit before a platform.
- **Salesforce admin / RevOps engineer (evaluator, user).** Has tried dedupe tools; the gap is reconciling CRM values
  with contracts and Slack. Wants CSVs in the CRM's own ids and nothing written to the CRM without review.
- **Security lead (gatekeeper).** First question: "Does our data leave our environment?" Second: "Who can the agent
  answer for?" Will send a questionnaire; Canon has no SOC 2 report, so the on-prem, no-network design must carry it.
