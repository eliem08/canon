import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from canon.evals import ClaudeModel, StubModel, render_report, run_eval
from canon.evals.agents import BM25, CharNgramIndex, candidate_spans, raw_chunks, readable_chunks
from canon.evals.models import SYSTEM_PROMPT
from canon.evals.questions import QUESTION_TYPES, build_questions, load_questions
from canon.evals.scoring import classify, is_correct
from canon.evals.stats import mcnemar_exact, wilson

DATA = Path(__file__).resolve().parents[1] / "data" / "synthetic"
PARAPHRASES = DATA.parent / "eval" / "paraphrase_questions.json"
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
    report = render_report(run, sweep=[(1, 0.5, 0.6, 1.0), (2, 0.4, 0.5, 0.95)])
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


def test_openai_compatible_adapter_reads_key_from_env_only(monkeypatch):
    from canon.evals import OpenAICompatibleModel

    sent = {}

    def fake_post(url, payload, headers, timeout):
        sent.update(url=url, payload=payload, headers=headers)
        content = "<think>check the contract</think>1426000 MAD"
        return {"choices": [{"message": {"content": content}}]}

    model = OpenAICompatibleModel.preset("baseten", "some/model", post=fake_post)
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="BASETEN_API_KEY"):
        model.answer("q", "c")
    monkeypatch.setenv("BASETEN_API_KEY", "test-key")
    assert model.answer("What is the value?", "ctx") == "1426000 MAD"
    assert sent["url"] == "https://inference.baseten.co/v1/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer test-key"
    assert sent["payload"]["model"] == "some/model"
    assert sent["payload"]["messages"][0]["content"] == SYSTEM_PROMPT
    assert "test-key" not in json.dumps(sent["payload"])


def test_openai_compatible_adapter_with_proxy_injected_credentials(monkeypatch):
    from canon.evals import OpenAICompatibleModel

    sent = {}

    def fake_post(url, payload, headers, timeout):
        sent["headers"] = headers
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    model = OpenAICompatibleModel.preset("baseten", "m", post=fake_post, proxy_credentials=True)
    assert model.answer("q", "c") == "ok" and "Authorization" not in sent["headers"]


def test_openai_compatible_adapter_requires_model_id():
    from canon.evals import OpenAICompatibleModel

    with pytest.raises(ValueError):
        OpenAICompatibleModel.preset("baseten", None)


def test_openai_compatible_adapter_retries_transient_errors_only(monkeypatch):
    import urllib.error

    from canon.evals import OpenAICompatibleModel

    monkeypatch.setenv("BASETEN_API_KEY", "k")
    calls = []

    def flaky(url, payload, headers, timeout):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.HTTPError(url, 502, "Bad Gateway", {}, None)
        return {"choices": [{"message": {"content": "ok"}}]}

    model = OpenAICompatibleModel.preset("baseten", "m", post=flaky, backoff=0)
    assert model.answer("q", "c") == "ok" and len(calls) == 3

    def forbidden(url, payload, headers, timeout):
        calls.append(1)
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    calls.clear()
    model = OpenAICompatibleModel.preset("baseten", "m", post=forbidden, backoff=0)
    with pytest.raises(urllib.error.HTTPError):
        model.answer("q", "c")
    assert len(calls) == 1  # client errors are not retried


# ---------------------------------------------------------------- eval v2


def test_question_files_load_and_fill_expected_from_truth(tmp_path):
    committed = load_questions(DATA / "ground_truth" / "eval_questions.json")
    assert committed == build_questions(TRUTH)
    para = load_questions(PARAPHRASES, TRUTH)
    assert len(para) >= 30 and all(q.expected not in (None, "") for q in para)
    client = tmp_path / "client.json"
    client.write_text(
        json.dumps([{"id": "C1", "type": "owner", "question": "x?", "expected": "A"}])
    )
    assert load_questions(client)[0].entity_id is None
    with pytest.raises(ValueError):
        load_questions(PARAPHRASES)  # needs the ground truth for expected answers


def test_candidate_spans_find_mid_sentence_names():
    spans = candidate_spans("Before I call Atlas Logistique tomorrow, who owns that account?", 6)
    assert "Atlas Logistique" in spans
    assert not any(s.split()[0].lower() in {"before", "who"} for s in spans)
    assert "Nour Packaging" in candidate_spans("Where are Nour Packaging's offices?", 6)


def test_stats():
    lo, hi = wilson(39, 40)
    assert 0.86 < lo < 0.88 and hi > 0.99
    assert wilson(0, 0) == (0.0, 1.0)
    assert mcnemar_exact(16, 1) < 0.001 and mcnemar_exact(3, 3) == 1.0


def test_oracle_is_in_the_run(run):
    assert run.agents == ["baseline", "hybrid", "oracle", "canon"]
    assert all(o.context_chars > 0 for r in run.results for o in r.outcomes.values())
    assert all("oracle" in r.outcomes for r in run.results)
    assert all(r.outcomes["oracle"].trace[0].startswith("oracle: ") for r in run.results)


def test_paraphrase_questions_link_mid_sentence():
    para = run_eval(DATA, StubModel(), as_of=date(2026, 10, 1), questions=PARAPHRASES)
    linked = [r for r in para.results if any("linked to" in t for t in r.outcomes["canon"].trace)]
    assert len(linked) == len(para.results)
    assert para.accuracy("canon") >= 0.9 and para.accuracy("canon") > para.accuracy("baseline")


def test_report_has_ci_and_mcnemar(run):
    report = render_report(run, repeats=[run])
    assert "95% CI" in report and "McNemar" in report and "Repeated runs (2)" in report


def test_strong_baseline_prepares_chunks_like_a_careful_engineer():
    chunks = readable_chunks(DATA)
    slack = [t for loc, t in chunks if loc.startswith("slack:")]
    assert slack and not any("<@U" in t for t in slack)
    assert all(t.startswith("#") and t.split(" ")[1][:2] == "20" for t in slack)
    assert len(chunks) == len(raw_chunks(DATA))


def test_fuzzy_index_tolerates_typos_and_case():
    index = CharNgramIndex(["Atlas Logistique SARL contrat", "Zitoun Cosmetics", "Fennec Software"])
    assert index.search("atlas logsitique", 1) == [0]


def test_report_quotes_canon_against_the_strong_baseline(run):
    report = render_report(run)
    assert "Canon vs. hybrid" in report and "Context read" in report
    assert run.accuracy("canon") > run.accuracy("hybrid") >= run.accuracy("baseline") - 0.05


def test_client_hosted_model_needs_no_key(monkeypatch):
    from canon.evals.models import OpenAICompatibleModel

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    sent = {}

    def post(url, payload, headers, timeout):
        sent.update(url=url, headers=headers)
        return {"choices": [{"message": {"content": "461000"}}]}

    m = OpenAICompatibleModel("local", "http://llm.internal:8000/v1/", "OPENAI_API_KEY",
                              post=post, require_key=False)  # fmt: skip
    assert m.answer("q", "c") == "461000"
    assert sent == {"url": "http://llm.internal:8000/v1/chat/completions", "headers": {}}


def test_raw_file_rag_reads_text_a_sales_rep_may_not_see():
    as_rep = run_eval(DATA, StubModel(), caller="salma.el.idrissi", as_of=date(2026, 10, 1))
    assert as_rep.leaky("canon") == 0
    assert as_rep.leaky("hybrid") > len(as_rep.results) / 2
    report = render_report(as_rep)
    assert "Answers that read restricted text" in report


def test_full_access_caller_has_no_restricted_reads(run):
    assert all(run.leaky(a) == 0 for a in run.agents)
