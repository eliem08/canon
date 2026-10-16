# Canon eval: agent accuracy on raw data vs. on Canon

- Questions: 30 from `paraphrase_questions.json` (contract_value 8, renewal_date 7, owner 8, phone 4, address 3)
- Model: `stub` (same model and prompt for every agent)
- Canon caller: `revops.admin`; facts as of 2026-10-01
- Baseline: BM25 keyword retrieval over raw CRM rows, Slack messages and contract texts (top 5 chunks)
- Strong RAG: BM25 + fuzzy character-trigram retrieval, queried with the question and every candidate customer span, reciprocal-rank fusion, top 10 chunks; Slack mentions resolved to names and messages dated
- Oracle: every raw chunk of the right customer and nothing else (perfect retrieval, from the answer key). It shows what raw data supports at best.
- Canon: MCP tools (`get_customer` for linking any span of the question, then `find_contract_terms` / `who_owns` / `get_customer`)

## Overall

| Agent | Correct | Accuracy | 95% CI (Wilson) | Context read (chars, mean) | Answers that read restricted text |
|---|---|---|---|---|---|
| Baseline (BM25 over raw files) | 19/30 | 63.3% | 46%–78% | 2,150 | 0/30 |
| Strong RAG (hybrid fuzzy retrieval, multi-query, top 10) | 23/30 | 76.7% | 59%–88% | 3,695 | 0/30 |
| Oracle retrieval (every raw record of the right customer) | 14/30 | 46.7% | 30%–64% | 2,712 | 0/30 |
| **Canon (MCP tools)** | 29/30 | 96.7% | 83%–99% | 7,088 | 0/30 |

Lift, Canon vs. baseline: **+33.3 pts**. On the same questions, Canon alone is right on 10 and the baseline alone on 0 (exact McNemar p = 0.002).
Canon vs. hybrid: **+20.0 pts**; Canon alone right on 6, hybrid alone on 0 (exact McNemar p = 0.031). This is the comparison to quote: the strongest baseline that does not need Canon or the answer key.
Canon vs. oracle: **+50.0 pts**; Canon alone right on 15, oracle alone on 0 (exact McNemar p = 6.1e-05). The oracle needs the answer key; it bounds what any retrieval over raw files could do.

## Accuracy by question type

| Type | Questions | baseline | hybrid | oracle | canon |
|---|---|---|---|---|---|
| contract_value | 8 | 50% | 62% | 62% | 100% |
| renewal_date | 7 | 43% | 57% | 29% | 100% |
| owner | 8 | 62% | 88% | 25% | 88% |
| phone | 4 | 100% | 100% | 75% | 100% |
| address | 3 | 100% | 100% | 67% | 100% |

## Failure analysis

| Failure | baseline | hybrid | oracle | canon |
|---|---|---|---|---|
| stale / superseded value of the right customer | 7 | 7 | 16 | 1 |
| value belonging to a different customer | 1 | 0 | 0 | 0 |
| no answer found | 3 | 0 | 0 | 0 |
| other | 0 | 0 | 0 | 0 |

Accuracy by how the customer was named:

| Mention style | Questions | baseline | hybrid | oracle | canon |
|---|---|---|---|---|---|
| hand-written | 30 | 63% | 77% | 47% | 97% |

### Every miss

