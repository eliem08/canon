# Canon: know what your AI agent will get wrong about your customers, before it does

*Draft for the founder. Items in **[brackets]** are founder decisions. Every number below comes from synthetic data and is
labelled as such. Don't present it as a client result.*

## The problem
Teams are connecting AI agents to their CRM, chat and contracts. The agent then answers from whatever it retrieves:
- A **stale CRM value**, when the signed contract says otherwise.
- The **old account owner**, when the change was only announced in Slack.
- A **duplicate account** of the same customer, under a different spelling or in Arabic script.
- **Text the person asking is not allowed to see**: a sales rep receives a legal-only contract clause.

Nobody notices until a customer does.

## What we offer: a 2-week MCP Readiness Audit
You give us an export of your CRM, team chat and contracts. We run Canon **inside your network, with no internet access
during processing**, and you receive:

1. **A ranked fix list.** Stale CRM values, duplicate accounts, owner changes only chat knows about, unreadable values, and
   merges to confirm. Every item carries the record ids to check it, plus who should fix it.
2. **A permission map.** What each role can see, and where an agent would read what it shouldn't.
3. **A before/after test on your own questions.** The same AI model answers 30–50 questions your team writes, once on your raw
   data and once through Canon, scored against the answers your team agrees are correct.
4. *(Optional)* **A 2-week trial** of Canon as a permission-aware data layer for your agents (an MCP server).

**Your time:** a 1-hour kickoff, a technical contact for 2–3 hours, and a 1-hour readout. **Duration:** 10 working days.
**Price:** **[$5–7k core / $10–15k extended]**.

## What the evidence says so far (synthetic data, 25 customers, 4 open AI models)
- **The audit finds real problems.** On the synthetic export it listed 62 stale CRM values, all correct, and missed 2 of 64.
- **No permission leaks.** Over 4,400 answers for 110 callers on 10 datasets, a retrieval system over the raw export put
  text the caller may not see in front of the model in **87%** of answers (100% for someone with no access at all).
  Through Canon: **0%**.
- **Accuracy:** on par with a well-built retrieval system (97.5% vs 92.5%; the difference is not statistically
  significant), and far above basic keyword search (55–58%).
- **Every fact is cited** to a contract page and line, a Slack message or a CRM row, with a confidence and the values it
  was chosen over.
- **3× less text for the model to read** than the retrieval baseline, which means lower cost per question.
- **Reads what companies actually have:** CSV/XLSX/JSON CRM exports, Slack exports including private channels, PDF
  contracts including scans (French/Arabic/English OCR), and Word files.

- **Tested on real data too:** 510 public contracts, US and French company registries, 23k Arabic names, 361 scanned
  receipts. Full numbers and how to rerun them: [`PROOF.md`](PROOF.md).

*We'll measure all of this again on your data. We don't promise an accuracy number before we see it.*

## Data handling
- Processing in your environment (we ship a container), or on ours under a DPA **[founder decision per client]**.
- No third-party AI service touches your data without written consent. The before/after test can use a model you host.
- Data deleted within **[N]** days of the readout, confirmed in writing. Nothing is published.

## Next step
A 30-minute call to see whether your data and questions fit. If they do, the data request is one page.
