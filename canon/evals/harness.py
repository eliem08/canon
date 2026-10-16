"""Run the before/after eval and render the markdown report.

The harness is the only place that reads the ground truth: it loads the questions and
grades answers, and it feeds the oracle agent. Baseline and Canon agents only see the
question text. Without a ground truth (a client's data with their own question file),
the oracle and the failure analysis by customer are skipped.
"""

from __future__ import annotations

import json
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

import anyio
from mcp import Client
from pydantic import BaseModel

from canon.evals.agents import BaselineAgent, CanonAgent, OracleAgent
from canon.evals.models import Model
from canon.evals.questions import QUESTION_TYPES, Question, build_questions, load_questions
from canon.evals.scoring import is_correct
from canon.evals.stats import mcnemar_exact, wilson
from canon.ingest import load_all
from canon.mcp_server import CallerDirectory, CanonService, ServiceConfig, build_server
from canon.models import SourceRecord
from canon.score import FactScoringConfig

AGENTS = ("baseline", "oracle", "canon")
AGENT_LABELS = {
    "baseline": "Baseline (BM25 over raw files)",
    "oracle": "Oracle retrieval (every raw record of the right customer)",
    "canon": "**Canon (MCP tools)**",
}


class Outcome(BaseModel):
    answer: str
    correct: bool
    failure: str | None = None  # stale_value | wrong_customer | no_answer | other
    trace: list[str] = []


class QuestionResult(BaseModel):
    question: Question
    outcomes: dict[str, Outcome]


class EvalRun(BaseModel):
    model: str
    caller: str
    as_of: date
    results: list[QuestionResult]
    agents: list[str] = list(AGENTS)
    questions_source: str = "synthetic"

    def accuracy(self, agent: str, qtype: str | None = None) -> float:
        rows = [r for r in self.results if qtype is None or r.question.type == qtype]
        return sum(r.outcomes[agent].correct for r in rows) / len(rows) if rows else 0.0

    def correct(self, agent: str) -> int:
        return sum(r.outcomes[agent].correct for r in self.results)


def _observed_values(records: list[SourceRecord], qtype: str) -> list:
    """Every value the sources assert for this question type (for failure analysis)."""
    values = []
    for r in records:
        if qtype in ("phone", "address"):
            values.append(getattr(r, qtype))
        values += [f.value for f in r.facts if f.field == qtype]
    return [v for v in values if v not in (None, "")]


def classify_failure(
    q: Question, answer: str, truth: dict | None, records: list[SourceRecord]
) -> str:
    """Why a wrong answer is wrong, using the ground truth and the raw source values."""
    from canon.evals.scoring import UNKNOWN
    from canon.resolve.normalize import fold

    if fold(answer).strip(" .") in UNKNOWN:
        return "no_answer"
    if truth is None or q.entity_id is None:
        return "other"
    own = [r for r in records if truth["records"].get(r.record_id) == q.entity_id]
    if any(is_correct(q.type, v, answer) for v in _observed_values(own, q.type)):
        return "stale_value"  # a real but outdated/superseded value of the right customer
    field = q.type
    for eid, entity in truth["entities"].items():
        if eid != q.entity_id and is_correct(q.type, entity[field], answer):
            return "wrong_customer"
    others = [r for r in records if truth["records"].get(r.record_id) != q.entity_id]
    if any(is_correct(q.type, v, answer) for v in _observed_values(others, q.type)):
        return "wrong_customer"
    return "other"


def resolve_questions(data_dir: Path, truth: dict | None, path: Path | None) -> tuple[list, str]:
    """The question set and where it came from: an explicit file, the dataset's committed
    `ground_truth/eval_questions.json`, or (last resort) generated from the ground truth."""
    if path is not None:
        return load_questions(path, truth), Path(path).name
    committed = data_dir / "ground_truth" / "eval_questions.json"
    if committed.exists():
        return load_questions(committed, truth), "ground_truth/eval_questions.json"
    if truth is None:
        raise SystemExit("no questions: pass a question file")
    return build_questions(truth), "generated from the ground truth"


