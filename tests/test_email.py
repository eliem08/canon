"""Email connector: one record per customer domain, facts cited to their message, no guessing."""

import json
from datetime import date
from email.message import EmailMessage
from pathlib import Path

import pytest

from canon.ingest import load_all
from canon.ingest.deployment import parse_deployment
from canon.ingest.email import EmailConfig, fresh_text, load_email


def _msg(sender, to, subject, body, when, mid, cc=None) -> EmailMessage:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, to, subject
    if cc:
        m["Cc"] = cc
    m["Date"] = when
    m["Message-ID"] = f"<{mid}@mail.example>"
    m.set_content(body)
    return m


def _write(root: Path, *messages: EmailMessage) -> Path:
    box = root / "email"
    box.mkdir(parents=True, exist_ok=True)
    for i, m in enumerate(messages):
        (box / f"{i:02d}.eml").write_bytes(bytes(m))
    return box


THREAD = (
    _msg("Jordan Miller <jordan@fieldstone.io>", "Chris Lee <chris@harborfoods.com>",
         "Renewal", "Hi Chris, attached is the renewal. Thanks, Jordan",
         "Mon, 02 Mar 2026 10:00:00 +0000", "m1"),
    _msg("Chris Lee <chris@harborfoods.com>", "jordan@fieldstone.io", "Re: Renewal",
         "Signed! New annual contract value for Harbor Foods: $1,468,000 per year.\n"
         "Chris Lee | Harbor Foods | (415) 555-0134\n\n"
         "On Mon, Mar 2, 2026 at 10:00 AM Jordan <jordan@fieldstone.io> wrote:\n"
         "> Our annual contract value last year was $1,190,000",
         "Tue, 03 Mar 2026 09:30:00 +0000", "m2"),
    _msg("Jordan Miller <jordan@fieldstone.io>", "chris@harborfoods.com", "Re: Renewal",
         "Great. Sarah Chen is taking over the Harbor account from today.\n"
         "Jordan Miller | Fieldstone | (212) 555-0199",
         "Wed, 04 Mar 2026 08:00:00 +0000", "m3", cc="Sarah Chen <sarah@fieldstone.io>"),
    _msg("Pat <pat.harbor@gmail.com>", "jordan@fieldstone.io", "hello", "Annual value $5 per year",
         "Thu, 05 Mar 2026 08:00:00 +0000", "m4"),
)  # fmt: skip


def test_one_record_per_customer_domain_with_cited_dated_facts(tmp_path):
    (rec,) = load_email(_write(tmp_path, *THREAD), EmailConfig(own_domains=("fieldstone.io",)))
    assert rec.record_id == "email:harborfoods.com" and rec.source == "email"
    assert rec.domain == "harborfoods.com" and rec.email == "chris@harborfoods.com"
    facts = {f.field: f for f in rec.facts}
    assert facts["contract_value"].value == 1_468_000  # the quoted $1,190,000 is not read
    assert facts["contract_value"].observed_at == date(2026, 3, 3)
    assert facts["contract_value"].source_ref.endswith("#m2@mail.example")
    assert facts["owner"].value == "Sarah Chen"
    assert rec.phone == "+14155550134"  # the customer's signature, never ours (212...)
    assert rec.updated_at == date(2026, 3, 5) or rec.updated_at == date(2026, 3, 4)


def test_two_amounts_on_one_line_are_still_refused(tmp_path):
    text = "Annual contract value $1,468,000 per year (last year $1,190,000 per year)"
    msg = _msg("chris@harborfoods.com", "jordan@fieldstone.io", "x", text,
               "Tue, 03 Mar 2026 09:30:00 +0000", "z1")  # fmt: skip
    (rec,) = load_email(_write(tmp_path, msg), EmailConfig(own_domains=("fieldstone.io",)))
    assert not [f for f in rec.facts if f.field == "contract_value"]
    assert any(i.reason == "multiple_amounts" for i in rec.issues)


def test_quoted_history_is_cut():
    body = "New price $2,000 per year\n\nLe 2 mars 2026, Jordan a écrit :\n> old price $1,000"
    assert "$1,000" not in fresh_text(body)
    outlook = "Thanks\n-----Original Message-----\nFrom: x\nSent: y\nannual value $9 per year"
    assert "$9" not in fresh_text(outlook)


