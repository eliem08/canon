from datetime import date

import pytest

from canon.models import Fact, SourceRecord
from canon.score import FactScoringConfig, authority, freshness, score_entity, score_field

AS_OF = date(2026, 10, 1)
CFG = FactScoringConfig(as_of=AS_OF)


def rec(rid, source, facts, status="active"):
    return SourceRecord(
        record_id=rid,
        source=source,
        locator="t",
        status=status,
        acl=[source],
        facts=[
            Fact(field=f, value=v, observed_at=d, valid_until=u, record_id=rid)
            for f, v, d, u in facts
        ],
    )


def test_freshness_decay_and_validity():
    assert freshness(AS_OF, AS_OF, 60) == 1.0
    assert freshness(date(2026, 8, 2), AS_OF, 60) == pytest.approx(0.5)
    assert freshness(None, AS_OF, 60, undated=0.4) == 0.4
    # asserted for a period still running -> fully fresh, then decays from its end
    assert freshness(date(2024, 1, 1), AS_OF, 365, valid_until=date(2027, 1, 1)) == 1.0
    assert freshness(date(2020, 1, 1), AS_OF, 365, valid_until=date(2025, 10, 1)) == (
        pytest.approx(0.5, abs=0.01)
    )


def test_authority_order_status_and_override():
    a = {s: authority(s, "active", CFG) for s in ("contract", "crm", "email", "slack")}
    assert a["contract"] > a["crm"] > a["email"] > a["slack"]
    assert authority("contract", "superseded", CFG) < a["slack"]
    assert authority("slack", "archived", CFG) < a["slack"]
    cfg = FactScoringConfig(field_authority={"owner": {"slack": 0.9}})
    assert authority("slack", "active", cfg, "owner") > authority("crm", "active", cfg, "owner")
    assert authority("slack", "active", cfg, "contract_value") == a["slack"]


def test_agreement_raises_confidence_and_stays_in_unit_interval():
    one = score_field("owner", [rec("a", "crm", [("owner", "Ali", AS_OF, None)])], CFG)
    two = score_field(
        "owner",
        [
            rec("a", "crm", [("owner", "Ali", AS_OF, None)]),
            rec("b", "slack", [("owner", "ali ", AS_OF, None)]),  # same value, other spelling
        ],
        CFG,
    )
    assert 0 < one.confidence < two.confidence <= 1
    assert not two.conflict and {e.record_id for e in two.sources} == {"a", "b"}


def test_conflict_keeps_losers_as_alternatives():
    fact = score_field(
        "contract_value",
        [
            rec("v2", "contract", [("contract_value", 150.0, date(2026, 1, 1), date(2028, 1, 1))]),
            rec("v1", "contract", [("contract_value", 100.0, date(2024, 1, 1), date(2026, 1, 1))],
                status="superseded"),
            # CRM touched last week but still carrying the old value
            rec("crm", "crm", [("contract_value", 100.0, date(2026, 9, 24), None)]),
        ],
        CFG,
    )  # fmt: skip
    assert fact.value == 150.0 and fact.conflict
    assert [a.value for a in fact.alternatives] == [100.0]
    assert {e.record_id for e in fact.alternatives[0].sources} == {"v1", "crm"}
    assert "conflicting" in fact.explanation
    assert fact.last_updated == date(2026, 1, 1)


def test_much_newer_statement_beats_stale_higher_authority():
    records = [
        rec("crm", "crm", [("owner", "Old", date(2026, 1, 10), None)]),
        rec("slack", "slack", [("owner", "New", date(2026, 9, 1), None)]),
    ]
    assert score_field("owner", records, CFG).value == "New"
    # ...but a Slack message older than the CRM update loses
    records[1] = rec("slack", "slack", [("owner", "New", date(2025, 12, 1), None)])
    assert score_field("owner", records, CFG).value == "Old"


def test_archived_source_is_discounted():
    fact = score_field(
        "owner",
        [
            rec("crm", "crm", [("owner", "Current", date(2026, 6, 1), None)]),
            rec("old", "slack", [("owner", "Former", date(2026, 9, 20), None)], status="archived"),
        ],
        CFG,
    )
    assert fact.value == "Current" and fact.alternatives[0].value == "Former"


def test_score_entity_skips_unobserved_fields():
    facts = score_entity([rec("a", "crm", [("owner", "Ali", AS_OF, None)])], CFG)
    assert set(facts) == {"owner"}
