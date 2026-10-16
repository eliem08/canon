# Canon eval: agent accuracy on raw data vs. on Canon

- Questions: 40 from `ground_truth/eval_questions.json` (contract_value 10, renewal_date 10, owner 10, phone 5, address 5)
- Model: `stub` (same model and prompt for every agent)
- Canon caller: `salma.el.idrissi`; facts as of 2026-10-01
- Baseline: BM25 keyword retrieval over raw CRM rows, Slack messages and contract texts (top 5 chunks)
- Strong RAG: BM25 + fuzzy character-trigram retrieval, queried with the question and every candidate customer span, reciprocal-rank fusion, top 10 chunks; Slack mentions resolved to names and messages dated
- Oracle: every raw chunk of the right customer and nothing else (perfect retrieval, from the answer key). It shows what raw data supports at best.
- Canon: MCP tools (`get_customer` for linking any span of the question, then `find_contract_terms` / `who_owns` / `get_customer`)

## Overall

| Agent | Correct | Accuracy | 95% CI (Wilson) | Context read (chars, mean) | Answers that read restricted text |
|---|---|---|---|---|---|
| Baseline (BM25 over raw files) | 24/40 | 60.0% | 45%–74% | 1,980 | 27/40 |
| Strong RAG (hybrid fuzzy retrieval, multi-query, top 10) | 26/40 | 65.0% | 50%–78% | 3,704 | 35/40 |
| Oracle retrieval (every raw record of the right customer) | 20/40 | 50.0% | 35%–65% | 2,701 | 40/40 |
| **Canon (MCP tools)** | 34/40 | 85.0% | 71%–93% | 3,537 | 0/40 |

Lift, Canon vs. baseline: **+25.0 pts**. On the same questions, Canon alone is right on 13 and the baseline alone on 3 (exact McNemar p = 0.021).
Canon vs. hybrid: **+20.0 pts**; Canon alone right on 9, hybrid alone on 1 (exact McNemar p = 0.021). This is the comparison to quote: the strongest baseline that does not need Canon or the answer key.
Canon vs. oracle: **+35.0 pts**; Canon alone right on 16, oracle alone on 2 (exact McNemar p = 0.0013). The oracle needs the answer key; it bounds what any retrieval over raw files could do.

## Accuracy by question type

| Type | Questions | baseline | hybrid | oracle | canon |
|---|---|---|---|---|---|
| contract_value | 10 | 60% | 50% | 30% | 90% |
| renewal_date | 10 | 80% | 60% | 40% | 80% |
| owner | 10 | 40% | 80% | 50% | 100% |
| phone | 5 | 60% | 40% | 80% | 60% |
| address | 5 | 60% | 100% | 80% | 80% |

## Failure analysis

| Failure | baseline | hybrid | oracle | canon |
|---|---|---|---|---|
| stale / superseded value of the right customer | 2 | 10 | 18 | 4 |
| value belonging to a different customer | 4 | 1 | 0 | 0 |
| no answer found | 10 | 3 | 0 | 2 |
| other | 0 | 0 | 2 | 0 |

Accuracy by how the customer was named:

| Mention style | Questions | baseline | hybrid | oracle | canon |
|---|---|---|---|---|---|
| alias | 7 | 14% | 43% | 43% | 86% |
| arabic | 4 | 50% | 0% | 50% | 75% |
| canonical | 9 | 100% | 56% | 33% | 67% |
| darija | 3 | 67% | 67% | 67% | 100% |
| legal | 7 | 86% | 100% | 57% | 100% |
| lower | 8 | 38% | 88% | 62% | 88% |
| typo | 2 | 50% | 100% | 50% | 100% |

### Every miss

