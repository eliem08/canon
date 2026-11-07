# Canon: status and gap analysis

*Audit date 2026-10-16 · repo state: `claude/funny-keller-2ivw36` @ `dfd70c9` (PR #1, open) · assumed 30-day clock starts at the
first commit, 2026-10-15, so this is **day 2 of 30** (UNVERIFIED: the real start date is the founder's).*

**Independence caveat.** This audit was done by the same AI agent that wrote most of the code. I tried to attack my own work
(section 1 stress tests), but a human should review it before it is used to make decisions.

## Update: end of day 2 (repo @ `8ac73ca`, PR #1)

*This section supersedes the percentages and the task list below; the original audit is kept unchanged under it for the record.
Same independence caveat: written by the agent that built it.*

**Verdict: still AT RISK.** Engineering risk dropped sharply: STATUS tasks 1–7 are built and tested, along with the audit
report generator and client-side packaging. Two things did not move: commercial risk (no design partner or data sample in the
repo), and the eval's headline claim.

| Goal | Audit (morning) | Now | Evidence / what's left |
|---|---|---|---|
| 1. CRM + Slack + Drive/PDF pipeline, ER, MCP | ~35% | **~75%** | PDF/OCR/DOCX/XLSX/CSV, folder ACLs, private channels, HTTP + tokens, Docker image verified offline (`docs/DOCUMENTS.md`, `docs/DEPLOY.md`). Missing: any real export, the Drive API (folder exports only), SSO. |
| 2. Public eval, gap ≥ 40 pts | ~50% | **~45%: the claim is falsified as stated** | vs keyword RAG: +35–42 pts (p < 1e-4). vs **strong RAG**: 0 to +5 pts, **not significant** on 4 models × 2 question sets. As a sales rep, raw-file RAG reads restricted text in 35/40 answers, Canon in 0/40 (`docs/EVALS.md`). Not public. |
| 3. Two paid pilots | ~3% | **~10%** | The deliverable now exists (`canon audit`, sample `docs/reports/audit_report_sample.md`), plus a runbook to run it inside a client's network. Still zero outreach evidence in the repo. |
| 4. ≥ 70% reusable code | ~40% | **~55% (unproven)** | Connectors read standard formats; country, currency and date conventions are config; no client logic in core. Only measurable on a real deployment. |

**The decision this forces (founder):** Goal 2 as written ("a gap of 40+ points") is only true against a weak baseline. The
evidence supports a different pitch: *as accurate as a well-built RAG, without reading what the user may not see, with every fact
cited, and with an audit of what's wrong in your data.* Either adopt that pitch, or test the accuracy claim on a client's data,
where histories are longer and names messier. Don't publish "+40".

**Next 2 weeks (replaces section 5):**
1. **Founder:** one design partner, an export, their questions. This blocks everything below.
2. Run `canon audit` on their data, inside their network; send the quarantine and the review queue on day 3.
3. Eval on *their* questions against strong RAG, with `--runs 3` and a client-hosted model if consent requires it.
4. Shrink Canon's tool output (about 2× strong RAG's context) and re-measure.
5. Based on what their data shows: Drive API connector, SSO, or ER tuning on their labelled pairs.

## Verdict: **AT RISK**

The engineering core came together unusually fast. A seeded dataset, entity resolution (F1 0.991), fact scoring, a 4-tool MCP server
with caller-based filtering, and a before/after eval all work, and all 116 tests and all 7 CI runs are green. But everything is
proven on data that the same author generated, and the places where real client data will hit (Drive/PDF/OCR ingestion, text
extraction, real permissions) are either absent or fail my own stress tests. Goal 1 is missing its Drive/PDF leg entirely;
Goal 2's headline gap is borderline (mean +38.75 points against a 40-point target) and is mostly an entity-resolution effect that
a buyer's engineer could partly rebuild; Goal 3 has zero evidence in the repo. It is not *off track* because 28 days remain, the
architecture is sound, and the fixes are known and bounded. It is at risk because the commercial clock (two paid pilots) depends on
getting a real data sample and a design partner, and nothing in the repo shows either exists yet.

---

## 1. Evidence-based status

Status scale: not started / stub / working on synthetic data / production-ready. **Nothing is production-ready.**
All commands below were run by me on 2026-10-16 unless marked UNVERIFIED.

| Component | Status | Proof | What breaks / is missing |
|---|---|---|---|
| **ingest** (`canon/ingest`, 377 LoC) | **Working on synthetic data** | 3 connectors: `crm.py` (JSON), `slack.py` (workspace export), `contracts.py` (`.txt`). Tests: `tests/test_ingest.py` (6), `tests/test_ingest_common.py` (7); `test_load_all_covers_every_ground_truth_record` loads 119/119 records. | Extraction rules mirror the generator's templates. Stress test (appendix A): 0 of 3 paraphrased Slack owner/renewal/value statements extracted; 2 false positives accepted as facts; contract parser turns `1,426,000.00` into **142,600,000** (a silent 100× error, `contracts.py:52`) and ignores long-form dates (`17 mars 2026` → no date). Formats are invented, so match against real exports is UNVERIFIED. |
| **Drive / PDF connector** | **Not started** | `grep -riE "ocr\|pdf\|drive\|imap\|salesforce\|hubspot" canon` finds nothing outside comments and a free-mail domain list. Contracts are stored as pre-extracted `.txt` (DECISIONS #4). | The "Drive/PDF" leg of Goal 1 does not exist. |
| **scanned-doc OCR** | **Not started** | Same grep: no OCR library, no image handling. | Arabic/French scans are likely in a real contract corpus (UNVERIFIED). |
| **resolve** (`canon/resolve`, 798 LoC) | **Working on synthetic data** | `canon resolve --report --seeds 50`: pairwise P 1.000 / R 0.983 / **F1 0.991**; B-cubed 0.993; blocking keeps 100% of true pairs at 94.4% reduction. Tests: `test_pipeline.py::test_f1_target_on_committed_dataset`, `test_resolve_units.py` (10). Scale test (appendix B): 4,760 records, F1 0.972, 17.4 s. | **False merges verified** on generic names: `Pharmacie Al Amal` (Rabat) vs `(Fès)` and `Boulangerie` vs `Boucherie Al Baraka` both merge (p = 0.50 and 0.56 against a ≥ 0.5 threshold, `pipeline.py:19`). Translations don't match: `Maroc Telecom` vs `اتصالات المغرب` p = 0.006. Entity IDs are positional (`pipeline.py:47`, `C{i:04d}`), so they change when data changes. No human review queue, no unmerge. At scale, 118 of 4,568 blocking keys exceed the size cap and are discarded (pair completeness 0.893). Runtime grows faster than linearly: 17.4 s at 4.8k records, so 100k+ would need rework (extrapolation, UNVERIFIED). |
| **score** (`canon/score`, 279 LoC) | **Working on synthetic data** | Fact accuracy **0.968** vs 0.904 "latest wins" and 0.955 "authority wins"; confidence separates right from wrong (0.74 vs 0.09); all 140 facts at confidence ≥ 0.3 are correct, 11 of the 13 facts below 0.3 are right too. Tests: `tests/test_score.py` (7). | Authorities and half-lives are hand-set (DECISIONS #16-18). Owner is 0.923 (2 misses). The benchmark barely exercises this component: with perfect retrieval a raw-data agent already scores 92.5-95% (appendix C). |
| **mcp_server** (`canon/mcp_server`, 389 LoC) | **Working on synthetic data** | 4 tools (`get_customer`, `find_contract_terms`, `who_owns`, `list_conflicts`). `examples/mcp_client.py` launches `canon serve` over stdio and gets answers (exit 0, ~2 s). `tests/test_mcp.py`: 10 functions / 16 cases pass, including a real MCP-protocol test. 2.3 ms per `get_customer` call in-process. | stdio only; no HTTP, no auth. `canon serve` itself is not unit-tested (`cli.py` coverage 22%; only the example client exercises it). Connecting to Claude Code/Desktop as documented in `docs/MCP_SERVER.md` is UNVERIFIED (no Claude client here). |
| **permissions** | **Working on synthetic data (policy, not inherited permissions)** | ACL-before-scoring: `service.py:111-116` filters records by caller group before any fact is computed. Tests: unauthorized callers get nothing from any tool for all 25 customers (3 callers × 25 × 4 = 300 checks); no response cites a record the caller can't read (5 callers × 25 × 4 = 500 checks); pinned identity cannot be overridden. All pass. | ACLs are **static constants per source type**: CRM `("sales","exec")` `crm.py:31`, Slack `("sales",)` `slack.py:35`, contracts `("legal","exec")` `contracts.py:16`. Slack channel `members` is exported by the generator but never read. Real Drive sharing and Slack private-channel membership are not ingested. Caller identity is **self-asserted** unless `--caller` pins it. No audit log (`grep logging\|audit canon` → nothing). The full dataset is loaded in server memory and stored unencrypted in `out/canon.sqlite`. |
| **evals** (`canon/evals`, 723 LoC) | **Working on synthetic data** | 40 questions, stub model + 4 real Baseten models; `docs/reports/` holds the ER report and 5 eval reports (stub + 4 models), each eval report with a JSON of every answer. Tests: `tests/test_evals.py` (11). | Questions are generated from the generator's seed list (`questions.py:15` imports `canon.synth.seeds`), so the question builder can't run on a client's data. The Canon agent finds the customer by trying the last ≤ 6 words of the question (`agents.py:128`); when the name isn't at the end it fails (appendix A: 2 of 4 phrasings). Details in section 4. |
| **multilingual (Arabic / French / Darija)** | **Working on synthetic data (narrow)** | 19 of the 25 generated customers have an Arabic-script name, but only **4 records** in the committed dataset are identified primarily by one (CRM "arabic" variant; the rest carry it as a secondary name in contracts). All 4 land in the correct cluster, a very small sample. Darija appears in generated Slack chatter and CRM `Chrikat …` names. `tests/test_normalize.py` (7). | Matching is transliteration only; translations fail (above). Arabic-Indic digits aren't normalized: `normalize_phone("٠٥٢٢١٢٣٤٥٦٧")` → `+٠٥٢٢١٢٣٤٥٦٧`. Darija support is a keyword list (`chrika`, `chrikat`: `normalize.py:36`; question cues in `evals/scoring.py`). Moroccan assumptions sit in core code: default country code `212` (`common.py:20`), ICE regex (`contracts.py:24`). |
| **deployment / VPC** | **Not started** | No Dockerfile, compose, Makefile, IaC or runbook in `git ls-files`. CI is lint + pytest only. Runs via `uv run` on a developer machine. | No packaging, no secrets handling beyond `.env.example`, no client-hosted option, no data-residency story. |

**What is genuinely solid** (fair credit): lineage is deterministic (record-level, not LLM-generated); the ACL-before-scoring
design is the right one; typed MCP outputs with sources/confidence/alternatives; every decision is logged (`docs/DECISIONS.md`,
37 entries); docs state their own gaps; the same pipeline reproduces from a seed in about 10 seconds.

---

## 2. Metrics table

| Metric | Target | Current | Notes / evidence |
|---|---|---|---|
| ER precision / recall / F1 (pairwise) | F1 ≥ 0.90 | **1.000 / 0.983 / 0.991** | Synthetic only. 26 clusters vs 25 true entities (one missed link: Slack channel `tmf`). **Real data: UNVERIFIED.** |
| ER F1, "held-out" seeds 1-50 | n/a | mean 0.994, min 0.975 | **Not held out**: all seeds use the same 25 customers, names, aliases and templates (verified: identical name sets). Measures randomness robustness only. |
| ER F1 at scale (4,760 records, synthetic replicas) | n/a | 0.972 (P 0.973, R 0.971) | 17.4 s; unique IDs per replica make this easier than real data. |
| Fact accuracy (6 fields, vs ground truth) | n/a | 0.968 | latest-wins 0.904; authority-wins 0.955 |
| **Eval: raw vs Canon, stub model** | gap ≥ 40 pts | 60.0% → 97.5% (**+37.5**) | n = 40, one run. 10 regenerated datasets (same names): 45.8% → 98.2%. |
| **Eval: raw vs Canon, 4 real models** | gap ≥ 40 pts | Kimi-K3 57.5 → 97.5 (**+40.0**); DeepSeek-V4-Pro 57.5 → 90.0 (**+32.5**); Nemotron-3-Ultra 57.5 → 97.5 (**+40.0**); GLM-5.3 55.0 → 97.5 (**+42.5**) | **Mean +38.75**. Three of four reach ≥ 40 with a margin of at most one question (2.5 pts). 95% Wilson CIs: raw 57.5% [42.2, 71.5], Canon 97.5% [87.1, 99.6]. |
| Eval: raw data with **perfect** retrieval (oracle) | n/a | Nemotron 92.5%, GLM-5.3 95.0% | The raw agent given every chunk of the right customer (selected with the hidden ground truth). Canon's scoring adds roughly 2.5-5 points on this benchmark; the rest of the gap is entity resolution + retrieval. |
| Test count / pass | n/a | **116 pass** (75 test functions, 11 files, 11 s) | |
| Line coverage | n/a | **94%** (2,135 statements, 132 missed) | Coverage of synthetic-shaped paths. `cli.py` 22%. Not a robustness measure. |
| CI status | green | **7/7 runs green** (GitHub Actions) | Jobs: `ruff check`, `ruff format --check`, `pytest`. No coverage gate, secret scan, dependency audit or SAST. |
| MCP tools | 4 | **4** | |
| ACL tests | all pass | **16/16** in `tests/test_mcp.py` (≈ 800 caller × tool × customer checks) | Tests prove the filter works on *configured* ACLs; they say nothing about whether those ACLs match a client's real permissions. |
| Ingestion sources supported | CRM + Slack + Drive/PDF | **3 formats, all synthetic**: CRM JSON, Slack export, contract `.txt` | Real sources: **0**. Drive: 0. PDF parsing: 0. OCR: 0. Email: 0 (type exists, no connector). |
| Reusable code share | ≥ 70% per deployment | **~82% by LoC, but not a valid measure** | Engine (resolve + score + store + models + MCP + eval runtime) 2,261 LoC vs 500 LoC per-source/per-client (ingest 377 + question builder 123). One dataset exists; no second deployment to measure. |

Size context: ≈ 3,800 non-test Python LoC, 752 test LoC, 25 commits in ~1.5 days, one author, PR #1 touches ≈ 250 files (mostly generated
data and reports), **no reviews, no issues, `main` still contains only the initial commit and is unprotected.**

---

## 3. Gap to goal

### % complete (judgment, with reasoning)

| Goal | % | Reasoning |
|---|---|---|
| **1. Working CRM + Slack + Drive/PDF pipeline with ER, exposed via MCP** | **~35%** | Engine, ER and MCP exist and run on synthetic CRM/Slack/contract-text. Missing: Drive, PDF parsing, OCR, any real export format, hosting. The part that exists is the *easier* half; extraction already fails my paraphrase tests. |
| **2. Public before/after eval, gap ≥ 40 pts** | **~50%** | Harness is real and reproducible; the gap is 37.5 (stub) / 38.75 (mean of 4 real models). But it is not public, uses author-built data and questions, n = 40, and a buyer can discount most of the gap (section 4, product risks). |
| **3. Two paid pilots ($5-15k audits)** | **~3%** | The repo has zero outreach, pricing, scoping, audit template or partner data. Only the eval report format can be reused as a deliverable. Anything outside the repo is UNVERIFIED. |
| **4. ≥ 70% reusable code per deployment** | **~40% (unproven)** | Structure is plausible: engine and connectors are separate; tunables are in config objects. But the first real deployment will add Drive/PDF/OCR and extraction code that doesn't exist yet, and core already contains Moroccan/French assumptions. No second data source to measure against. |

### Critical path to a real pilot on a client's data

The first product is an **audit**, so the minimum is an **offline batch run on an exported sample**, not a hosted multi-tenant service.

1. **A real data sample and a signed OK to use it** (founder; blocks everything below). Needed: CRM export (their real format), Slack export (or whatever they actually use), ~50-200 contracts/PDFs including scans.
2. **Real-document ingestion:** PDF text extraction + OCR (Arabic/French) + a folder-export Drive connector, with page-level citations.
3. **Extraction that survives paraphrase and bad formats:** LLM-assisted extraction with deterministic validators and quarantine for unparseable values (never guess), with source spans in lineage.
4. **ER calibrated on the client's data:** ~300 labelled pairs, a review queue for borderline merges, generic-name guards, stable IDs.
5. **Client-written eval set** (≥ 100 questions, written by their people, not generated) and a stronger baseline (embedding RAG + tool use, and oracle-retrieval for honesty).
6. **Minimum security:** authenticated identity, ACLs derived from the client's actual permissions (or explicitly mapped and signed off), audit log, untrusted-text handling, no data leaving the client's environment without consent.
7. **Deliverable:** the audit report (readiness findings + before/after numbers with confidence intervals + failure analysis).

A VPC/hosted MCP deployment can wait until a client pays for it.

### Demo-ware vs. what survives

| Likely to survive real messy data | Demo-ware today |
|---|---|
| ER architecture (blocking → pairwise → clustering with cannot-links), golden record + lineage model | The dataset and the 40 questions (same author, same templates) |
| Scoring model shape (authority × freshness, conflicts kept as alternatives) | Slack/contract extraction rules (mirror the generator's templates) |
| ACL-before-scoring design and typed MCP surface | "Permission-aware": static per-source groups; self-asserted identity |
| Eval harness structure (agents, models, grading, failure taxonomy) | "Held-out seeds" (same 25 customers); `partial_view` untested against real permissions |
| Test discipline, decision log, reproducible pipeline | Name vocabulary (`chrika`), Moroccan defaults in core, entity linking by trailing words |

---

## 4. Risks, ranked by severity

### 1. Silent wrong values at high confidence *(technical, trust-killing)*
`contracts.py:52` strips every non-digit, so `1,426,000.00` becomes 142,600,000 (verified); contract values carry the highest authority
(0.95), so a wrong one wins. A single visible 100× error in a pilot ends the engagement. Also: long-form French dates return no date,
and Slack extraction accepts false positives (`"<@U05> should be the owner of the follow-up task"` → account owner). Failure mode to
design out: unparseable or low-evidence input must be *quarantined and flagged*, never guessed.

### 2. Overfit to the synthetic data *(technical + product)*: suspected, with evidence
- Same 25 customers across all "held-out" seeds (verified).
- Slack cues (`slack.py:32-34`: `reprend le compte`, `deal`, `renouvellement`) and contract regexes (`contracts.py:27`) are the generator's templates; paraphrase test: 0 of 3 true statements extracted.
- Eval routing keywords and trailing-name entity linking were written alongside the question templates; 2 of 4 alternative phrasings fail.
- I tuned on the evaluation data: the short-skeleton discount after a failed held-out seed (DECISIONS #11), and the acronym and phone half-life changes after the eval exposed misses (commit `d00e059`). There is no train/test split between development data and reported numbers.
- The generator assumes "the newest statement is true", which my scoring then rewards.

### 3. The eval's headline gap mostly measures entity resolution, not Canon's full value *(product)*
- With perfect retrieval, a raw-data agent reaches **92.5-95%** vs Canon 97.5% (appendix C). A sharp buyer's engineer will say: "better entity linking over our RAG gets most of this."
- The baseline is BM25 top-5 with no tools: a straw man by 2026 standards.
- n = 40, one run per model: the CIs are wide (Canon 87-99.6%, raw 42-72%); of DeepSeek-V4-Pro's three extra Canon misses, one came back correct on re-run (run-to-run variance); and Kimi-K3 and Nemotron-3-Ultra hit "40" by exactly one question.
- Permissions, the other half of the pitch, aren't measured by the eval at all.
- Mean lift is **38.75**, below the 40-point target.

### 4. Security *(severity high for any client pilot)*
- **ACLs are configured, not inherited** (static constants per source; Slack membership ignored). "Permission-aware" could over-share everything in a group.
- **Self-asserted identity** unless `--caller` is pinned; no transport authentication.
- **Prompt injection:** source text is returned verbatim to the agent (verified: an alias containing instructions comes back unchanged in `get_customer.aliases`). Slack/contract content is attacker-influenced in many organizations.
- **No audit log, no rate limiting**; whole dataset in server memory and in plaintext `canon.sqlite`: a filter bug is a full leak, with no second layer.
- **Data egress:** the eval sends context to third-party LLM APIs (fine for synthetic data; a client's data needs explicit consent and may need a local model).
- **Secrets:** none in the repo or git history (checked). Hygiene note: an API key was pasted into the development chat. I did not store it, but it should be rotated (UNVERIFIED whether it has been).
- **Info leaks by design:** `partial_view` reveals that restricted sources exist; entity clusters are computed over all records.

### 5. Entity-resolution failure modes on real data *(technical)*
Verified: generic-name false merges, translation misses, Arabic-Indic digits, positional IDs, block-size cap dropping candidates at scale,
superlinear runtime, no review/undo. Unverified but likely: franchises/branches/subsidiaries (`Atlas Logistique` vs `... Maroc` scores 0.73), shared
phone numbers/domains across group companies, missing identifiers in real CRMs, merged/renamed companies over time. **Hallucinated lineage** is
not a risk today (lineage is deterministic) but lineage is record-level (a Slack channel, not a message; a contract file, not a page). Once an LLM
extracts facts, span-level citations with verification are required.

### 6. Commercial *(what a client would reject)*
- "Show me this working on *our* data": the Drive/PDF/OCR leg doesn't exist.
- "Where does our data go?": no self-hosted/VPC story, no audit log, no DPA-ready posture.
- "Why not RAG plus a better CRM dedupe?" (risk 3).
- Scope risk: an audit at $5-15k must be bounded; a custom connector per client is the consulting trap (Goal 4).
- Possible channel mismatch: the pilot's real conversation data may be WhatsApp/email, not Slack (founder question).

### 7. Process
One author (an AI agent), all work in one unreviewed 250-file PR, `main` empty and unprotected, CI without coverage/security gates.
Fast but unaudited by a human.

---

## 5. Next 2 weeks (7 tasks, in priority order)

| # | Task | Effort | Metric it moves | Done when |
|---|---|---|---|---|
| 1 | **Secure a real data sample and define the audit as an offline batch deliverable.** One design partner (or a realistic public corpus if none yet); written scope: inputs, outputs, price, what stays on their side. | S (founder-led) | Goals 1 and 3 | A partner has sent (or approved sending) a CRM export + Slack export + ≥ 50 contracts including ≥ 5 scans, with written permission; a 1-page audit scope exists. |
| 2 | **Harden parsing; quarantine instead of guess.** Money, dates (EN/FR/AR, long-form, Arabic-Indic digits), phones; unparseable → flagged with raw text kept. | S | Wrong-value rate (risk 1) | A 40-case adversarial fixture set (formats above) passes ≥ 95% with **zero silent wrong values**; `1,426,000.00` and `1.426.000,00` both parse to 1,426,000. |
| 3 | **PDF text + OCR (FR/AR) + folder-export Drive connector**, with page-level citations on every extracted fact. | L | Goal 1 (35% → ~65%) | ≥ 20 real/realistic PDFs (≥ 5 scanned, FR and AR) yield contract number, value, dates and signatory, each cited to a page; character error rate on the scans is reported. |
| 4 | **Robust extraction with source-span lineage:** LLM-assisted extraction for Slack and contracts, with the deterministic parsers kept as validators. | M | Extraction F1 and false-positive rate (risk 2) | On a 150-message Slack set and 30 contracts written/paraphrased *independently of the generator*, owner/value/renewal F1 ≥ 0.85 and false positives < 5%; every fact cites a message timestamp or page. |
| 5 | **Eval v2 that a buyer would believe:** independently written questions (≥ 150), stronger baselines (embedding RAG with tools, plus the oracle-retrieval baseline), 3 runs per model, confidence intervals. | M | Goal 2 credibility | Report shows each baseline with 95% CIs; the claim is stated against the *strongest* baseline; question builder no longer imports `canon.synth.seeds`. If the gap vs the strongest baseline is < 40 pts, the report says so and the pitch is adjusted. |
| 6 | **ER guards and a review queue:** generic-name rule, branch/subsidiary handling, stable entity IDs, borderline (p 0.4-0.7) review queue, unmerge. | M | ER precision on adversarial pairs | A 50-pair adversarial suite (generic names, branches, translations) scores precision ≥ 0.95 and recall ≥ 0.8; entity IDs unchanged after adding 10% more records. |
| 7 | **Minimum client-grade security:** transport-authenticated identity mapped to groups, ACLs derived from source permissions (Slack channel membership, Drive sharing; or an explicit signed-off mapping), audit log per tool call, source-text quoting. | M | Security risk (risk 4) | Integration test with two authenticated tokens: cross-group queries denied; one audit-log record per call; a prompt-injection fixture is returned inside a clearly delimited, non-instruction field; ACLs for the sample come from the sample's own metadata. |

### Deliberately do NOT build yet
- Hosted multi-tenant service, VPC/Kubernetes automation, UI or dashboards (an audit is a batch deliverable; offer a Docker image only if a client asks).
- More MCP tools, field-level ACL engine, MCP OAuth beyond what task 7 needs.
- Learned ER weights or embedding-based matching (no labels yet; revisit after task 6 labels exist).
- More synthetic data, extra generator seeds, fancier fake customers.
- Connectors beyond the pilot's real stack (WhatsApp, Teams, email) until the partner confirms what they use.
- Caching/performance work, fine-tuning, a landing page.

---

## 6. Non-technical blockers (questions for the founder)

1. **Design partner:** is there a named company that will share data? If not, what is the plan for getting one within 2 weeks? Who in that company can approve data access?
2. **Data-access agreement:** what NDA/DPA covers a CRM, Slack and contract export that includes personal data? Is the data subject to Moroccan data-protection rules (Law 09-08 / CNDP) or the EU GDPR? (Ask counsel; I'm not asserting what applies.)
3. **Where can the data go?** May the client's data be sent to a third-party LLM API (Anthropic, Baseten, etc.), or must everything run on their machine/VPC with a local model? This decides the architecture of tasks 3-4.
4. **What do they really use?** Is the real conversation data Slack, WhatsApp, email or Teams? Which CRM (Salesforce, HubSpot, Odoo, spreadsheets)? Where do contracts live (Drive, SharePoint, a shared folder, paper scans)?
5. **Audit definition and price:** what exactly is delivered for $5-15k (a report? a running MCP server? a data-readiness score?), by when, and what is the acceptance test? What happens after the audit (the upsell)?
6. **Who buys?** Which role signs a $5-15k audit, and what outcome do they care about (agent accuracy, compliance, cost)? Is "MCP readiness" a phrase they use?
7. **Public eval vs client confidentiality:** the public before/after number must come from synthetic or public data. Is a synthetic benchmark acceptable as the "public" proof, or do you need a public-corpus benchmark? Who reviews it independently?
8. **Capacity:** who besides the AI agent writes and reviews code in the next 14 days? Who talks to prospects?
9. **Pilot success criteria:** what result makes a client say yes to a second phase, and what result makes them walk?
10. **Reuse vs consulting trap:** are you willing to say no to a client-specific connector request in pilot 1 to protect the 70% target, and what's the rule?
11. **Credentials hygiene:** an API key was pasted into the development chat. Has it been rotated?
12. **Start date:** is the 30-day clock really at day 2, or did it start earlier?

---

## Appendix: how this was verified (reproducible)

Commands run from the repo root on 2026-10-16:

```bash
uv run --with pytest-cov pytest -q --cov=canon --cov-report=term-missing:skip-covered   # 116 passed, 94%
uv run ruff check . && uv run ruff format --check .                                     # clean
uv run canon resolve --report --seeds 50 --as-of 2026-10-01                            # F1 0.991; 50 seeds mean 0.994
uv run canon eval --seeds 10                                                            # 60.0% -> 97.5%; seeds 45.8% -> 98.2%
uv run python examples/mcp_client.py "Zitoun Cosmetics"                                 # stdio end to end, exit 0
```

Scripts used for the experiments below were scratch files, not committed (this PR changes only this document). Their essentials:

**A. Stress tests (extraction, parsing, linking, ER).**
```python
# Slack: channel_to_record(channel, [{"ts": ..., "text": t}], users, SlackConfig(), "x") for each t:
#   "<@U03> took over this account from today"            -> []                       (missed)
#   "Karim is now the account manager for Acme"           -> []                       (missed)
#   "<@U05> should be the owner of the follow-up task..." -> owner=Mehdi Alaoui       (FALSE POSITIVE)
#   "Renewal moved to 15 March 2028"                      -> []                       (missed)
#   "new ACV is 480,000 MAD"                              -> []                       (missed)
#   "Discussed the contract, they want a 12000 MAD discount" -> contract_value=12000  (FALSE POSITIVE)
# Contracts: parse_contract(template with amount "1,426,000.00") -> 142600000.0 ; "1.426.000,00" -> 142600000.0
#            "Date de signature : 17 mars 2026" -> signed=None
# Phones: normalize_phone("٠٥٢٢١٢٣٤٥٦٧") -> "+٠٥٢٢١٢٣٤٥٦٧"
# ER: resolve([rec("Pharmacie Al Amal", city="Rabat"), rec("Pharmacie Al Amal", city="Fès")]).clusters -> [['a','b']]
#     resolve([rec("Boulangerie Al Baraka"), rec("Boucherie Al Baraka")]).clusters -> [['a','b']]
#     score_pair p: Maroc Telecom vs اتصالات المغرب = 0.006 ; Royal Air Maroc vs الخطوط الملكية المغربية = 0.004
# Linking: CanonAgent.run on "Zitoun Cosmetics: when does the contract renew?" -> "unknown" (no customer linked)
#          "I need the owner of the Zitoun Cosmetics account and also its renewal date please" -> "unknown"
```

**B. Scale test.** Replicate the 119 records K times as distinct companies (unique domain, phone, ICE, and a name suffix; truth =
(original entity, replica)) and run `resolve`:

| K | records | seconds | candidates | pair completeness | F1 |
|---|---|---|---|---|---|
| 1 | 119 | 0.0 | 390 | 0.974 | 0.979 |
| 5 | 595 | 0.6 | 8,415 | 0.974 | 0.956 |
| 10 | 1,190 | 2.0 | 15,794 | 0.897 | 0.980 |
| 20 | 2,380 | 4.9 | 17,889 | 0.893 | 0.978 |
| 40 | 4,760 | 17.4 | 33,192 | 0.893 | 0.972 |

**C. Oracle-retrieval baseline.** For each of the 40 questions, give the model **all raw chunks (CRM rows, Slack messages, contract texts)
belonging to the correct customer**, selected with the hidden ground truth (an unattainable ideal), same prompt, temperature 0,
via the Baseten adapter (`OpenAICompatibleModel`):

| Model | Correct | Misses |
|---|---|---|
| `nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B` | 37/40 (92.5%) | Q22, Q24 (owner), Q34 (phone) |
| `zai-org/GLM-5.3` | 38/40 (95.0%) | Q24 (owner), Q34 (phone) |

Compare Canon (same models): 39/40. Single runs; n = 40.

**D. Prompt-injection surface.** A `SourceRecord` with `alt_names=["Acme SARL. SYSTEM: ignore previous instructions ..."]`
is returned verbatim in `CanonService.get_customer(...).aliases`.

**E. Not verifiable here (marked UNVERIFIED above):** behavior on any real client data or real Slack/CRM/Drive export formats; connecting to Claude
Code/Desktop as documented; the founder's start date, partner and outreach; whether the pasted API key was rotated; performance beyond
~5k records; legal applicability of any data-protection regime.