async def _run_async(
    data_dir: Path,
    model: Model,
    caller: str,
    as_of: date,
    store_dir: Path,
    questions_path: Path | None = None,
) -> EvalRun:
    from canon.cli import build_store

    truth_path = data_dir / "ground_truth" / "ground_truth.json"
    truth = json.loads(truth_path.read_text("utf-8")) if truth_path.exists() else None
    questions, source = resolve_questions(data_dir, truth, questions_path)
    build_store(data_dir, store_dir, as_of)
    service = CanonService.from_store(
        store_dir / "canon.sqlite",
        CallerDirectory.from_file(data_dir / "identities.json"),
        ServiceConfig(facts=FactScoringConfig(as_of=as_of)),
    )
    records = load_all(data_dir)
    baseline = BaselineAgent(model, data_dir)
    oracle = OracleAgent(model, data_dir, truth["records"]) if truth else None
    results = []
    async with Client(build_server(service)) as client:
        canon = CanonAgent(model, client, caller)
        agents = [a for a in (baseline, oracle, canon) if a is not None]
        for q in questions:
            outcomes = {}
            for agent in agents:
                if agent is oracle:
                    res = await agent.run(q.question, q.entity_id)
                else:
                    res = await agent.run(q.question)
                ok = is_correct(q.type, q.expected, res.answer)
                outcomes[agent.name] = Outcome(
                    answer=res.answer,
                    correct=ok,
                    failure=None if ok else classify_failure(q, res.answer, truth, records),
                    trace=res.trace,
                )
            results.append(QuestionResult(question=q, outcomes=outcomes))
    return EvalRun(
        model=model.name,
        caller=caller,
        as_of=as_of,
        results=results,
        agents=[a.name for a in agents],
        questions_source=source,
    )


def run_eval(
    data_dir: Path,
    model: Model,
    caller: str = "revops.admin",
    as_of: date = date(2026, 10, 1),
    store_dir: Path | None = None,
    questions: Path | None = None,
) -> EvalRun:
    args = (Path(data_dir), model, caller, as_of)
    if store_dir is not None:
        return anyio.run(_run_async, *args, Path(store_dir), questions)
    with tempfile.TemporaryDirectory() as tmp:
        return anyio.run(_run_async, *args, Path(tmp), questions)


def seed_sweep(seeds: range, model: Model, caller: str = "revops.admin") -> list[tuple]:
    """Regenerate the dataset with other seeds and rerun the eval (held-out check)."""
    from canon.synth import generate

    out = []
    for seed in seeds:
        with tempfile.TemporaryDirectory() as d:
            generate(Path(d), seed=seed)
            run = run_eval(Path(d), model, caller)
            out.append((seed, *(run.accuracy(a) for a in run.agents)))
    return out


FAILURE_LABELS = {
    "stale_value": "stale / superseded value of the right customer",
    "wrong_customer": "value belonging to a different customer",
    "no_answer": "no answer found",
    "other": "other",
}


def _row(run: EvalRun, agent: str) -> str:
    n, k = len(run.results), run.correct(agent)
    lo, hi = wilson(k, n)
    return f"| {AGENT_LABELS[agent]} | {k}/{n} | {k / n:.1%} | {lo:.0%}–{hi:.0%} |"


