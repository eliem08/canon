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

## Results (stub model, seed 20261001)

| | Baseline (raw files) | Canon (MCP) |
|---|---|---|
| Overall | 24/40 (60.0%) | **39/40 (97.5%)** |
| contract_value | 60% | 100% |
| renewal_date | 80% | 100% |
| owner | 40% | 100% |
| phone | 60% | 80% |
| address | 60% | 100% |
| Held-out seeds 1–10 | 45.8% (32–62%) | **98.2%** (92–100%) |

**Baseline failures** (16):

* 10 no answer: aliases, lowercase or Arabic-script names that keyword search can't find, and
  Slack owner mentions stored as `<@U03>` user IDs
* 4 wrong customer: a confuser's chunk ranked first
* 2 stale value: a superseded contract or a stale CRM value

**Canon's one miss** (Q34): CRM and Slack list a contact's mobile under the company's phone
field, while the contract lists the switchboard. Canon returns the mobile at low confidence (0.46)
with the switchboard as the alternative. Companies have several numbers, and Canon doesn't model
"main" vs. "contact" phone yet.

## Results with real models (Baseten, 2026-10-16)

Same 40 questions, same prompt, temperature 0, one run per model (per-model reports in
`reports/eval_<model>.md`, with per-question answers in the matching `.json`).

| Model | Baseline (raw files) | Canon (MCP) | Lift |
|---|---|---|---|
| `moonshotai/Kimi-K3` | 23/40 (57.5%) | **39/40 (97.5%)** | +40.0 pts |
| `deepseek-ai/DeepSeek-V4-Pro-0813` | 23/40 (57.5%) | **36/40 (90.0%)** | +32.5 pts |
| `nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B` | 23/40 (57.5%) | **39/40 (97.5%)** | +40.0 pts |
| `zai-org/GLM-5.3` | 22/40 (55.0%) | **39/40 (97.5%)** | +42.5 pts |

* **The lift holds with real models:** raw-file RAG is stuck at 55-58% whichever model reads it
  (the stub gave 60%). Canon gives 90-97.5%, so the gap comes from the context, not model
  reasoning. A stronger model can't recover facts that retrieval never surfaced.
* **Baseline failures are mostly retrieval:** 9-12 of its 17-18 misses per model are
  "no answer" (aliases, lowercase or Arabic names, Slack mentions stored as user IDs), and 3-4 are
  stale values. Models do not rescue a bad context.
* **Canon's shared miss is Q34**, the mobile-vs-switchboard phone number (see above). All four
  models answer with the mobile; it comes back at confidence 0.46 with the switchboard as the
  alternative.
* **DeepSeek-V4-Pro's three extra Canon misses** are "unknown" on contract-value questions,
  where the right value was in the context. I re-ran two of them: Q03 (a Darija question about an
  Arabic-script name) reproduced as "unknown" after normal completion, with plenty of token
  budget left, and Q06 came back correct. So this is model variance on non-English phrasing, not
  an adapter problem.
* **Single runs, 40 questions:** one question is 2.5 points, so differences of one or two
  questions between models are noise. Models were chosen as the flagship tier by price from
  Baseten's catalog, with no tuning. Neither agent's prompt was tuned for any model.
* **Cost:** about 80 short calls per model (roughly 2-3K tokens each); the four runs together
  took about 10 minutes.

## Caveats

* The stub numbers are a deterministic regression check; the real-model table above is the
  headline.
* Questions, data and pipeline come from the same author, so the lift is an upper bound until it
  is reproduced on a customer's data with questions written by their team.
* The router's cue list was extended after the paraphrase questions were written (owner: "looks
  after", "s'occupe"; phone: "number", "dial"; address: "located"...), so routing on that set
  (30/30) is not independent evidence. When no cue matches, the Canon agent falls back to the full
  profile.
