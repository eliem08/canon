from datetime import date

from canon.models import Fact, SourceRecord
from canon.resolve.golden import build_golden
from canon.score import FactScoringConfig

AS_OF = FactScoringConfig(as_of=date(2026, 10, 1))


def rec(rid, source, name, status="active", updated=None, facts=(), **kw):
    return SourceRecord(
        record_id=rid, source=source, locator="t", name=name, status=status,
        updated_at=updated, acl=[source],
        facts=[Fact(field=f, value=v, observed_at=d, record_id=rid) for f, v, d in facts], **kw,
    )  # fmt: skip


def test_survivorship_and_lineage():
    records = [
        rec("contract:v1", "contract", "Acme SARL", status="superseded",
            updated=date(2024, 1, 1), address="Old St", phone="+212522000001",
            facts=[("contract_value", 100.0, date(2024, 1, 1)),
                   ("renewal_date", "2026-01-01", date(2024, 1, 1)),
                   ("address", "Old St", date(2024, 1, 1))]),
        rec("contract:v2", "contract", "Ste Acme SARL", updated=date(2026, 1, 1),
            address="New St", phone="+212522000001",
            facts=[("contract_value", 150.0, date(2026, 1, 1)),
                   ("renewal_date", "2028-01-01", date(2026, 1, 1)),
                   ("address", "New St", date(2026, 1, 1))]),
        rec("crm:1", "crm", "ACME SARL", updated=date(2026, 2, 1), phone="+212661000000",
            facts=[("owner", "Old Owner", date(2026, 2, 1)),
                   ("contract_value", 100.0, date(2026, 2, 1))]),
        rec("slack:1", "slack", "acme", updated=date(2026, 6, 1), phone="+212661000000",
            facts=[("owner", "New Owner", date(2026, 6, 1))]),
        rec("slack:old", "slack", "acme", status="archived", updated=date(2026, 9, 1),
            facts=[("owner", "Archived Owner", date(2026, 9, 1))]),
    ]  # fmt: skip
    g = build_golden("C1", records, AS_OF)
    assert g.fields["legal_name"].value == "Acme SARL"
    assert g.fields["name"].value == "Acme"
    assert g.fields["contract_value"].value == 150.0  # active contract beats CRM and v1
    assert g.fields["contract_value"].record_ids == ["contract:v2"]
    losers = {a.value for a in g.facts["contract_value"].alternatives}
    assert losers == {100.0}  # v1 + stale CRM value kept as an alternative, not deleted
    assert g.fields["renewal_date"].value == "2028-01-01"
    assert g.fields["owner"].value == "New Owner"  # newest non-archived statement
    assert g.fields["address"].value == "New St"
    assert g.fields["phone"].value == "+212522000001"  # contracts outweigh contact mobiles
    assert g.members == sorted(r.record_id for r in records)
    assert g.acl == ["contract", "crm", "slack"]