| Q | Question | Expected | baseline | hybrid | oracle | canon |
|---|---|---|---|---|---|---|
| P01 | Before I call Atlas Logistique tomorrow, who on our side owns that account? | `Nadia Berrada` | ✓ | ✓ | ✗ `Karim Tazi` (stale_value) | ✓ |
| P03 | La boulangerie Al Baraka renouvelle quand exactement ? | `2028-03-01` | ✗ `2025-12-01` (stale_value) | ✗ `2025-12-01` (stale_value) | ✗ `2025-12-01` (stale_value) | ✓ |
| P04 | Qui s'occupe de Marjana Distribution chez nous en ce moment ? | `Imane Chraibi` | ✓ | ✓ | ✗ `Salma El Idrissi` (stale_value) | ✓ |
| P07 | Dar El Hana Immobilier, c'est combien par an leur contrat ? | `190000` | ✗ `155000 MAD` (stale_value) | ✗ `155000 MAD` (stale_value) | ✓ | ✓ |
| P08 | Is the Oasis Agro Export contract up for renewal soon, and when? | `2027-06-01` | ✗ `2026-06-01` (wrong_customer) | ✓ | ✗ `2025-12-01` (stale_value) | ✓ |
| P09 | chkoun li kaytkellef b Chefchaouen Textiles daba? | `Nadia Berrada` | ✗ `Omar Fassi` (stale_value) | ✗ `Omar Fassi` (stale_value) | ✗ `Omar Fassi` (stale_value) | ✗ `Omar Fassi` (stale_value) |
| P10 | Can you check what Rif Ciment's annual contract is worth? | `1666000` | ✓ | ✓ | ✗ `1380000 MAD` (stale_value) | ✓ |
| P11 | For Tanger Med Freight, what's the renewal date on the contract? | `2028-06-01` | ✓ | ✓ | ✗ `2026-04-01` (stale_value) | ✓ |
| P16 | When does Bab Rayan Consulting's contract renew? | `2027-09-01` | ✓ | ✓ | ✗ `2025-04-01` (stale_value) | ✓ |
| P17 | Amal Microfinance wants a meeting; who is the account owner there? | `Mehdi Alaoui` | ✓ | ✓ | ✗ `Imane Chraibi` (stale_value) | ✓ |
| P18 | What did we sign with Atlantic Fishing Company for, per year? | `1858000` | ✗ `unknown` (no_answer) | ✓ | ✓ | ✓ |
| P21 | Who looks after Al Massira Transport these days? | `Salma El Idrissi` | ✗ `unknown` (no_answer) | ✓ | ✓ | ✓ |
| P22 | Fennec Software, how much is the contract worth annually? | `1031000` | ✗ `765000 MAD` (stale_value) | ✗ `765000 MAD` (stale_value) | ✗ `765000 MAD` (stale_value) | ✓ |
| P23 | What's the head office address for Yasmine Hôtels? | `Avenue Mohammed VI, Malabata` | ✓ | ✓ | ✗ `58 Rue Oued Sebou` (stale_value) | ✓ |
| P24 | Is Atlas Tours still handled by the same account owner? Who is it? | `Nadia Berrada` | ✗ `unknown` (no_answer) | ✓ | ✗ `Leila Bennani` (stale_value) | ✓ |
| P25 | Sahara Tours ch7al kaykhalsou f l3am? | `968000` | ✗ `920000 MAD` (stale_value) | ✗ `920000 MAD` (stale_value) | ✗ `920000 MAD` (stale_value) | ✓ |
| P26 | Quand est-ce que le contrat de Zitoun Cosmetics doit être renouvelé ? | `2027-05-01` | ✗ `2025-05-01` (stale_value) | ✗ `2025-05-01` (stale_value) | ✓ | ✓ |
| P27 | Quel est le numéro de Boulangerie Al Baraka ? | `+212546677565` | ✓ | ✓ | ✗ `+212629980318` (stale_value) | ✓ |
| P28 | Tanger Med Freight asked for a quote; who's their account owner? | `Nadia Berrada` | ✓ | ✓ | ✗ `Karim Tazi` (stale_value) | ✓ |
| P30 | My manager asked when Fennec Software renews - do you know? | `2027-09-01` | ✗ `2026-06-01` (stale_value) | ✗ `2026-06-01` (stale_value) | ✗ `2026-06-01` (stale_value) | ✓ |

## Reading this report

- With the stub model, the answer is whatever the context literally contains first. This measures what each agent's *context* supports, not model reasoning. Run with a real model (`canon eval --model claude`) for the end-to-end number; the stub is a deterministic CI check. The stub's *oracle* number is not meaningful: given every record of a customer, it answers with the first value it finds, which is often the stale one. A real model weighs dates and sources.
- Confidence intervals are per agent; the McNemar test is the right comparison because both agents answer the same questions.
- The synthetic data and the questions were written by the same team that built Canon. Treat the lift as an upper bound until reproduced on a customer's data with the customer's questions.