| Q | Question | Expected | baseline | hybrid | oracle | canon |
|---|---|---|---|---|---|---|
| Q01 | Quel est le montant annuel actuel du contrat de Atlas Logistique ? | `461000` | ✓ | ✗ `375000 MAD` (stale_value) | ✗ `375 MAD` (other) | ✓ |
| Q03 | Ch7al kaykhalsou f l3am daba, نسيج شفشاون? | `872000` | ✗ `800000 MAD` (stale_value) | ✗ `800000 MAD` (stale_value) | ✗ `800 MAD` (other) | ✗ `800000.0` (stale_value) |
| Q04 | Quel est le montant annuel actuel du contrat de Rif Cement ? | `1666000` | ✗ `unknown` (no_answer) | ✗ `1380000 MAD` (stale_value) | ✗ `1380000 MAD` (stale_value) | ✓ |
| Q05 | Quel est le montant annuel actuel du contrat de Tanger Med Freight SARL ? | `1341000` | ✓ | ✓ | ✗ `1215000 MAD` (stale_value) | ✓ |
| Q06 | Quel est le montant annuel actuel du contrat de مدينة فارما ? | `600000` | ✓ | ✗ `510000 MAD` (stale_value) | ✗ `510000 MAD` (stale_value) | ✓ |
| Q07 | Ch7al kaykhalsou f l3am daba, Bab Rayan Consulting SARL? | `487000` | ✓ | ✓ | ✗ `385000 MAD` (stale_value) | ✓ |
| Q08 | Ch7al kaykhalsou f l3am daba, atlantic fishing company? | `1858000` | ✗ `unknown` (no_answer) | ✓ | ✓ | ✓ |
| Q09 | Ch7al kaykhalsou f l3am daba, Riad Digital Agency? | `1382000` | ✓ | ✓ | ✗ `1300000 MAD` (stale_value) | ✓ |
| Q10 | Ch7al kaykhalsou f l3am daba, سوس فريش? | `536000` | ✗ `410000 MAD` (stale_value) | ✗ `410000 MAD` (stale_value) | ✓ | ✓ |
| Q11 | When is the contract renewal date for Atlas Logisitque? | `2027-12-01` | ✗ `2026-06-01` (wrong_customer) | ✓ | ✗ `2026-02-01` (stale_value) | ✓ |
| Q12 | Quelle est la date de renouvellement du contrat de Boulangerie Al Baraka ? | `2028-03-01` | ✓ | ✗ `2025-12-01` (stale_value) | ✗ `2025-12-01` (stale_value) | ✗ `2025-12-01` (stale_value) |
| Q13 | Quelle est la date de renouvellement du contrat de Nour Packaging ? | `2027-07-01` | ✓ | ✗ `2026-01-01` (stale_value) | ✗ `2026-01-01` (stale_value) | ✗ `2026-01-01` (stale_value) |
| Q14 | Quelle est la date de renouvellement du contrat de oasis agro export ? | `2027-06-01` | ✓ | ✓ | ✗ `2025-12-01` (stale_value) | ✓ |
| Q15 | Imta ghadi ytjedded contrat dyal chrikat Medina Pharma? | `2027-08-01` | ✓ | ✗ `2025-06-01` (stale_value) | ✗ `2025-06-01` (stale_value) | ✓ |
| Q17 | When is the contract renewal date for Argan d'Or S.A.? | `2027-09-01` | ✗ `2026-06-01` (wrong_customer) | ✓ | ✓ | ✓ |
| Q19 | Quelle est la date de renouvellement du contrat de سوس فريش ? | `2027-08-01` | ✓ | ✗ `2025-08-01` (stale_value) | ✓ | ✓ |
| Q20 | When is the contract renewal date for Yasmine Hotels? | `2027-05-01` | ✓ | ✓ | ✗ `2025-08-01` (stale_value) | ✓ |
| Q21 | Chkoun l'owner dyal sahara tours? | `Omar Fassi` | ✗ `unknown` (no_answer) | ✓ | ✗ `Salma El Idrissi` (stale_value) | ✓ |
| Q22 | Chkoun l'owner dyal marjana distribution? | `Imane Chraibi` | ✓ | ✓ | ✗ `Salma El Idrissi` (stale_value) | ✓ |
| Q23 | Who is the account owner for chrikat Dar El Hana Immobilier? | `Salma El Idrissi` | ✗ `unknown` (no_answer) | ✓ | ✓ | ✓ |
| Q24 | Chkoun l'owner dyal Rif Cement? | `Youssef Benali` | ✗ `unknown` (no_answer) | ✗ `unknown` (no_answer) | ✗ `Imane Chraibi` (stale_value) | ✓ |
| Q25 | Chkoun l'owner dyal Tanger Med Freight S.A.? | `Nadia Berrada` | ✓ | ✓ | ✗ `Karim Tazi` (stale_value) | ✓ |
| Q27 | Qui est le responsable du compte argan d'or ? | `Nadia Berrada` | ✗ `unknown` (no_answer) | ✗ `unknown` (no_answer) | ✓ | ✓ |
| Q28 | Who is the account owner for Bab Rayan Consulting? | `Youssef Benali` | ✓ | ✓ | ✗ `Omar Fassi` (stale_value) | ✓ |
| Q29 | Qui est le responsable du compte atlantic fishing company ? | `Mehdi Alaoui` | ✗ `unknown` (no_answer) | ✓ | ✓ | ✓ |
| Q30 | Chkoun l'owner dyal Al Massira? | `Salma El Idrissi` | ✗ `unknown` (no_answer) | ✓ | ✓ | ✓ |
| Q31 | What is the main phone number of Sahara Tech? | `+212592846751` | ✗ `unknown` (no_answer) | ✗ `unknown` (no_answer) | ✓ | ✓ |
| Q34 | Quel est le numéro de téléphone de Zitoun Cosmetics ? | `+212579101995` | ✓ | ✗ `+212670914607` (stale_value) | ✗ `+212670914607` (stale_value) | ✗ `+212670914607` (stale_value) |
| Q35 | Quel est le numéro de téléphone de AFC ? | `+212524415035` | ✗ `+212578098257` (wrong_customer) | ✗ `+212578098257` (wrong_customer) | ✓ | ✗ `unknown` (no_answer) |
| Q37 | Quelle est l'adresse du siège social de dar el hana immobilier ? | `21 Avenue Hassan II` | ✗ `unknown` (no_answer) | ✓ | ✓ | ✗ `unknown` (no_answer) |
| Q40 | What is the registered office address of Yasmine? | `Avenue Mohammed VI, Malabata` | ✗ `Port de Dakhla` (wrong_customer) | ✓ | ✗ `58 Rue Oued Sebou` (stale_value) | ✓ |

## Reading this report

- With the stub model, the answer is whatever the context literally contains first. This measures what each agent's *context* supports, not model reasoning. Run with a real model (`canon eval --model claude`) for the end-to-end number; the stub is a deterministic CI check. The stub's *oracle* number is not meaningful: given every record of a customer, it answers with the first value it finds, which is often the stale one. A real model weighs dates and sources.
- Confidence intervals are per agent; the McNemar test is the right comparison because both agents answer the same questions.
- The synthetic data and the questions were written by the same team that built Canon. Treat the lift as an upper bound until reproduced on a customer's data with the customer's questions.
