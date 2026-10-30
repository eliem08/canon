"""Read-only CRM pulls: HubSpot companies and Salesforce accounts, written as a CRM export.

`canon pull hubspot|salesforce --out <data>/crm/accounts.json` calls the CRM's REST API with a
token from the environment and writes rows under the default column names (`CRMFieldMap`), so the
pulled file goes through exactly the same `canon check` / ingest path as a manual export. Nothing is
ever written back to the CRM: only GET requests are made.

- HubSpot: a private-app token in `HUBSPOT_TOKEN` (scopes: crm.objects.companies.read,
  crm.objects.owners.read). Contract value and renewal date are custom properties; name them with
  `--property contract_value=<internal name>`.
- Salesforce: `SALESFORCE_TOKEN` (an OAuth access token) and `SALESFORCE_INSTANCE_URL`. Custom
  fields go the same way (`--property renewal_date=Renewal_Date__c`).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import asdict
from pathlib import Path

from canon.ingest.crm import CRMFieldMap

HUBSPOT_URL = "https://api.hubapi.com"
SALESFORCE_API = "v60.0"
COLUMNS = asdict(CRMFieldMap())  # canonical field -> default export column

HUBSPOT_PROPERTIES = {
    "name": "name",
    "website": "domain",
    "phone": "phone",
    "street": "address",
    "city": "city",
    "modified": "hs_lastmodifieddate",
}
SALESFORCE_FIELDS = {
    "id": "Id",
    "name": "Name",
    "website": "Website",
    "phone": "Phone",
    "street": "BillingStreet",
    "city": "BillingCity",
    "owner": "Owner.Name",
    "modified": "LastModifiedDate",
}


class PullError(RuntimeError):
    pass


def _same_host(url: str, base: str) -> str:
    """Pagination links come from the API; the token is only ever sent to the host we started on."""
    if urllib.parse.urlsplit(url).netloc != urllib.parse.urlsplit(base).netloc:
        raise PullError(f"refusing to follow a pagination link to another host: {url[:80]}")
    return url


def _get(url: str, token: str, timeout: int = 60) -> dict:
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        # the body may echo request details; report the status only, never the token
        raise PullError(f"{exc.code} from {urllib.parse.urlsplit(url).netloc}") from None


def _value(record: dict, path: str):
    for part in path.split("."):
        record = (record or {}).get(part) if isinstance(record, dict) else None
    return record


def pull_hubspot(token: str, extra: dict[str, str] | None = None, base: str = HUBSPOT_URL) -> list:
    """Every company, with its owner's name resolved from the owners API."""
    props = {**HUBSPOT_PROPERTIES, **(extra or {})}
    owners: dict[str, str] = {}
    url = f"{base}/crm/v3/owners?limit=100"
    while url:
        page = _get(url, token)
        for o in page.get("results", []):
            owners[str(o["id"])] = " ".join(
                x for x in (o.get("firstName"), o.get("lastName")) if x
            ) or o.get("email", "")
        link = ((page.get("paging") or {}).get("next") or {}).get("link")
        url = _same_host(link, base) if link else None
    wanted = ",".join(sorted({*props.values(), "hubspot_owner_id"}))
    query = urllib.parse.urlencode({"limit": 100, "properties": wanted, "archived": "false"})
    url = f"{base}/crm/v3/objects/companies?{query}"
    rows = []
    while url:
        page = _get(url, token)
        for company in page.get("results", []):
            p = company.get("properties") or {}
            row = {COLUMNS["id"]: str(company["id"])}
            for field, prop in props.items():
                if field in COLUMNS and p.get(prop) not in (None, ""):
                    row[COLUMNS[field]] = p[prop]
            owner = owners.get(str(p.get("hubspot_owner_id") or ""))
            if owner:
                row[COLUMNS["owner"]] = owner
            rows.append(row)
        after = ((page.get("paging") or {}).get("next") or {}).get("after")
        url = f"{base}/crm/v3/objects/companies?{query}&after={after}" if after else None
    return rows


def pull_salesforce(token: str, instance_url: str, extra: dict[str, str] | None = None) -> list:
    """Every account through SOQL, following `nextRecordsUrl`."""
    fields = {**SALESFORCE_FIELDS, **(extra or {})}
    for name in fields.values():
        if not all(part.replace("_", "").isalnum() for part in name.split(".")):
            raise PullError(f"not a Salesforce field name: {name!r}")
    soql = f"SELECT {', '.join(dict.fromkeys(fields.values()))} FROM Account"
    base = instance_url.rstrip("/")
    url = f"{base}/services/data/{SALESFORCE_API}/query?{urllib.parse.urlencode({'q': soql})}"
    rows = []
    while url:
        page = _get(url, token)
        for record in page.get("records", []):
            row = {}
            for field, api_name in fields.items():
                value = _value(record, api_name)
                if field in COLUMNS and value not in (None, ""):
                    row[COLUMNS[field]] = value
            rows.append(row)
        nxt = page.get("nextRecordsUrl")
        url = _same_host(f"{base}{nxt}", base) if nxt and not page.get("done", True) else None
    return rows


def write_export(rows: list[dict], out: Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
