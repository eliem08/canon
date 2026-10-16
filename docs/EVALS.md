# Eval harness (Milestone 5)

The sales proof: the same model answers the same 40 questions twice, once with naive retrieval
over the raw exports and once with Canon's MCP tools. The difference is what Canon adds.

```bash
uv run canon eval                              # stub model, offline, ~2 s (what CI runs)
uv run canon eval --seeds 10                   # plus 10 regenerated datasets (held-out check)
uv sync --extra claude && uv run canon eval --model claude    # real model (needs credentials)
uv run canon eval --model claude --model-id claude-opus-5-5 --caller salma.el.idrissi
```

Output: `out/eval_report.md` (+ `.json` with every answer and agent trace). The committed
copy is [`reports/eval_report.md`](reports/eval_report.md).

## Questions

`canon/evals/questions.py` derives 40 questions deterministically from the hidden ground
truth. They are written to `data/synthetic/ground_truth/eval_questions.json`.

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

Both agents use the same model, prompt and question router (`classify`). Only the context
differs.

* **Baseline:** BM25 over raw chunks (CRM rows, individual Slack messages, contract texts),
  top 5 chunks.
* **Canon:** links the customer by calling `get_customer` on the question's trailing spans and
  keeping the best match, then calls `find_contract_terms`, `who_owns` or `get_customer` over
  MCP and passes the structured result as context. It acts as `revops.admin` by default
  (`--caller` to change).

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

## Caveats

* The stub numbers are a deterministic regression check, not the headline. The headline should be
  a real-model run.
* Questions, data and pipeline come from the same author, so the lift is an upper bound until it
  is reproduced on a customer's data with questions written by their team.
* Entity linking relies on the customer mention ending the question. A real model would extract
  the name itself.
