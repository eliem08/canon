# Canon eval: agent accuracy on raw data vs. on Canon

- Questions: 40 from `ground_truth/eval_questions.json` (contract_value 10, renewal_date 10, owner 10, phone 5, address 5)
- Model: `deepseek-ai/DeepSeek-V4-Pro-0813` (same model and prompt for every agent)
- Canon caller: `salma.el.idrissi`; facts as of 2026-10-01
- Baseline: BM25 keyword retrieval over raw CRM rows, Slack messages and contract texts (top 5 chunks)
- Strong RAG: BM25 + fuzzy character-trigram retrieval, queried with the question and every candidate customer span, reciprocal-rank fusion, top 10 chunks; Slack mentions resolved to names and messages dated
- Oracle: every raw chunk of the right customer and nothing else (perfect retrieval, from the answer key). It shows what raw data supports at best.
- Canon: MCP tools (`get_customer` for linking any span of the question, then `find_contract_terms` / `who_owns` / `get_customer`)

## Overall

| Agent | Correct | Accuracy | 95% CI (Wilson) | Context read (chars, mean) | Answers that read restricted text |
|---|---|---|---|---|---|
| Baseline (BM25 over raw files) | 23/40 | 57.5% | 42%–71% | 1,980 | 27/40 |
| Strong RAG (hybrid fuzzy retrieval, multi-query, top 10) | 37/40 | 92.5% | 80%–97% | 3,704 | 35/40 |
| Oracle retrieval (every raw record of the right customer) | 38/40 | 95.0% | 83%–99% | 2,701 | 40/40 |
| **Canon (MCP tools)** | 33/40 | 82.5% | 68%–91% | 3,537 | 0/40 |

Lift, Canon vs. baseline: **+25.0 pts**. On the same questions, Canon alone is right on 12 and the baseline alone on 2 (exact McNemar p = 0.013).
Canon vs. hybrid: **-10.0 pts**; Canon alone right on 1, hybrid alone on 5 (exact McNemar p = 0.22). This is the comparison to quote: the strongest baseline that does not need Canon or the answer key.
Canon vs. oracle: **-12.5 pts**; Canon alone right on 1, oracle alone on 6 (exact McNemar p = 0.12). The oracle needs the answer key; it bounds what any retrieval over raw files could do.

## Accuracy by question type

| Type | Questions | baseline | hybrid | oracle | canon |
|---|---|---|---|---|---|
| contract_value | 10 | 60% | 100% | 100% | 80% |
| renewal_date | 10 | 80% | 100% | 100% | 80% |
| owner | 10 | 40% | 100% | 90% | 100% |
| phone | 5 | 40% | 40% | 80% | 60% |
| address | 5 | 60% | 100% | 100% | 80% |

## Failure analysis

| Failure | baseline | hybrid | oracle | canon |
|---|---|---|---|---|
| stale / superseded value of the right customer | 3 | 1 | 2 | 4 |
| value belonging to a different customer | 0 | 0 | 0 | 0 |
| no answer found | 14 | 2 | 0 | 3 |
| other | 0 | 0 | 0 | 0 |

Accuracy by how the customer was named:

| Mention style | Questions | baseline | hybrid | oracle | canon |
|---|---|---|---|---|---|
| alias | 7 | 14% | 71% | 86% | 86% |
| arabic | 4 | 50% | 100% | 100% | 50% |
| canonical | 9 | 89% | 89% | 89% | 67% |
| darija | 3 | 67% | 100% | 100% | 100% |
| legal | 7 | 86% | 100% | 100% | 100% |
| lower | 8 | 38% | 100% | 100% | 88% |
| typo | 2 | 50% | 100% | 100% | 100% |

### Every miss

