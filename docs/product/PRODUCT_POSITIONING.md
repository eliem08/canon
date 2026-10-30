# Product positioning

*Part of the product document set. Target market: the US first, then the UK and EU (decision 94). Market statements are hypotheses unless a source is linked; no customer has been interviewed. Written by the agent that built most of the code. Updated 2026-10-31.*

## One sentence

Canon finds what is stale, duplicated or unreadable in your customer data across CRM, Slack and contracts, inside your
own environment, and lets AI agents answer only with facts each person is allowed to see, with sources.

## 30-second pitch

Your AI agents are only as good as your customer data, and they don't know who is asking. In two weeks, without your
data leaving your environment, we give you a ranked fix list in your CRM's own record ids (wrong contract values,
wrong owners, duplicate accounts), the contracts that auto-renew in the next six months with their notice deadlines,
and a test showing an agent answering from cleaned facts while respecting each person's access.

## Proof points we can demonstrate today

1. **Permissions.** On synthetic US data, 0 of 4,400 answers exposed a record the caller could not read, against
   43% for keyword retrieval and 87% for strong retrieval (`docs/reports/permission_report_west.md`).
2. **Real public documents.** On 267 held-out SEC-filed US contracts (CUAD): parties found 57% at 99% precision,
   renewal notice periods 37% with none wrong, end dates 33% at 91% (`docs/reports/cuad_report.md`). US business
   listings: duplicate detection F1 0.948 (`docs/reports/er_real_report.md`).
3. **Live demo** on a synthetic US company: dashboard, fix list, renewal calendar, review loop, week-2 comparison.

## Honest limitations

- Never run on a real customer's data yet.
- Answer accuracy is on par with a well-built retrieval system, not better; the advantage is permissions, sources
  and the fix list.
- Batch, not live sync; runs on the client's machine; no hosted service and no SOC 2 report.
- Permissions are as configured, not read live from each system.
- Most contract end dates that depend on events ("12 months after go-live") are not computed.
