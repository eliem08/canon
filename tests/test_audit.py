"""The readiness audit report: findings are right, complete enough, and need no answer key."""

import json
from datetime import date
from pathlib import Path

import pytest

from canon.audit import build_audit, render_audit
from canon.evals.scoring import is_correct
from canon.ingest import load_all
from canon.mcp_server import CallerDirectory
from canon.resolve.pipeline import ResolverConfig, resolve
from canon.score import FactScoringConfig

DATA = Path(__file__).resolve().parents[1] / "data" / "synthetic"
TRUTH = json.loads((DATA / "ground_truth" / "ground_truth.json").read_text(encoding="utf-8"))
AS_OF = date(2026, 10, 1)


@pytest.fixture(scope="module")
def world():
    records = load_all(DATA)
    res = resolve(records, ResolverConfig(facts=FactScoringConfig(as_of=AS_OF)))
    directory = CallerDirectory.from_file(DATA / "identities.json")
    return records, build_audit(records, res, directory, [], AS_OF)


def test_stale_crm_findings_are_right_and_mostly_complete(world):
    records, audit = world
    found = audit.stale_crm + audit.slack_only_owner_changes
    for s in found:  # precision: the kept value is the truth and the CRM value is not
        truth = TRUTH["entities"][TRUTH["records"][s.stale_record]][s.field]
        assert is_correct(s.field, truth, s.current), s
        assert not is_correct(s.field, truth, s.stale), s
    flagged = {(s.stale_record, s.field) for s in found}
    actually_stale = {
        (r.record_id, f.field)
        for r in records
        if r.source == "crm" and r.status == "active"
        for f in r.facts
        if f.field in ("owner", "contract_value", "renewal_date", "address")
        and not is_correct(
            f.field, TRUTH["entities"][TRUTH["records"][r.record_id]][f.field], str(f.value)
        )
    }
    caught = {(rid, f) for rid, f in actually_stale if any(rid == x and f == y for x, y in flagged)}

    # one finding per customer and field, so count customers rather than records
    def by_customer(pairs):
        return {(TRUTH["records"][rid], f) for rid, f in pairs}

    assert len(by_customer(caught)) / len(by_customer(actually_stale)) >= 0.8


def test_findings_are_ranked_and_actionable(world):
    _, audit = world
    impacts = [f.impact for f in audit.findings]
    assert impacts == sorted(impacts, reverse=True)
    assert all(f.who_fixes and f.count > 0 for f in audit.findings)
    assert {"stale_crm_contract_value", "crm_duplicates", "review_merges"} <= {
        f.key for f in audit.findings
    }


def test_permission_view_per_caller(world):
    _, audit = world
    views = {v.caller: v for v in audit.callers}
    assert views["intern"].records_visible == 0
    assert views["revops.admin"].customers_partial == 0
    assert views["salma.el.idrissi"].customers_partial > 0  # contracts are legal-only


def test_report_renders_every_section(world):
    _, audit = world
    report = render_audit(audit)
    for heading in ("Prioritized fix list", "Duplicates", "Conflicting and stale facts",
                    "quarantine", "Merges to confirm", "Permissions", "Caveats"):  # fmt: skip
        assert heading in report


def test_audit_never_reads_the_answer_key():
    source = (Path(__file__).resolve().parents[1] / "canon" / "audit.py").read_text("utf-8")
    assert "ground_truth" not in source


def test_renewal_calendar_lists_upcoming_renewals_in_order(world):
    _, audit = world
    assert "Renewals in the next 180 days" in render_audit(audit)
    days = [r.cancel_by or r.renews_on for r in audit.renewals]
    assert days == sorted(days)
    assert all(AS_OF < r.renews_on <= date(2027, 3, 30) for r in audit.renewals)


def test_an_auto_renewing_contract_rolls_into_the_calendar():
    from canon.audit import _renewals
    from canon.models import GoldenRecord, ResolvedFact

    def f(field, value):
        return ResolvedFact(field=field, value=value, confidence=0.9, last_updated=None)

    g = GoldenRecord(entity_id="e1", fields={}, members=["contract:1"],
                     facts={"renewal_date": f("renewal_date", "2024-12-01"),
                            "renewal_period_months": f("renewal_period_months", 12),
                            "renewal_notice": f("renewal_notice", "P60D")})  # fmt: skip
    (r,) = _renewals([g], AS_OF, 180)
    assert (r.renews_on, r.cancel_by, r.automatic) == (date(2026, 12, 1), date(2026, 10, 2), True)


def test_week_two_audit_reports_what_the_client_fixed(world, tmp_path):
    import shutil

    from canon.audit import compare_audits, render_delta

    _, before = world
    target = next(s for s in before.stale_crm if s.field == "owner")
    data = tmp_path / "data"
    shutil.copytree(DATA, data)
    path = data / "crm" / "accounts.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    for row in rows:  # the client applies one line of crm_fixes.csv
        if row["Id"] == target.stale_record.removeprefix("crm:"):
            row["Owner"] = target.current_value
            row["LastModifiedDate"] = "2026-10-01T09:00:00Z"
    path.write_text(json.dumps(rows), encoding="utf-8")
    records = load_all(data)
    res = resolve(records, ResolverConfig(facts=FactScoringConfig(as_of=AS_OF)))
    after = build_audit(records, res, None, [], AS_OF)
    delta = compare_audits(before, after)
    assert (target.stale_record, "owner") in {(s.stale_record, s.field) for s in delta.fixed}
    assert not delta.new
    report = render_delta(delta)
    assert "Stale CRM values fixed since then: **" in report and target.stale_record in report
