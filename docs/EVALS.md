# Eval harness (Milestone 5)

The sales proof: the same model answers the same questions three times: with naive retrieval over
the raw exports, with *perfect* retrieval over the raw exports (oracle), and with Canon's MCP tools.
Baseline → Canon is what Canon adds; oracle → Canon is the part that better search alone can't give.

```bash
uv run canon eval                              # stub model, offline, ~2 s (what CI runs)
uv run canon eval --seeds 10                   # plus 10 regenerated datasets (held-out check)
uv sync --extra claude && uv run canon eval --model claude    # real model (needs credentials)
uv run canon eval --model claude --model-id claude-opus-5-5 --caller salma.el.idrissi
BASETEN_API_KEY=... uv run canon eval --model baseten --model-id <model slug from Baseten>
uv run canon eval --questions data/eval/paraphrase_questions.json   # hand-written questions
uv run canon eval --questions client_questions.json --runs 3        # a client's set, 3 repeats
```

In a cloud session where the key is stored as an environment *secret* (injected by the network
proxy, so it never enters the sandbox), add `--proxy-credentials`.

Otherwise keys are read from environment variables only (`ANTHROPIC_API_KEY`/`ant auth login` for Claude,
`BASETEN_API_KEY` for Baseten). Never put them in a repo file; `.env` is gitignored, but prefer
the environment's secret settings.

Output: `out/eval_report.md` (+ `.json` with every answer and agent trace). The committed
copy is [`reports/eval_report.md`](reports/eval_report.md).

## Questions

The harness loads questions from a file (`--questions`, default
`<data>/ground_truth/eval_questions.json`). A client's set is a JSON list of
`{"id", "type", "question", "expected"}`; `entity_id` is optional (without it, and without a ground
truth, the oracle agent and the "wrong customer" failure class are skipped).

Two sets are committed:

* **Synthetic (40):** `canon/evals/questions.py` derives them deterministically from the hidden
  ground truth (`canon generate` writes them). The customer mention ends each question.
