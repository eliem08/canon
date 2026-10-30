import json
from datetime import date
from pathlib import Path

from canon.ingest import load_all
from canon.ingest.config import IngestConfig
from canon.ingest.contracts import load_contracts, parse_contract
from canon.ingest.crm import CRMFieldMap, crm_row_to_record
from canon.ingest.slack import SlackConfig, channel_to_record, humanize_channel

MA = IngestConfig(default_country="212", currency="MAD")  # these tests use Moroccan data

DATA = Path(__file__).resolve().parents[1] / "data" / "synthetic"


def test_crm_row():
    row = {
        "Id": "001X",
        "Account Name": "ACME SARL",
        "Website": "https://www.acme.ma/",
        "Phone": "05 22 12 34 56",
        "Primary Contact Email": "x@gmail.com",
        "Billing Street": "1 Rue A",
        "Billing City": "Rabat",
        "ICE": None,
        "Owner": "Karim Tazi",
        "Annual Contract Value": "450k MAD",
        "Renewal Date": "01/03/2027",
        "LastModifiedDate": "2026-07-06T12:00:00Z",
    }
    r = crm_row_to_record(row, "crm.json", CRMFieldMap(), ("sales",), MA)
    assert r.record_id == "crm:001X" and r.domain == "acme.ma" and r.phone == "+212522123456"
    facts = {f.field: f for f in r.facts}
    assert facts["contract_value"].value == 450_000
    assert facts["renewal_date"].value == "2027-03-01"
    assert facts["owner"].observed_at == date(2026, 7, 6)
    assert r.acl == ["sales"]


def test_slack_channel_extracts_mentions_and_facts():
    channel = {"id": "C1", "name": "old-acme-log", "is_archived": True,
               "purpose": {"value": "Suivi compte Acme Logistique"}}  # fmt: skip
    messages = [
        {"ts": "1735725600", "text": "mn daba <@U1> howa l'owner dyal acme"},
        {"ts": "1735812000", "text": "contrat acme tla3 l 300k MAD"},
        {"ts": "1735898400", "text": "renouvellement dyal acme f 01/02/2027"},
        {"ts": "1735984800", "text": "contact chez acme: info@acme.ma, 3ayto l 0661234567"},
    ]
    r = channel_to_record(channel, messages, {"U1": "Nadia Berrada"}, SlackConfig(), "slack", MA)
    assert r.name == "acme log" and r.alt_names == ["Acme Logistique"]
    assert r.status == "archived" and r.domain == "acme.ma" and r.phone == "+212661234567"
    facts = {f.field: f.value for f in r.facts}
    assert facts == {
        "owner": "Nadia Berrada",
        "contract_value": 300_000,
        "renewal_date": "2027-02-01",
    }


def test_humanize_channel():
    assert humanize_channel("client-atlas-log", ("client",)) == "atlas log"
    assert humanize_channel("atlas", ("client",)) == "atlas"


CONTRACT = """CONTRAT DE PRESTATION DE SERVICES
Contrat N° : CN-1
Version : 2
Date de signature : 17/03/2026
Le Client : Acme SARL
الطرف الثاني: أكمي ش.م.م
ICE : 001234567890123
Siège social : 1 Rue A, Rabat
Représenté par : Ali B
Contact : contact@acme.ma - Tél : 0522-12-34-56
Article 4 - Prix. Le montant annuel est fixé à 1 426 000 MAD HT.
Article 5 - Durée. Date d'effet : 01/03/2026. Date de renouvellement : 01/03/2028.
Article 12 - Le présent contrat annule et remplace la version 1 du contrat N° CN-1.
"""


def test_parse_contract():
    parsed = parse_contract(CONTRACT, "contract:x", "x.txt", config=MA)
    r = parsed["record"]
    assert (parsed["number"], parsed["version"], parsed["supersedes"]) == ("CN-1", 2, 1)
    assert r.name == "Acme SARL" and r.alt_names == ["أكمي ش.م.م"]
    assert (r.address, r.city, r.tax_id, r.phone) == ("1 Rue A", "Rabat", "001234567890123",
                                                      "+212522123456")  # fmt: skip
    facts = {f.field: f.value for f in r.facts}
    assert facts["contract_value"] == 1_426_000 and facts["renewal_date"] == "2028-03-01"


def test_older_contract_versions_are_superseded(tmp_path):
    (tmp_path / "a_v2.txt").write_text(CONTRACT, encoding="utf-8")
    (tmp_path / "a_v1.txt").write_text(CONTRACT.replace("Version : 2", "Version : 1"))
    status = {r.record_id: r.status for r in load_contracts(tmp_path, config=MA)}
    assert status == {"contract:a_v1": "superseded", "contract:a_v2": "active"}


def test_load_all_covers_every_ground_truth_record():
    truth = json.loads((DATA / "ground_truth" / "ground_truth.json").read_text(encoding="utf-8"))
    records = load_all(DATA)
    assert {r.record_id for r in records} == set(truth["records"])
    assert sum(r.status == "superseded" for r in records) == 25
    assert all(r.acl for r in records)
