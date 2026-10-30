"""WhatsApp and Microsoft Teams connectors (canon/ingest/chat.py), on fixtures written for tests."""

import json
import shutil
from pathlib import Path

import pytest

from canon.ingest import load_all
from canon.ingest.chat import load_teams, load_whatsapp, parse_whatsapp, teams_text
from canon.ingest.config import IngestConfig
from canon.mcp_server.service import _principals

FIX = Path(__file__).parent / "fixtures" / "chat"
WA = FIX / "WhatsApp Chat with Client Rif Ciments.txt"


@pytest.fixture
def export(tmp_path):
    (tmp_path / "whatsapp").mkdir()
    shutil.copy(WA, tmp_path / "whatsapp" / WA.name)
    teams = tmp_path / "teams"
    (teams / "19:abc@thread.tacv2").mkdir(parents=True)
    shutil.copy(FIX / "teams_channels.json", teams / "channels.json")
    shutil.copy(FIX / "teams_abc.json", teams / "19:abc@thread.tacv2" / "page1.json")
    return tmp_path


# ---------------------------------------------------------------- WhatsApp


def test_whatsapp_formats_multiline_media_and_bad_dates():
    msgs, bad = parse_whatsapp(WA.read_text(encoding="utf-8"))
    texts = [m["text"] for m in msgs]
    assert not any("omitted" in t for t in texts)
    assert texts[-1].endswith("deuxième ligne")  # continuation line kept with its message
    assert bad == ["31/02/2026, 10:00 - Omar Fassi: date impossible"]


@pytest.mark.parametrize(
    "line, user",
    [
        ("[17/03/2026, 14:05:12] Omar Fassi: hello", "Omar Fassi"),  # iOS
        ("17/03/2026, 14:05 - Omar Fassi: hello", "Omar Fassi"),  # Android
        ("3/17/26, 2:05 PM - Omar Fassi: hello", "Omar Fassi"),  # US phone, 12-hour clock
    ],
)
def test_whatsapp_line_styles(line, user):
    msgs, _ = parse_whatsapp(line)
    assert [m["user"] for m in msgs] == [user]


def test_whatsapp_twelve_hour_clock():
    pm, _ = parse_whatsapp("3/17/26, 12:05 PM - A: x\n3/17/26, 12:05 AM - A: y")
    assert int(pm[0]["ts"]) - int(pm[1]["ts"]) == 12 * 3600


def test_whatsapp_day_month_order_is_inferred_from_the_file_or_configured():
    text = "13/02/2026, 09:00 - A: x\n03/02/2026, 09:00 - A: y"
    (inferred, _), (us, _) = (
        parse_whatsapp(text),
        parse_whatsapp("02/13/2026, 09:00 - A: x\n02/03/2026, 09:00 - A: y"),
    )
    assert inferred[1]["ts"] == us[1]["ts"]  # 3 February both times
    forced, _ = parse_whatsapp("03/02/2026, 09:00 - A: y", IngestConfig(dayfirst=False))
    assert forced[0]["ts"] != inferred[1]["ts"]  # 2 March when the deployment says month first


def test_whatsapp_record_facts_citations_and_participant_acl(tmp_path):
    shutil.copy(WA, tmp_path / WA.name)
    (rec,) = load_whatsapp(tmp_path)
    assert rec.record_id.startswith("whatsapp:") and rec.source == "slack"
    assert rec.name == "rif ciments"
    facts = {f.field: f for f in rec.facts}
    assert facts["contract_value"].value == 2_400_000
    assert facts["contract_value"].source_ref.startswith(f"whatsapp/{WA.name}#ts=")
    assert facts["renewal_date"].value == "2027-03-15"
    # participants only: a phone number and a name
    assert rec.acl == ["whatsapp-user:+212661234567", "whatsapp-user:omar fassi"]
    assert [i.reason for i in rec.issues if i.reason == "unreadable_timestamp"] == [
        "unreadable_timestamp"
    ]


# ---------------------------------------------------------------- Teams


def test_teams_html_bodies():
    body = {"contentType": "html", "content": "<p>A&nbsp;<at id='0'>Omar</at></p><p>B</p>"}
    assert teams_text(body) == "A Omar\nB"


def test_teams_records_and_acls(export):
    recs = {r.name: r for r in load_teams(export / "teams")}
    standard, private = recs["atlas logistique"], recs["zitoun"]  # "deal-" is a channel prefix
    assert standard.acl == ["sales"] and standard.alt_names == ["Atlas Logistique"]
    assert private.acl == ["teams-user:aad-omar"]
    facts = {f.field: f.value for f in standard.facts}
    assert facts["contract_value"] == 1_426_000
    assert standard.email == "contact@atlas-logistique.ma"
    quotes = " ".join(f.quote or "" for f in standard.facts)
    assert "oups" not in quotes and "systemEventMessage" not in quotes


def test_unsafe_teams_channel_id(export):
    channels = json.loads((export / "teams" / "channels.json").read_text())
    channels[0]["id"] = "../../etc"
    (export / "teams" / "channels.json").write_text(json.dumps(channels))
    with pytest.raises(ValueError, match="unsafe Teams channel id"):
        load_teams(export / "teams")


def test_load_all_reads_both_and_the_deployment_file_can_share_whatsapp(export):
    sources = {r.record_id.split(":")[0] for r in load_all(export)}
    assert sources == {"whatsapp", "teams"}
    (export / "canon.json").write_text(json.dumps({"whatsapp": {"acl": ["sales"]}}))
    (wa,) = [r for r in load_all(export) if r.record_id.startswith("whatsapp:")]
    assert wa.acl == ["sales"]


def test_callers_carry_chat_principals():
    entry = {"groups": ["sales"], "chat_ids": {"teams": "aad-omar", "whatsapp": "+212661234567"}}
    assert _principals(entry) == {"sales", "teams-user:aad-omar", "whatsapp-user:+212661234567"}