* **Hand-written paraphrases (30):** `data/eval/paraphrase_questions.json`. These are informal
  EN/FR/Darija questions with the customer named **mid-sentence** ("Before I call Atlas Logistique
  tomorrow, who on our side owns that account?"). Expected answers are filled from the ground
  truth by `entity_id`.

| Type | Count | Expected answer |
|---|---|---|
| contract_value | 10 | current annual value (active contract) |
| renewal_date | 10 | current renewal date |
| owner | 10 | current account owner |
| phone | 5 | main (switchboard) phone |
| address | 5 | current registered address |

Phrasing mixes English, French and Darija ("Chkoun l'owner dyal …?"). The customer is named the
way people actually write it: canonical, with a legal suffix (sometimes the wrong one), lowercase,
with a typo, as "chrikat …", by alias (`AFC`, `Rif Cement`), or in Arabic script (`سوس فريش`).

## Agents

All agents use the same model and prompt. Only the context differs.

* **Baseline:** BM25 over raw chunks (CRM rows, individual Slack messages, contract texts),
  top 5 chunks.
* **Oracle:** every raw chunk of the question's true customer, taken from the answer key, and
  nothing else. This is perfect retrieval. Whatever it still gets wrong comes from the raw data
  itself: stale CRM values, superseded contracts, owner changes buried in chat.
* **Canon:** links the customer by probing `get_customer` with every span of up to 6 words that
  doesn't start or end with a function word, keeping the best match (on a tie, the longer span).
  It then calls `find_contract_terms`, `who_owns` or `get_customer` over MCP, according to the
  question type the wording points to, or `get_customer` (every field) when the wording is unclear.
  It passes the structured result as context. It acts as `revops.admin` by default (`--caller` to
  change).

**Statistics:** each accuracy has a 95% Wilson interval. Canon vs. baseline is compared with an
exact McNemar test on the questions where exactly one of them is right, which is the right test for
paired answers. `--runs N` repeats the eval and tabulates every run, since real models vary.

## Models

* `StubModel` (CI): deterministic. From JSON it reads the asked field's `value`; from raw text it
  takes the first matching value in the highest-ranked chunk. It measures what each agent's
  *context* supports, with no reasoning. A real model will do better than the stub on the
  baseline, for example by noticing "annule et remplace" (cancels and replaces).
* `ClaudeModel`: Anthropic SDK (optional `claude` extra).
  * Defaults to `claude-opus-5-5` at `effort: low`, with a short "answer only, or `unknown`"
    system prompt.
  * Refusal fallback is on (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`), and a
    `refusal` stop reason is graded as no answer.
  * Any object with `answer(question, context) -> str` plugs in.
* `OpenAICompatibleModel`: any OpenAI-compatible Chat Completions endpoint, with a `baseten`
  preset (`https://inference.baseten.co/v1`, key from `BASETEN_API_KEY`). It uses temperature 0
  and strips inline `<think>` blocks from reasoning models. It retries 429/5xx
  with backoff. There is no default model: pass the provider's model slug with `--model-id`.

## Grading and failure analysis

`is_correct` accepts free text:

* amounts within 0.5% (`1 426 000 MAD`, `1,426,000`)
* dates in ISO, `dd/mm/yyyy`, "March 1, 2028" or "1er mars 2028"
* owner names contained in the answer
* phones matched on their last 9 digits
* addresses matched by token-set similarity of at least 90

Wrong answers are classified against the ground truth and the raw source values:

* **stale value:** a real but outdated or superseded value of the right customer
* **wrong customer:** another customer's value
* **no answer**
* **other**

## Results with real models (Baseten, eval v2, 2026-10-16)

Same prompt for every agent, temperature 0, one run per model. Per-model reports with every answer:
`reports/eval_<model>.md` (40 synthetic questions) and `reports/eval_paraphrase_<model>.md`
(30 hand-written questions).

**40 synthetic questions**

| Model | Baseline (BM25, raw) | Oracle retrieval (raw) | **Canon** | Canon vs. baseline (McNemar p) |
|---|---|---|---|---|
| `moonshotai/Kimi-K3` | 57.5% | 95.0% | **97.5%** | +40.0 pts (3e-05) |
| `deepseek-ai/DeepSeek-V4-Pro-0813` | 55.0% | 95.0% | **97.5%** | +42.5 pts (2e-05) |
| `nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B` | 57.5% | 92.5% | **97.5%** | +40.0 pts (1e-04) |
| `zai-org/GLM-5.3` | 55.0% | 95.0% | **97.5%** | +42.5 pts (2e-05) |

**30 hand-written questions (customer named mid-sentence)**

| Model | Baseline (BM25, raw) | Oracle retrieval (raw) | **Canon** | Canon vs. baseline (McNemar p) |
|---|---|---|---|---|
| `moonshotai/Kimi-K3` | 70.0% | 93.3% | **96.7%** | +26.7 pts (0.008) |
| `deepseek-ai/DeepSeek-V4-Pro-0813` | 73.3% | 93.3% | **96.7%** | +23.3 pts (0.016) |
| `nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B` | 66.7% | 90.0% | **96.7%** | +30.0 pts (0.004) |
| `zai-org/GLM-5.3` | 73.3% | 90.0% | **96.7%** | +23.3 pts (0.016) |

95% Wilson intervals at n = 40 are roughly ±10 points around 97.5% and ±15 around 55%; the paired
McNemar test is the meaningful comparison.

### What this says, plainly

* **Most of the lift is retrieval.** With *perfect* retrieval over the raw exports, real models reach
  90–95%. Canon adds only 2.5–6.7 points over that oracle. The baseline's misses are mostly
  "no answer": aliases, Arabic-script and lowercase names, and Slack owner mentions stored as
  `<@U03>`, which keyword search can't connect to the customer. Canon wins mainly by *finding the
  right records* (entity resolution + linking). Resolving conflicts helps much less on this data.
* **What reconciliation still buys** shows in the oracle's misses, which are always the same
  questions: an owner change announced only in Slack (Q24, P01, P09, Q22) and a stale contact
  mobile in the CRM (Q34, P27). Canon gets the owner changes right, except E11/P09 (a documented
  fact-scoring miss), and also misses the phone question (Q34: mobile vs. switchboard).
* **Honest positioning:** on clean, small synthetic data, an agent that gets every relevant record
  in its context does nearly as well as Canon. Real deployments can't do that: thousands of
  records per customer, permissions, tokens, cost. That is a claim to prove on client data, not
  something this eval shows. The oracle also needs the answer key, so it is an upper bound, not a
  product.
* **Stub vs. real models:** the stub's oracle score (50%) is meaningless, because it takes the
  first value it sees. Real models weigh dates and supersession, so they reach 90–95%.
* Models are not compared to each other: differences of 1–2 questions are noise at this size.

## Results (stub model, CI)

`reports/eval_report.md` (40 questions, with held-out seeds) and `reports/eval_paraphrase.md`
(30 hand-written). Baseline 60.0% / Canon 97.5% (held-out seeds 1–10: 45.8% / 97.2%);
hand-written: 63.3% / 96.7%. The stub is a deterministic regression check, not the headline.

## Caveats

* The stub numbers are a deterministic regression check; the real-model tables are the headline,
  and the oracle column is the honest frame for them.
* Questions, data and pipeline come from the same author, so the lift is an upper bound until it
  is reproduced on a customer's data with questions written by their team.
* The router's cue list was extended after the paraphrase questions were written (owner: "looks
  after", "s'occupe"; phone: "number", "dial"; address: "located"...), so routing on that set
  (30/30) is not independent evidence. When no cue matches, the Canon agent falls back to the full
  profile.
