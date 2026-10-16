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
* **Strong RAG (`hybrid`):** what a careful engineer would build without Canon. It runs BM25 plus
  fuzzy character-trigram retrieval and queries with the whole question and every candidate customer
  span (the same span heuristic Canon's linker uses). Results are merged by reciprocal-rank fusion and
  the top 10 chunks are kept. Slack `<@U..>` mentions are replaced with names and every message is
  dated.
* **Oracle:** every raw chunk of the question's true customer, taken from the answer key, and
  nothing else. This is perfect retrieval. Whatever it still gets wrong comes from the raw data
  itself: stale CRM values, superseded contracts, owner changes buried in chat.
* **Canon:** links the customer by probing `get_customer` with every span of up to 6 words that
  doesn't start or end with a function word, keeping the best match (on a tie, the longer span).
  It then calls `find_contract_terms`, `who_owns` or `get_customer` over MCP, according to the
  question type the wording points to, or `get_customer` (every field) when the wording is unclear.
  It passes the structured result as context. It acts as `revops.admin` by default (`--caller` to
  change).

**Permissions:** each agent reports which source records reached the model. The report counts the
answers whose context included a record the caller may not read. Raw-file agents ignore
permissions; Canon filters before scoring.

**Statistics:** each accuracy has a 95% Wilson interval. Canon vs. each other agent is compared with an
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

## Results with real models (Baseten, eval v2.1, 2026-10-16)

Four open models, temperature 0, one run each, the same prompt for every agent. Full tables per model and
view are in [`reports/eval_summary.md`](reports/eval_summary.md) (regenerate with
`uv run python scripts/eval_summary.py`). Per-question answers are in each `reports/eval_*.json`.

| View | Baseline (BM25) | **Strong RAG** | Oracle | **Canon** | Canon vs strong RAG | Answers that read restricted text (RAG / Canon) | Context per answer (RAG / Canon) |
|---|---|---|---|---|---|---|---|
| 40 synthetic questions, full access | 55–58% | **92.5%** | 92.5–95% | **97.5%** | +5 pts, p = 0.5 (all 4 models) | 0 / 0 | 3.7k / **1.3k** chars |
| 30 hand-written questions, full access | 70–73% | **93–97%** | 90–93% | **96.7%** | 0 to +3.3 pts, p = 1 | 0 / 0 | 3.7k / **1.4k** |
| 40 synthetic questions, **as a sales rep** | 55–58% | **92.5%** | 92.5–95% | **82.5–85%** | −7.5 to −10 pts, p ≥ 0.22 | **35/40 / 0/40** | 3.7k / **0.9k** |

These numbers are from the run with compact tool responses (`fields` filter, locators listed once). The
earlier run with full responses (7.2k characters per answer) gave the same Canon accuracy within one
question per model.

### What this says, plainly

1. **Against a well-built RAG, Canon is not more accurate on this benchmark.** Canon beats keyword
   retrieval by 35–42 points (p < 1e-4). Strong RAG, though, gets within 0–5 points of Canon, and
   every difference is far from significant. Strong RAG is what a careful engineer builds without
   Canon: fuzzy and multi-query retrieval, Slack mentions resolved to names, messages dated.
   **The "+40 points" claim only holds against a weak baseline, so it should not be made.**
2. **Where Canon differs is permissions.** Asked as a sales rep, RAG over the raw export put
   contract text the rep may not read into **35 of 40** answers; perfect retrieval did so in all 40.
   Canon did so in **0**. Its accuracy is lower in that view (82.5–85%) because some correct answers
   exist only in legal-only contracts. That is the permission model working, and the grading against
   full-access truth counts it as a miss.
3. **Canon reads less.** With compact responses and the `fields` filter, Canon gives the model
   1.3k characters per answer, against 3.7k for strong RAG, at the same or better accuracy. Before
   compaction it was 7.2k. The dataset is small, so how RAG behaves with long histories is still
   untested.
4. **What is still Canon's alone:** typed answers with confidence, conflicts and alternatives;
   per-fact citations; the audit report (stale CRM values, duplicates, quarantine); identity and
   permission enforcement; and an audit log. These are product properties, and accuracy on 40
   synthetic questions doesn't measure them.

### Pitch implication (founder decision)
Sell the **audit and the permission-safe layer**, not an accuracy lift: "your agent can be as accurate
as good RAG *without* reading what the user may not see, and here is what's wrong in your data." Re-test
the accuracy claim on a client's data and questions, where histories are longer and names messier.

## Results (stub model, CI)

`reports/eval_report.md` (40 questions, with held-out seeds), `reports/eval_paraphrase.md`
(30 hand-written) and `reports/eval_sales.md` (as a sales rep).

| | Baseline | Strong RAG | Canon |
|---|---|---|---|
| 40 synthetic questions | 60.0% | 65.0% | 97.5% |
| 30 hand-written questions | 63.3% | 76.7% | 96.7% |

Held-out seeds 1–10: baseline 45.8%, Canon 97.2%. The stub takes the first value it finds, so it
understates every raw-file agent (strong RAG gets 65% with the stub and 92.5% with real models). It is a
deterministic regression check, not the headline.

## Caveats

* The stub numbers are a deterministic regression check. The real-model tables are the headline,
  and the strong-RAG column is the honest frame for them.
* Questions, data and pipeline come from the same author, so the lift is an upper bound until it
  is reproduced on a customer's data with questions written by their team.
* The router's cue list was extended after the paraphrase questions were written (owner: "looks
  after", "s'occupe"; phone: "number", "dial"; address: "located"...), so routing on that set
  (30/30) is not independent evidence. When no cue matches, the Canon agent falls back to the full
  profile.