def test_own_domain_is_inferred_only_when_obvious(tmp_path):
    other = _msg("ana@keystonebuild.com", "jordan@fieldstone.io", "hi", "hello",
                 "Fri, 06 Mar 2026 08:00:00 +0000", "k1")  # fmt: skip
    recs = load_email(_write(tmp_path / "a", *THREAD[:3], other))  # fieldstone.io on every message
    assert {r.domain for r in recs} == {"harborfoods.com", "keystonebuild.com"}
    unreadable = []  # one customer only: both domains are on every message, so it is ambiguous
    assert load_email(_write(tmp_path / "c", *THREAD[:3]), unreadable=unreadable) == []
    assert unreadable[0].reason == "own_domain_unknown"
    mixed = [
        _msg(f"a@c{i}.com", f"b@d{i}.com", "x", "hi", "Mon, 02 Mar 2026 10:00:00 +0000", f"x{i}")
        for i in range(4)
    ]
    unreadable = []
    assert load_email(_write(tmp_path / "b", *mixed), unreadable=unreadable) == []
    assert unreadable[0].reason == "own_domain_unknown"


def test_deployment_section_and_typos(tmp_path):
    dep = parse_deployment({"email": {"own_domains": ["Fieldstone.io"], "acl": ["exec"]}})
    assert dep.email.own_domains == ("fieldstone.io",) and dep.email.acl == ("exec",)
    with pytest.raises(ValueError, match="email"):
        parse_deployment({"email": {"own_domain": ["fieldstone.io"]}})
    with pytest.raises(ValueError, match="own_domains"):
        parse_deployment({"email": {"own_domains": "fieldstone.io"}})


def test_email_record_joins_its_crm_account_through_load_all(tmp_path):
    from canon.resolve.pipeline import ResolverConfig, resolve
    from canon.score import FactScoringConfig

    _write(tmp_path, *THREAD)
    (tmp_path / "crm").mkdir()
    (tmp_path / "crm" / "accounts.json").write_text(json.dumps([{
        "Id": "001A", "Account Name": "Harbor Foods Corp", "Website": "www.harborfoods.com",
        "Owner": "Jordan Miller", "Annual Contract Value": 1190000, "Currency": "USD",
        "LastModifiedDate": "2025-12-01T10:00:00Z",
    }]))  # fmt: skip
    (tmp_path / "canon.json").write_text(json.dumps({"email": {"own_domains": ["fieldstone.io"]}}))
    records = load_all(tmp_path)
    res = resolve(records, ResolverConfig(facts=FactScoringConfig(as_of=date(2026, 4, 1))))
    (cluster,) = [c for c in res.clusters if "crm:001A" in c]
    assert "email:harborfoods.com" in cluster
    value = next(g for g in res.golden if "crm:001A" in g.members).facts["contract_value"]
    # the customer's email disagrees with the CRM: surfaced as a conflict with both values
    # cited (which one wins is the scoring policy: email ranks below the CRM by default)
    assert value.conflict
    assert {value.value, *(a.value for a in value.alternatives)} == {1_190_000, 1_468_000}


def test_intake_check_reports_the_mailbox(tmp_path):
    from canon.intake import check_export, render_check

    _write(tmp_path, *THREAD[:3])  # one customer: our domain cannot be told apart
    report = check_export(tmp_path)
    assert report["email"]["messages"] == 3 and report["email"]["own_domains"] is None
    assert "own_domains" in render_check(report)


def test_html_only_messages_are_read_and_quoted_blocks_dropped(tmp_path):
    m = EmailMessage()
    m["From"], m["To"] = "chris@harborfoods.com", "jordan@fieldstone.io"
    m["Date"], m["Message-ID"] = "Tue, 03 Mar 2026 09:30:00 +0000", "<h1@mail.example>"
    m.set_content(
        "<p>New annual contract value: $1,468,000 per year</p>"
        "<blockquote>annual contract value $1,190,000 per year</blockquote>"
        "<script>alert(1)</script>",
        subtype="html",
    )
    (rec,) = load_email(_write(tmp_path, m), EmailConfig(own_domains=("fieldstone.io",)))
    assert [f.value for f in rec.facts if f.field == "contract_value"] == [1_468_000]
