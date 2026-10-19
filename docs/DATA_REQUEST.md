# Data request for a design partner (draft v0.1)

*What to ask a design partner to export for an MCP Readiness Audit ([scope](AUDIT_SCOPE.md)). Have counsel review the data-handling
section before sending; this is a checklist, not legal language.*

## 1. Exports

| # | What | Format | Minimum | Must include |
|---|---|---|---|---|
| 1 | **CRM accounts** (and contacts if separate) | CSV/XLSX/JSON as exported | All active accounts, or ≥ 200 | account name, website, phone, address/city, tax id (ICE) if stored, **owner**, **annual contract value + currency**, **renewal date**, **last modified date**, record id |
| 2 | **Team chat:** Slack workspace export, Microsoft Teams channels, or WhatsApp groups (tell us which is real) | native export (Slack: zip with `channels.json`, `users.json`, per-day files; Teams: Graph `chatMessage` JSON per channel plus channel membership; WhatsApp: "Export chat" without media, one `.txt` per group) | channels that discuss customers, last 24 months | channel membership/privacy flags (needed for permissions), user list |
| 3 | **Contracts** | PDF/DOCX as stored, scans included | 50–200 files, including **≥ 5 amendments/superseding versions** | the files as stored; any folder structure (it often encodes the customer and who may read it) |
| 4 | **Who can see what** | spreadsheet | every role that will use the agent | role → which sources/folders/channels it may read; 3–5 example people per role |
| 5 | **Questions** | spreadsheet (CSV/XLSX: `id, type, question, expected`; dates as YYYY-MM-DD) | **30–50** | real questions the team asks (or wants an agent to answer), each with the answer they agree is correct today and where they'd check it |

Why #5 matters most: the before/after number is only credible if the client wrote the questions and the answers. We won't
generate them.

## 2. Things to confirm before sending
- [ ] Which CRM, chat tool and document store are actually used day to day?
- [ ] Date format and currency conventions in the exports (e.g. `25/03/2026`, MAD vs EUR). Mixed conventions are fine; we detect them.
- [ ] Languages present (French / Arabic / Darija / English), and whether any contracts are scanned.
- [ ] A technical contact for 2–3 hours over the two weeks.

## 3. Data handling we commit to (proposed, for counsel review)
- **Processing location:** option A (their environment) or B (ours, under a DPA). **[FOUNDER DECISION, per client]**
- **No third-party AI services** on their data without explicit written approval naming the provider.
- **Minimization:** they may pseudonymize personal data (contact names, personal phones/emails) before export. Customer company names must stay.
- **Retention:** data deleted within N days of the final report, with written confirmation. **[FOUNDER DECISION: N]**
- **Publication:** no client data, names or figures are published. Any public result uses synthetic or public data only, unless separately agreed in writing.
- **Access:** limited to named people; access log kept for the audit period.

## 4. Message template (to adapt)

> We're running a small number of paid MCP readiness audits: we take an export of your CRM, team chat and contracts and
> measure how accurately an AI agent can answer questions about your customers today versus with a resolved, permission-aware
> data layer. You get a report with the duplicates, stale and conflicting facts and permission gaps we find, and a before/after
> accuracy number on questions your own team writes. It takes about two weeks and 3–4 hours of your team's time. The data stays
> [in your environment / under a DPA and is deleted afterwards]. Would you be open to a 30-minute call to see if it fits?

## 5. Readiness check for us (before the data arrives)
- [ ] Run `canon check` on the export the day it arrives. Column names, CRM file name, ACLs and currency go in `canon.json` (a config change, not code); `canon check` suggests the CRM mapping for us to confirm. The CRM connector reads JSON, CSV (`,`/`;`) or XLSX (first sheet). Ask for tax ids and phones as text: when Excel has stored them as numbers they are refused, because leading zeros may be gone.
- [ ] Permissions: Slack private-channel membership is read from the export (`groups.json`); contract folders get ACLs from `_acl.json` sidecars written from the role spreadsheet (#4); everything else is per source type. Say which in the report.
- [ ] Contracts: PDFs (text or scanned), DOCX and images are read; scans go through OCR (`docs/DOCUMENTS.md`). OCR is measured on synthetic renders and on real English receipts (SROIE), not yet on French or Arabic scans, so measure field accuracy on 10 of their scans on day 1. Unreadable files are listed in the quarantine report.
- [ ] `canon resolve` on their sample produces a quarantine report we can show them on day 3.