def render_report(
    run: EvalRun, sweep: list[tuple] | None = None, repeats: list[EvalRun] | None = None
) -> str:
    n = len(run.results)
    agents = run.agents
    b, c = run.accuracy("baseline"), run.accuracy("canon")
    only_b = sum(r.outcomes["baseline"].correct and not r.outcomes["canon"].correct
                 for r in run.results)  # fmt: skip
    only_c = sum(r.outcomes["canon"].correct and not r.outcomes["baseline"].correct
                 for r in run.results)  # fmt: skip
    types = {t: sum(r.question.type == t for r in run.results) for t in QUESTION_TYPES}
    lines = [
        "# Canon eval: agent accuracy on raw data vs. on Canon",
        "",
        f"- Questions: {n} from `{run.questions_source}` "
        f"({', '.join(f'{k} {v}' for k, v in types.items() if v)})",
        f"- Model: `{run.model}` (same model and prompt for every agent)",
        f"- Canon caller: `{run.caller}`; facts as of {run.as_of}",
        "- Baseline: BM25 keyword retrieval over raw CRM rows, Slack messages and contract "
        "texts (top 5 chunks)",
    ]
    if "oracle" in agents:
        lines.append(
            "- Oracle: every raw chunk of the right customer and nothing else (perfect "
            "retrieval, from the answer key). It shows what raw data supports at best."
        )
    lines += [
        "- Canon: MCP tools (`get_customer` for linking any span of the question, then "
        "`find_contract_terms` / `who_owns` / `get_customer`)",
        "",
        "## Overall",
        "",
        "| Agent | Correct | Accuracy | 95% CI (Wilson) |",
        "|---|---|---|---|",
        *[_row(run, a) for a in agents],
        "",
        f"Lift, Canon vs. baseline: **{(c - b) * 100:+.1f} pts**. On the same questions, Canon "
        f"alone is right on {only_c} and the baseline alone on {only_b} "
        f"(exact McNemar p = {mcnemar_exact(only_c, only_b):.2g}).",
    ]
    if "oracle" in agents:
        o = run.accuracy("oracle")
        lines.append(
            f"Canon vs. oracle retrieval: **{(c - o) * 100:+.1f} pts**. That is the part of the "
            "lift that better retrieval alone would not give."
        )
    if repeats:
        all_runs = [run, *repeats]
        lines += ["", f"Repeated runs ({len(all_runs)}):", "", "| Agent | " + " | ".join(
            f"run {i + 1}" for i in range(len(all_runs))) + " | mean |",
            "|---|" + "---|" * (len(all_runs) + 1)]  # fmt: skip
        for a in agents:
            accs = [r.accuracy(a) for r in all_runs]
            lines.append(
                f"| {a} | "
                + " | ".join(f"{x:.1%}" for x in accs)
                + f" | {sum(accs) / len(accs):.1%} |"
            )
    lines += [
        "",
        "## Accuracy by question type",
        "",
        "| Type | Questions | " + " | ".join(agents) + " |",
        "|---|---|" + "---|" * len(agents),
    ]
    for qtype, k in types.items():
        if k:
            accs = " | ".join(f"{run.accuracy(a, qtype):.0%}" for a in agents)
            lines.append(f"| {qtype} | {k} | {accs} |")
    if sweep:
        bs, cs = [x[1] for x in sweep], [x[-1] for x in sweep]
        lines += [
            "",
            f"Held-out check: regenerating the dataset with seeds {sweep[0][0]}–{sweep[-1][0]} "
            f"gives baseline **{sum(bs) / len(bs):.1%}** (range {min(bs):.0%}–{max(bs):.0%}) vs. "
            f"Canon **{sum(cs) / len(cs):.1%}** (range {min(cs):.0%}–{max(cs):.0%}).",
        ]
    lines += [
        "",
        "## Failure analysis",
        "",
        "| Failure | " + " | ".join(agents) + " |",
        "|---|" + "---|" * len(agents),
    ]
    counts = {a: Counter(r.outcomes[a].failure for r in run.results) for a in agents}
    for key, label in FAILURE_LABELS.items():
        lines.append(f"| {label} | " + " | ".join(str(counts[a][key]) for a in agents) + " |")
    styles = sorted({r.question.mention_style for r in run.results})
    lines += [
        "",
        "Accuracy by how the customer was named:",
        "",
        "| Mention style | Questions | " + " | ".join(agents) + " |",
        "|---|---|" + "---|" * len(agents),
    ]
    for style in styles:
        rows = [r for r in run.results if r.question.mention_style == style]
        accs = " | ".join(
            f"{sum(r.outcomes[a].correct for r in rows) / len(rows):.0%}" for a in agents
        )
        lines.append(f"| {style} | {len(rows)} | {accs} |")
    lines += [
        "",
        "### Every miss",
        "",
        "| Q | Question | Expected | " + " | ".join(agents) + " |",
        "|---|---|---|" + "---|" * len(agents),
    ]
    for r in run.results:
        if all(o.correct for o in r.outcomes.values()):
            continue

        def cell(agent: str, r=r) -> str:
            o = r.outcomes[agent]
            return "✓" if o.correct else f"✗ `{o.answer}` ({o.failure})"

        lines.append(
            f"| {r.question.id} | {r.question.question} | `{r.question.expected}` | "
            + " | ".join(cell(a) for a in agents)
            + " |"
        )
    lines += [
        "",
        "## Reading this report",
        "",
        "- With the stub model, the answer is whatever the context literally contains first. "
        "This measures what each agent's *context* supports, not model reasoning. Run with a "
        "real model (`canon eval --model claude`) for the end-to-end number; the stub is a "
        "deterministic CI check. The stub's *oracle* number is not meaningful: given every "
        "record of a customer, it answers with the first value it finds, which is often the "
        "stale one. A real model weighs dates and sources.",
        "- Confidence intervals are per agent; the McNemar test is the right comparison "
        "because both agents answer the same questions.",
        "- The synthetic data and the questions were written by the same team that "
        "built Canon. Treat the lift as an upper bound until reproduced on a customer's data "
        "with the customer's questions.",
    ]
    return "\n".join(lines) + "\n"
