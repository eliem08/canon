"""Message-level fact extraction: hand-written dev/held-out set, LLM validation, lineage."""

import json
from pathlib import Path

import pytest

from canon.ingest import load_all
from canon.ingest.extract import extract_message, validate_llm
from canon.ingest.parsing import IssueLog

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "slack_messages.json").read_text(encoding="utf-8")
)
USERS = FIXTURE["users"]
DATA = Path(__file__).resolve().parents[1] / "data" / "synthetic"


def _same(field, got, expected) -> bool:
    if field == "contract_value":
        return abs(float(got) - float(expected)) < 1e-6
    return got == expected


def _score(split: str, llm=None) -> dict:
    tp = fp = fn = neg = neg_fp = 0
    for m in FIXTURE["messages"]:
        if m["split"] != split:
            continue
        got = {e.field: e.value for e in extract_message(m["text"], USERS, IssueLog("t"), llm=llm)}
        exp = m["expect"]
        neg += not exp
        neg_fp += bool(got) and not exp
        for k in set(got) | set(exp):
            if k in got and k in exp and _same(k, got[k], exp[k]):
                tp += 1
            else:
                fp += k in got
                fn += k in exp
    p, r = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    return {"p": p, "r": r, "f1": 2 * p * r / max(p + r, 1e-9), "neg_fp": neg_fp / neg}


def test_fixture_is_big_enough():
    assert sum(m["split"] == "heldout" for m in FIXTURE["messages"]) >= 60


@pytest.mark.parametrize("split", ["dev", "heldout"])
def test_extraction_quality(split):
    s = _score(split)
    assert s["f1"] >= 0.85, s
    assert s["neg_fp"] < 0.05, s  # messages that assert nothing must yield nothing


class FakeLLM:
    def __init__(self, reply: dict) -> None:
        self.reply = json.dumps(reply)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return f"Sure! {self.reply}"


def test_llm_values_must_appear_in_the_message():
    text = "<@U08> est désormais l'interlocutrice principale côté commercial pour Medina Pharm"
    log = IssueLog("t")
    llm = FakeLLM({"owner": "Leila Bennani", "contract_value": 600000, "renewal_date": None})
    found = {e.field: e.value for e in extract_message(text, USERS, log, llm=llm)}
    assert found == {"owner": "Leila Bennani"}  # the invented amount is dropped
    assert [i.reason for i in log.items] == ["llm_value_not_in_source"]


def test_llm_owner_must_be_a_mentioned_known_user():
    kept, rejected = validate_llm(
        {"owner": "Rachid Amrani"}, "Rachid gère Zitoun", USERS, "MAD", True
    )
    assert kept == [] and rejected == ["owner"]
    kept, rejected = validate_llm({"owner": "Omar Fassi"}, "géré par <@U03>", USERS, "MAD", True)
    assert kept == [] and rejected == ["owner"]


def test_llm_dates_and_amounts_are_checked_by_the_parsers():
    text = "Renouvellement tacite au 1er février 2028, 2,6 M MAD/an"
    kept, rejected = validate_llm(
        {"renewal_date": "2028-02-01", "contract_value": 2_600_000}, text, USERS, "MAD", True
    )
    assert {e.field for e in kept} == {"renewal_date", "contract_value"} and not rejected
    kept, rejected = validate_llm(
        {"renewal_date": "2028-01-02", "contract_value": 260_000}, text, USERS, "MAD", True
    )
    assert kept == [] and set(rejected) == {"renewal_date", "contract_value"}


def test_llm_is_only_asked_when_rules_leave_a_field_empty():
    text = "Nouveau contrat Zitoun: 820k MAD/an, renouvellement le 01/09/2028, owner <@U07>"
    llm = FakeLLM({})
    extract_message(text, USERS, IssueLog("t"), llm=llm)
    assert llm.prompts == []


@pytest.fixture(scope="module")
def records():
    return {r.record_id: r for r in load_all(DATA)}


def test_slack_facts_cite_their_message(records):
    slack = [f for r in records.values() if r.source == "slack" for f in r.facts]
    assert slack and all("#ts=" in f.source_ref and f.quote for f in slack)


def test_contract_facts_cite_page_and_line(records):
    contract = [f for r in records.values() if r.source == "contract" for f in r.facts]
    assert contract and all(":L" in f.source_ref and "#p1" in f.source_ref for f in contract)
    value = next(f for f in contract if f.field == "contract_value")
    assert any(ch.isdigit() for ch in value.quote)
