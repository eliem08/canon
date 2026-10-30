"""Read-only CRM pulls (canon/ingest/pull.py) against a local fake of each API."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from canon.ingest import load_all
from canon.ingest.config import IngestConfig
from canon.ingest.pull import PullError, pull_hubspot, pull_salesforce, write_export

MA = IngestConfig(default_country="212", currency="MAD")  # these tests use Moroccan data

TOKEN = "test-token-not-real"


class FakeAPI:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                api.calls.append((self.command, self.path, self.headers.get("Authorization")))
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    self.send_response(401)
                    self.end_headers()
                    return
                body = api.route(self.path)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()


class HubSpot(FakeAPI):
    def route(self, path):
        url = urlsplit(path)
        q = parse_qs(url.query)
        if url.path == "/crm/v3/owners":
            return {"results": [{"id": "7", "firstName": "Omar", "lastName": "Fassi"}]}
        if q.get("after") == ["2"]:
            return {
                "results": [
                    {"id": "102", "properties": {"name": "Rif Ciments SA", "city": "Tanger"}}
                ]
            }
        return {
            "results": [
                {
                    "id": "101",
                    "properties": {
                        "name": "Atlas Logistique",
                        "domain": "atlas-logistique.ma",
                        "phone": "0522 12 34 56",
                        "city": "Casablanca",
                        "hubspot_owner_id": "7",
                        "annual_contract_value": "1426000",
                        "hs_lastmodifieddate": "2026-09-30T10:00:00Z",
                    },
                }
            ],
            "paging": {"next": {"after": "2"}},
        }


class Salesforce(FakeAPI):
    def route(self, path):
        if path.startswith("/services/data/v60.0/query/next-1"):
            return {"done": True, "records": [{"Id": "0015g2", "Name": "Rif Ciments SA"}]}
        assert "FROM+Account" in path or "FROM%20Account" in path
        return {
            "done": False,
            "nextRecordsUrl": "/services/data/v60.0/query/next-1",
            "records": [
                {
                    "Id": "0015g1",
                    "Name": "Atlas Logistique",
                    "BillingCity": "Casablanca",
                    "Owner": {"Name": "Omar Fassi"},
                    "LastModifiedDate": "2026-09-30T10:00:00.000+0000",
                    "Renewal_Date__c": "2027-03-01",
                }
            ],
        }


def test_hubspot_pull_pages_owners_and_custom_properties():
    with HubSpot() as api:
        rows = pull_hubspot(TOKEN, {"contract_value": "annual_contract_value"}, base=api.base)
    assert [r["Id"] for r in rows] == ["101", "102"]
    assert rows[0]["Owner"] == "Omar Fassi" and rows[0]["Annual Contract Value"] == "1426000"
    assert rows[0]["Website"] == "atlas-logistique.ma" and rows[1]["Billing City"] == "Tanger"
    assert {c[0] for c in api.calls} == {"GET"}  # read-only


def test_salesforce_pull_follows_next_records_url():
    with Salesforce() as api:
        rows = pull_salesforce(TOKEN, api.base, {"renewal_date": "Renewal_Date__c"})
    assert [r["Account Name"] for r in rows] == ["Atlas Logistique", "Rif Ciments SA"]
    assert rows[0]["Owner"] == "Omar Fassi" and rows[0]["Renewal Date"] == "2027-03-01"
    assert {c[0] for c in api.calls} == {"GET"}


def test_pulled_export_goes_through_the_normal_ingest(tmp_path):
    with HubSpot() as api:
        rows = pull_hubspot(TOKEN, {"contract_value": "annual_contract_value"}, base=api.base)
    write_export(rows, tmp_path / "crm" / "accounts.json")
    recs = {r.name: r for r in load_all(tmp_path, config=MA)}
    atlas = recs["Atlas Logistique"]
    assert atlas.phone == "+212522123456" and atlas.domain == "atlas-logistique.ma"
    facts = {f.field: f.value for f in atlas.facts}
    assert facts["owner"] == "Omar Fassi" and facts["contract_value"] == 1_426_000


def test_a_refused_token_is_reported_without_echoing_it():
    with HubSpot() as api, pytest.raises(PullError) as err:
        pull_hubspot("wrong-token", base=api.base)
    assert "401" in str(err.value) and "wrong-token" not in str(err.value)


def test_pagination_never_sends_the_token_to_another_host():
    class Redirecting(HubSpot):
        def route(self, path):
            if path.startswith("/crm/v3/owners"):
                return {"results": [], "paging": {"next": {"link": "https://evil.test/steal"}}}
            return super().route(path)

    with Redirecting() as api, pytest.raises(PullError, match="another host"):
        pull_hubspot(TOKEN, base=api.base)


def test_salesforce_field_names_cannot_inject_soql():
    with pytest.raises(PullError, match="not a Salesforce field"):
        pull_salesforce(TOKEN, "http://127.0.0.1:1", {"owner": "Name FROM User --"})
