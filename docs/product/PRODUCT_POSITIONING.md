# Product positioning

*Part of the product document set (`docs/product/`). Code claims cite repository paths; market statements are hypotheses unless a source is linked. Written by the agent that built most of the code: treat as a self-assessment, not independent review. Updated 2026-10-30.*

- **One sentence.** "Canon finds what's stale, duplicated or unreadable in your customer data across CRM, chat and contracts, inside your network, and lets AI assistants answer only with facts each person is allowed to see."
- **30-second pitch.**
  - Your AI assistant is only as good as your customer data.
  - In two weeks, without your data leaving your servers, we give you a ranked fix list: wrong contract values, wrong account owners, duplicates, and contracts about to auto-renew with their notice deadlines.
  - Then we show an AI agent answering from the cleaned facts with sources, while respecting who may see what.
- **Three demonstrable proof points:**
  1. **Permissions.** 0 of 4,400 answers read restricted data, versus 70–87% for retrieval baselines. On synthetic data with configured roles.
  2. **Real public documents.**
     - On 267 SEC contracts it read: parties 57% found / 99% precision, renewal notice periods 37% / 100%, end dates 33% / 91%.
     - French company registry: 93% precision on automatic links.
  3. **Live demo:** fix list, renewal calendar, review loop, and the week-2 comparison.
- **Honest limitations:**
  - not yet run on a real client's data;
  - answer accuracy is on par with a good retrieval system, not better;
  - for a restricted sales rep, Canon answered 82–85% correctly against 92.5% for RAG. RAG leaked restricted data in 35 of 40 answers;
  - most contract end dates are not found;
  - batch only;
  - permissions are as configured, not read live from each system.
