# Market research

*Part of the product document set. Target market: the US first, then the UK and EU (decision 94). Market statements are hypotheses unless a source is linked; no customer has been interviewed. Written by the agent that built most of the code. Updated 2026-10-31.*

No customer interviews have been done. This page separates **evidence** (linked) from **assumptions** (to test in discovery).

## The problem in the market

- **Agents inherit CRM data problems.** Practitioner and vendor sources say agents built on inconsistent or outdated
  CRM data become less accurate, and recommend cleaning data before deploying agents ([Tofu: getting CRM data agent-ready (vendor blog)](https://www.tofuhq.com/post/how-to-get-crm-data-agent-ready)). A Diginomica
  article reports that 62% of organisations have suffered direct revenue loss from poor CRM data quality; the
  underlying survey is not named, so treat it as unverified ([Diginomica: poor CRM data and AI initiatives](https://diginomica.com/how-poor-crm-data-continues-plague-marketings-ai-initiatives-board-may-not-see-it)).
- **MCP deployments rarely scope access per user.** One industry write-up cites 18% of MCP server deployments
  implementing access scoping ([Celigo: MCP governance](https://www.celigo.com/blog/mcp-governance/)); another notes agents act with the permissions granted to the server,
  not the person asking ([MintMCP: assessing MCP data risk](https://docs.mintmcp.com/blog/assess-mcp-data-risk)). Enterprises are being advised to keep an inventory of the MCP servers their
  agents can reach ([CData: 2026 enterprise MCP adoption roadmap](https://www.cdata.com/blog/2026-enterprise-mcp-adoption-roadmap)).
- **EU regulation asks deployers for input-data relevance, human oversight and logs.** Article 26 of the EU AI Act
  obliges deployers of high-risk systems to ensure input data under their control is relevant and to keep logs
  ([EU AI Act Article 26 (deployer obligations)](https://artificialintelligenceact.eu/article/26/), [DLA Piper: deployer obligations from 2 August 2026](https://knowledge.dlapiper.com/dlapiperknowledge/globalemploymentlatestdevelopments/2026/deployer-obligations-under-the-ai-act-implications-for-employers-from-2-august-2026)). The dates are contested: a May 2026 "Digital Omnibus" agreement may move
  high-risk obligations to December 2027 or August 2028 ([Process Excellence Network: what changed in the EU AI Act in 2026](https://www.processexcellencenetwork.com/ai/articles/eu-ai-act-2026-what-actually-changed-and-what-deployers-still-must-do)). Most B2B sales agents are not
  high-risk systems; this is a tailwind for governance budgets, not a compliance requirement Canon satisfies.

## Ideal customer profile (hypothesis)

- **Geography.** United States first (largest pool of RevOps teams building agents); then UK and EU, where keeping data
  on the company's own infrastructure (GDPR) is a stronger argument.
- **Company.** B2B with recurring revenue (SaaS, IT services, subscriptions, distribution with contracts),
  about 200 to 2,000 employees, a RevOps or sales-operations team of 2 to 15 people.
- **Systems.** Salesforce or HubSpot; Slack or Microsoft Teams; contracts as PDFs (e-signature exports, Drive/SharePoint
  folders).
- **Trigger events.** An internal AI agent or Copilot/Agentforce rollout touching customer data; a CRM migration or
  clean-up project; a missed auto-renewal or a forecast miss traced to bad CRM data; a security review of an AI pilot.

## Today's workflow and alternatives

- **Today.** RevOps cleans the CRM in spreadsheets and with CRM dedupe tools; renewal dates are tracked by hand from
  contracts; account ownership changes in Slack before the CRM; AI pilots connect straight to raw sources.
- **Alternatives.** See `COMPETITOR_ANALYSIS.md`: CRM-native data tools, enterprise search (Glean, Copilot), MCP
  gateways, data-quality/MDM platforms, RevOps consultancies.

## Prospect types, ranked (hypotheses, no named companies)

| # | Prospect type | Why it fits | Approach | Friction | Confidence |
|---|---|---|---|---|---|
| 1 | US B2B SaaS, 200–1,000 staff, RevOps team, building an internal agent on CRM + Slack | Renewal-driven revenue; agent permission risk is concrete | VP RevOps / Head of Sales Ops | Security questionnaire; no SOC 2 | Medium |
| 2 | Salesforce / HubSpot consulting partners (channel) | Need an "AI-readiness" offer; own the CRM relationship | Partner principal | Partner terms | Medium |
| 3 | RevOps agencies and fractional RevOps leaders | Deliver clean-ups by hand; Canon makes it repeatable | Founder / principal | Small budgets | Medium |
| 4 | UK / EU B2B companies with data-residency concerns | On-premise processing is decisive | Head of RevOps + DPO | GDPR review, DPA | Low–medium |
| 5 | IT services / MSPs with large contract portfolios | Contract renewal tracking | COO / Finance | Contract formats vary | Low–medium |
| 6 | Companies piloting MCP agents (job posts for "AI agent engineer" + RevOps) | Direct permission pain | Head of AI / platform | Build-vs-buy | Low |

**Beachhead for one founder:** US B2B SaaS companies of 200–1,000 employees on Salesforce or HubSpot with Slack,
reached through two or three CRM consulting partners and warm RevOps contacts. Target: 20 conversations, 2 paid audits.

**Not a buyer:** enterprises that require a SOC 2 Type II hosted SaaS before any trial (Canon has none); companies
with no CRM; startups under ~50 people (too little data to have the problem); teams wanting a CRM replacement.

## Regulatory notes (not legal advice; no compliance claims)

- **GDPR (EU/UK).** Canon processes customer and employee personal data (names, emails, phone numbers). Running
  inside the client's network avoids an international transfer by Canon; the client remains controller. A DPA is
  still expected for the engagement.
- **US.** State privacy laws (e.g. CCPA/CPRA) mostly concern consumer data; B2B contact data has partial exemptions
  that vary by state. Procurement will mostly ask security questions (SOC 2, pen test, data handling).
