import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from canon.evals import ClaudeModel, StubModel, render_report, run_eval
from canon.evals.agents import BM25, raw_chunks
from canon.evals.models import SYSTEM_PROMPT
from canon.evals.questions import QUESTION_TYPES, build_questions
from canon.evals.scoring import classify, is_correct

DATA = Path(__file__).resolve().parents[1] / "data" / "synthetic"
TRUTH = json.loads((DATA / "ground_truth" / "ground_truth.json").read_text(encoding="utf-8"))


def test_forty_questions_deterministic_and_committed():
    questions = build_questions(TRUTH)
    assert len(questions) == 40 == sum(QUESTION_TYPES.values())
    assert build_questions(TRUTH) == questions
    committed = json.loads((DATA / "ground_truth" / "eval_questions.json").read_text("utf-8"))
    assert [q.model_dump() for q in questions] == committed
    for q in questions:
        assert classify(q.question) == q.type, q.question
        assert q.question.rstrip(" ?").endswith(q.mention)


@pytest.mark.parametrize(
    ("qtype", "expected", "answer", "ok"),
    [
        ("contract_value", 1426000, "1 426 000 MAD", True),
        ("contract_value", 1426000, "The annual value is 1,426,000 MAD (renews 2028).", True),
        ("contract_value", 1426000, "1085000", False),
        ("renewal_date", "2028-03-01", "01/03/2028", True),
        ("renewal_date", "2028-03-01", "It renews on March 1, 2028.", True),
        ("renewal_date", "2028-03-01", "1er mars 2028", True),
        ("renewal_date", "2028-03-01", "2027-03-01", False),
        ("owner", "Salma El Idrissi", "The owner is Salma El Idrissi.", True),
        ("owner", "Salma El Idrissi", "Karim Tazi", False),
        ("phone", "+212522123456", "05 22 12 34 56", True),
        ("phone", "+212522123456", "+212661000000", False),
        ("address", "21 Avenue Hassan II", "21, Av. Hassan II, Agadir", True),
        ("address", "21 Avenue Hassan II", "Port de Dakhla", False),
        ("owner", "Salma El Idrissi", "unknown", False),
    ],
)
def test_grading(qtype, expected, answer, ok):
    assert is_correct(qtype, expected, answer) is ok


def test_baseline_retrieval_never_reads_ground_truth():
    locators = [loc for loc, _ in raw_chunks(DATA)]
    assert locators and not any("ground_truth" in loc or "identities" in loc for loc in locators)
    index = BM25(["atlas logistique contrat", "zitoun cosmetics"])
    assert index.search("contrat atlas", 2) == [0]


@pytest.fixture(scope="module")
def run():
    return run_eval(DATA, StubModel(), as_of=date(2026, 10, 1))


def test_canon_beats_baseline_with_stub_model(run):
    assert len(run.results) == 40
    assert run.accuracy("canon") >= 0.9
    assert run.accuracy("canon") - run.accuracy("baseline") >= 0.2
    for r in run.results:
        for o in r.outcomes.values():
            assert o.correct == (o.failure is None)


def test_report_has_required_sections(run):
    report = render_report(run, sweep=[(1, 0.5, 1.0), (2, 0.4, 0.95)])
    for heading in ("## Overall", "## Accuracy by question type", "## Failure analysis"):
        assert heading in report
    assert "Held-out check" in report and "Every miss" in report


def test_claude_adapter_request_shape():
    calls = {}

    class FakeMessages:
        def create(self, **kwargs):
            calls.update(kwargs)
            block = SimpleNamespace(type="text", text="2028-03-01")
            return SimpleNamespace(stop_reason="end_turn", content=[block])

    client = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages()))
    model = ClaudeModel(client=client)
    assert model.answer("When does X renew?", "ctx") == "2028-03-01"
    assert calls["model"] == "claude-opus-5-5" and calls["system"] == SYSTEM_PROMPT
    assert calls["fallbacks"] == "default" and calls["output_config"] == {"effort": "low"}
    assert "ctx" in calls["messages"][0]["content"]


def test_claude_adapter_refusal_is_unknown():
    class Refusing:
        def create(self, **kwargs):
            return SimpleNamespace(stop_reason="refusal", content=[])

    client = SimpleNamespace(beta=SimpleNamespace(messages=Refusing()))
    assert ClaudeModel(client=client).answer("q", "c") == "unknown"