| Q | Question | Expected | baseline | hybrid | oracle | canon |
|---|---|---|---|---|---|---|
| Q03 | Ch7al kaykhalsou f l3am daba, نسيج شفشاون? | `872000` | ✗ `800 000 MAD` (stale_value) | ✓ | ✓ | ✗ `800000.0 DH` (stale_value) |
| Q04 | Quel est le montant annuel actuel du contrat de Rif Cement ? | `1666000` | ✗ `unknown` (no_answer) | ✓ | ✓ | ✓ |
| Q08 | Ch7al kaykhalsou f l3am daba, atlantic fishing company? | `1858000` | ✗ `unknown` (no_answer) | ✓ | ✓ | ✓ |
| Q10 | Ch7al kaykhalsou f l3am daba, سوس فريش? | `536000` | ✗ `410 000 MAD HT` (stale_value) | ✓ | ✓ | ✗ `unknown` (no_answer) |
| Q11 | When is the contract renewal date for Atlas Logisitque? | `2027-12-01` | ✗ `unknown` (no_answer) | ✓ | ✓ | ✓ |
| Q12 | Quelle est la date de renouvellement du contrat de Boulangerie Al Baraka ? | `2028-03-01` | ✓ | ✓ | ✓ | ✗ `2025-12-01` (stale_value) |
| Q13 | Quelle est la date de renouvellement du contrat de Nour Packaging ? | `2027-07-01` | ✓ | ✓ | ✓ | ✗ `2026-01-01` (stale_value) |
| Q17 | When is the contract renewal date for Argan d'Or S.A.? | `2027-09-01` | ✗ `unknown` (no_answer) | ✓ | ✓ | ✓ |
| Q21 | Chkoun l'owner dyal sahara tours? | `Omar Fassi` | ✗ `unknown` (no_answer) | ✓ | ✓ | ✓ |
| Q23 | Who is the account owner for chrikat Dar El Hana Immobilier? | `Salma El Idrissi` | ✗ `unknown` (no_answer) | ✓ | ✓ | ✓ |
| Q24 | Chkoun l'owner dyal Rif Cement? | `Youssef Benali` | ✗ `unknown` (no_answer) | ✓ | ✗ `Imane Chraibi` (stale_value) | ✓ |
| Q27 | Qui est le responsable du compte argan d'or ? | `Nadia Berrada` | ✗ `unknown` (no_answer) | ✓ | ✓ | ✓ |
| Q29 | Qui est le responsable du compte atlantic fishing company ? | `Mehdi Alaoui` | ✗ `unknown` (no_answer) | ✓ | ✓ | ✓ |
| Q30 | Chkoun l'owner dyal Al Massira? | `Salma El Idrissi` | ✗ `unknown` (no_answer) | ✓ | ✓ | ✓ |
| Q31 | What is the main phone number of Sahara Tech? | `+212592846751` | ✗ `unknown` (no_answer) | ✗ `unknown` (no_answer) | ✓ | ✓ |
| Q34 | Quel est le numéro de téléphone de Zitoun Cosmetics ? | `+212579101995` | ✗ `06 70 91 46 07` (stale_value) | ✗ `06 70 91 46 07` (stale_value) | ✗ `06 70 91 46 07` (stale_value) | ✗ `+212670914607` (stale_value) |
| Q35 | Quel est le numéro de téléphone de AFC ? | `+212524415035` | ✗ `unknown` (no_answer) | ✗ `unknown` (no_answer) | ✓ | ✗ `unknown` (no_answer) |
| Q37 | Quelle est l'adresse du siège social de dar el hana immobilier ? | `21 Avenue Hassan II` | ✗ `unknown` (no_answer) | ✓ | ✓ | ✗ `unknown` (no_answer) |
| Q40 | What is the registered office address of Yasmine? | `Avenue Mohammed VI, Malabata` | ✗ `unknown` (no_answer) | ✓ | ✓ | ✓ |

## Reading this report

- With the stub model, the answer is whatever the context literally contains first. This measures what each agent's *context* supports, not model reasoning. Run with a real model (`canon eval --model claude`) for the end-to-end number; the stub is a deterministic CI check. The stub's *oracle* number is not meaningful: given every record of a customer, it answers with the first value it finds, which is often the stale one. A real model weighs dates and sources.
- Confidence intervals are per agent; the McNemar test is the right comparison because both agents answer the same questions.
- The synthetic data and the questions were written by the same team that built Canon. Treat the lift as an upper bound until reproduced on a customer's data with the customer's questions.
