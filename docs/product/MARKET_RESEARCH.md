# Market research

*Part of the product document set (`docs/product/`). Code claims cite repository paths; market statements are hypotheses unless a source is linked. Written by the agent that built most of the code: treat as a self-assessment, not independent review. Updated 2026-10-30.*

No customer interviews have been done. Everything here is desk research plus hypotheses to test in discovery.

## Ideal customer profile

- **Geography and language.** Morocco first, then the francophone Maghreb. Operating language is French with Arabic names and documents. The synthetic data, the French/Arabic OCR and the WhatsApp connector all point here, and few global tools handle this mix well.
- **Company.** B2B, about 100 to 1,000 employees, with 20 to 200 people in sales or account management. Examples: distribution, logistics, B2B services, IT services and integrators, insurance brokerage, leasing.
- **Systems.** A CRM (Salesforce, HubSpot or Dynamics), contracts in PDF or scanned, and sales conversations in WhatsApp or Teams.
- **Technical maturity.** An IT or data lead exists, and the company is piloting an AI assistant (Copilot, an internal chatbot, an MCP agent).
- **Triggering events:**
  - an AI-assistant rollout;
  - a CRM migration or clean-up;
  - a renewal-revenue leak, such as contracts renewing or lapsing unnoticed;
  - a CNDP compliance push, which favours on-premise processing.

## Today's workflow and alternatives

- **Today.** CRM hygiene is done by hand in spreadsheets. Renewal dates live in contracts that nobody re-reads. Account ownership changes in WhatsApp and never reaches the CRM. AI pilots connect straight to raw data.
- **Alternatives:**
  - CRM-native tools: HubSpot or Salesforce duplicate management, Salesforce Data Cloud / Agentforce;
  - enterprise search with permissions: Glean, Microsoft Copilot over SharePoint;
  - MCP gateways and governance tools: MintMCP, CData;
  - data-quality and master-data tools: Informatica, Talend;
  - local integrators doing manual clean-ups.
- **Why a buyer would switch:**
  1. It runs fully on-premise and offline, which helps with Moroccan cross-border transfer rules (see the risk note in §3.4).
  2. It reads French and Arabic contracts and WhatsApp alongside the CRM.
  3. It produces a concrete fix list and renewal calendar in two weeks.
  4. It enforces permissions per caller, whereas many MCP deployments don't scope access at all. One industry source cites 18% scoping ([Celigo](https://www.celigo.com/blog/mcp-governance/)), and another notes that agents act with the server's permissions, not the user's ([MintMCP](https://docs.mintmcp.com/blog/assess-mcp-data-risk)).
- **The measurable outcome they would pay for:**
  - number of stale and duplicate CRM records fixed;
  - renewal revenue at risk found, from contracts renewing in the next 180 days with notice deadlines;
  - a demonstrated zero-leak permission test on their own roles.

## Prospect types

| # | Prospect type | Why it fits | Approach | Use case | Friction | Confidence |
|---|---|---|---|---|---|---|
| 1 | Moroccan B2B distributors or wholesalers with field sales on WhatsApp | Many accounts, owner churn, contract renewals | Commercial director | Audit plus renewal calendar | Low to medium | Medium |
| 2 | Salesforce, HubSpot or Dynamics integrators in Casablanca/Rabat (as a **channel**) | They own the CRM relationship and need AI-readiness offers | Partner manager or CEO | Resell the audit to their clients | Partner terms | Medium |
| 3 | IT services companies and system integrators | They run their own CRM and contracts, and are tech-mature design partners | CEO or COO | Audit plus an MCP trial on their own data | Low | Medium |
| 4 | Insurance brokers | Policies and contracts with renewals and notice periods | Head of operations | Renewal and notice extraction | CNDP sensitivity | Low to medium |
| 5 | Logistics and transport B2B | Multi-site customers, duplicates | Sales operations | Duplicate merge, owner map | Low | Low to medium |
| 6 | Leasing or equipment-rental firms | Contract-heavy, renewal revenue | Finance director | Renewal calendar | Medium | Low |
| 7 | Telecom or cloud providers launching enterprise GenAI ([Orange Maroc / Orange Business "Live Intelligence"](https://fr.hespress.com/468751-468751.html) is one example of the push) | Partner channel for "data-readiness before GenAI" | Partnerships | Bundled offer | Long cycles | Low |
| 8 | Customer-experience outsourcers (Concentrix's AI customer-experience observatory shows AI focus in Morocco; [Hespress](https://fr.hespress.com/468751-concentrix-lance-le-premier-observatoire-de-lexperience-client-a-lere-de-lia-au-maroc-en-partenariat.html)) | Large CRM data volumes | IT innovation | Permission-safe agents | Enterprise procurement | Low |

**Beachhead, narrow enough for one founder:** Moroccan B2B companies with 100 to 500 employees that use HubSpot or Salesforce, with French contracts and WhatsApp-heavy sales, reached through **two CRM integrators** as warm channels. The target is 15 conversations and 2 paid audits.

**Not a buyer:**
- large banks and telecoms (slow procurement; they build in-house);
- B2C companies (wrong data shape);
- companies with no CRM;
- US or EU enterprises (Glean and the CRM vendors already serve them, and Canon has no US proof beyond a public benchmark);
- anyone who wants a hosted SaaS tomorrow (Canon is on-premise and batch).

## Regulatory context

- **Cross-border transfers.** Moroccan Law 09-08 (Articles 43–44) restricts transfers abroad. Practitioners treat cloud hosting abroad as a transfer that may need CNDP authorization, and the CNDP has begun warning large controllers ([Upsilon](https://upsilon-consulting.com/en/international-personal-data-transfer-morocco/), [Chambers 2026](https://practiceguides.chambers.com/practice-guides/data-protection-privacy-2026/morocco)). These are secondary sources; verify with a lawyer.
- **What this means for Canon.** Offline, on-premise processing is a selling point. The `eval` step with a hosted model would be a transfer, so use a local model or get written consent.
- **No compliance claims.** Do not claim to be "CNDP-compliant". Claim "processes inside your network; no data leaves unless you choose a hosted model".

## Sources

- [Upsilon Consulting: international data transfer in Morocco](https://upsilon-consulting.com/en/international-personal-data-transfer-morocco/)
- [Chambers Data Protection & Privacy 2026: Morocco](https://practiceguides.chambers.com/practice-guides/data-protection-privacy-2026/morocco)
- [DPO Consulting: Morocco Law 09-08 guide](https://www.dpo-consulting.com/blog/morocco-data-protection-law-09-08)
- [Celigo: MCP governance](https://www.celigo.com/blog/mcp-governance/)
- [MintMCP: assessing MCP data risk](https://docs.mintmcp.com/blog/assess-mcp-data-risk)
- [CData: 2026 enterprise MCP adoption roadmap](https://www.cdata.com/blog/2026-enterprise-mcp-adoption-roadmap)
- [Hespress: Concentrix AI customer-experience observatory, Morocco](https://fr.hespress.com/468751-concentrix-lance-le-premier-observatoire-de-lexperience-client-a-lere-de-lia-au-maroc-en-partenariat.html)
- [KPMG France: Trends of AI 2026](https://kpmg.com/fr/fr/media/press-releases/2026/01/adoption-ia-entreprises-francaises.html)
