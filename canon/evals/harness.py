"""Run the before/after eval and render the markdown report.

The harness is the only place that reads the ground truth: it builds the questions
from it and grades answers against it. Agents only see the question text.
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

from canon.evals.agents import BaselineAgent, CanonAgent
from canon.evals.models import Model
from canon.evals.questions import QUESTION_TYPES, Question, build_questions
from canon.evals.scoring import is_correct
from canon.ingest import load_all
from canon.mcp_server import CallerDirectory, CanonService, ServiceConfig, build_server
from canon.models import SourceRecord
from canon.score import FactScoringConfig

AGENTS = ("baseline", "canon")


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

    def accuracy(self, agent: str, qtype: str | None = None) -> float:
        rows = [r for r in self.results if qtype is None or r.question.type == qtype]
        return sum(r.outcomes[agent].correct for r in rows) / len(rows) if rows else 0.0


def _observed_values(records: list[SourceRecord], qtype: str) -> list:
    """Every value the sources assert for this question type (for failure analysis)."""
    values = []
    for r in records:
        if qtype in ("phone", "address"):
            values.append(getattr(r, qtype))
        values += [f.value for f in r.facts if f.field == qtype]
    return [v for v in values if v not in (None, "")]


def classify_failure(q: Question, answer: str, truth: dict, records: list[SourceRecord]) -> str:
    """Why a wrong answer is wrong, using the ground truth and the raw source values."""
    from canon.evals.scoring import UNKNOWN
    from canon.resolve.normalize import fold

    if fold(answer).strip(" .") in UNKNOWN:
        return "no_answer"
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


async def _run_async(
    data_dir: Path, model: Model, caller: str, as_of: date, store_dir: Path
) -> EvalRun:
    from canon.cli import build_store

    truth = json.loads((data_dir / "ground_truth" / "ground_truth.json").read_text("utf-8"))
    questions = build_questions(truth)
    build_store(data_dir, store_dir, as_of)
    service = CanonService.from_store(
        store_dir / "canon.sqlite",
        CallerDirectory.from_file(data_dir / "identities.json"),
        ServiceConfig(facts=FactScoringConfig(as_of=as_of)),
    )
    records = load_all(data_dir)
    baseline = BaselineAgent(model, data_dir)
    results = []
    async with Client(build_server(service)) as client:
        canon = CanonAgent(model, client, caller)
        for q in questions:
            outcomes = {}
            for agent in (baseline, canon):
                res = await agent.run(q.question)
                ok = is_correct(q.type, q.expected, res.answer)
                outcomes[agent.name] = Outcome(
                    answer=res.answer,
                    correct=ok,
                    failure=None if ok else classify_failure(q, res.answer, truth, records),
                    trace=res.trace,
                )
            results.append(QuestionResult(question=q, outcomes=outcomes))
    return EvalRun(model=model.name, caller=caller, as_of=as_of, results=results)


def run_eval(
    data_dir: Path,
    model: Model,
    caller: str = "revops.admin",
    as_of: date = date(2026, 10, 1),
    store_dir: Path | None = None,
) -> EvalRun:
    if store_dir is not None:
        return anyio.run(_run_async, Path(data_dir), model, caller, as_of, Path(store_dir))
    with tempfile.TemporaryDirectory() as tmp:
        return anyio.run(_run_async, Path(data_dir), model, caller, as_of, Path(tmp))


def seed_sweep(seeds: range, model: Model, caller: str = "revops.admin") -> list[tuple]:
    """Regenerate the dataset with other seeds and rerun the eval (held-out check)."""
    from canon.synth import generate

    out = []
    for seed in seeds:
        with tempfile.TemporaryDirectory() as d:
            generate(Path(d), seed=seed)
            run = run_eval(Path(d), model, caller)
            out.append((seed, run.accuracy("baseline"), run.accuracy("canon")))
    return out


FAILURE_LABELS = {
    "stale_value": "stale / superseded value of the right customer",
    "wrong_customer": "value belonging to a different customer",
    "no_answer": "no answer found",
    "other": "other",
}


def render_report(run: EvalRun, sweep: list[tuple] | None = None) -> str:
    n = len(run.results)
    b, c = run.accuracy("baseline"), run.accuracy("canon")
    lines = [
        "# Canon eval: agent accuracy on raw data vs. on Canon",
        "",
        f"- Questions: {n} ({', '.join(f'{k} {v}' for k, v in QUESTION_TYPES.items())}), "
        "mixed EN/FR/Darija phrasing; customers named by alias, Arabic script, typos, "
        "legal suffixes",
        f"- Model: `{run.model}` (same model and prompt for both agents)",
        f"- Canon caller: `{run.caller}`; facts as of {run.as_of}",
        "- Baseline: BM25 keyword retrieval over raw CRM rows, Slack messages and contract "
        "texts (top 5 chunks)",
        "- Canon: MCP tools (`get_customer` for linking, then `find_contract_terms` / "
        "`who_owns` / `get_customer`)",
        "",
        "## Overall",
        "",
        "| Agent | Correct | Accuracy |",
        "|---|---|---|",
        f"| Baseline (raw files) | {round(b * n)}/{n} | {b:.1%} |",
        f"| **Canon (MCP tools)** | **{round(c * n)}/{n}** | **{c:.1%}** |",
        f"| Lift | | **{(c - b) * 100:+.1f} pts** |",
        "",
        "## Accuracy by question type",
        "",
        "| Type | Questions | Baseline | Canon |",
        "|---|---|---|---|",
    ]
    for qtype in QUESTION_TYPES:
        k = sum(r.question.type == qtype for r in run.results)
        lines.append(
            f"| {qtype} | {k} | {run.accuracy('baseline', qtype):.0%} | "
            f"{run.accuracy('canon', qtype):.0%} |"
        )
    if sweep:
        bs, cs = [b for _, b, _ in sweep], [c for *_, c in sweep]
        lines += [
            "",
            f"Held-out check: regenerating the dataset with seeds {sweep[0][0]}–{sweep[-1][0]} "
            f"gives baseline **{sum(bs) / len(bs):.1%}** (range {min(bs):.0%}–{max(bs):.0%}) vs. "
            f"Canon **{sum(cs) / len(cs):.1%}** (range {min(cs):.0%}–{max(cs):.0%}).",
        ]
    lines += ["", "## Failure analysis", "", "| Failure | Baseline | Canon |", "|---|---|---|"]
    counts = {a: Counter(r.outcomes[a].failure for r in run.results) for a in AGENTS}
    for key, label in FAILURE_LABELS.items():
        lines.append(f"| {label} | {counts['baseline'][key]} | {counts['canon'][key]} |")
    styles = sorted({r.question.mention_style for r in run.results})
    lines += [
        "",
        "Accuracy by how the customer was named:",
        "",
        "| Mention style | Questions | Baseline | Canon |",
        "|---|---|---|---|",
    ]
    for style in styles:
        rows = [r for r in run.results if r.question.mention_style == style]
        acc = {a: sum(r.outcomes[a].correct for r in rows) / len(rows) for a in AGENTS}
        lines.append(f"| {style} | {len(rows)} | {acc['baseline']:.0%} | {acc['canon']:.0%} |")
    lines += ["", "### Every miss", "", "| Q | Question | Expected | Baseline | Canon |"]
    lines.append("|---|---|---|---|---|")
    for r in run.results:
        if all(o.correct for o in r.outcomes.values()):
            continue

        def cell(agent: str, r=r) -> str:
            o = r.outcomes[agent]
            return "✓" if o.correct else f"✗ `{o.answer}` ({o.failure})"

        lines.append(
            f"| {r.question.id} | {r.question.question} | `{r.question.expected}` | "
            f"{cell('baseline')} | {cell('canon')} |"
        )
    lines += [
        "",
        "## Reading this report",
        "",
        "- With the stub model, the answer is whatever the retrieved context literally "
        "contains first. This measures what each agent's *context* supports, not model "
        "reasoning. Run with a real model (`canon eval --model claude`) for the end-to-end "
        "number; the stub is a deterministic CI check.",
        "- The synthetic data and the questions were generated by the same team that "
        "built Canon. Treat the lift as an upper bound until reproduced on a customer's data.",
    ]
    return "\n".join(lines) + "\n"
