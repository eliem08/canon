"""CRM account export connector (Salesforce-style JSON list of accounts)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from canon.ingest.common import business_domain, normalize_phone, parse_date, parse_money
from canon.models import Fact, SourceRecord


@dataclass(frozen=True)
class CRMFieldMap:
    """Column names of the export. Override per CRM; defaults match Salesforce."""

    id: str = "Id"
    name: str = "Account Name"
    website: str = "Website"
    phone: str = "Phone"
    email: str = "Primary Contact Email"
    street: str = "Billing Street"
    city: str = "Billing City"
    tax_id: str = "ICE"
    owner: str = "Owner"
    contract_value: str = "Annual Contract Value"
    renewal_date: str = "Renewal Date"
    modified: str = "LastModifiedDate"


DEFAULT_CRM_ACL = ("sales", "exec")


def load_crm(
    path: Path, fields: CRMFieldMap | None = None, acl: tuple[str, ...] = DEFAULT_CRM_ACL
) -> list[SourceRecord]:
    fields = fields or CRMFieldMap()
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return [crm_row_to_record(row, str(path), fields, acl) for row in rows]


def crm_row_to_record(
    row: dict, locator: str, fields: CRMFieldMap, acl: tuple[str, ...]
) -> SourceRecord:
    rid = f"crm:{row[fields.id]}"
    modified = parse_date(row.get(fields.modified))
    email = row.get(fields.email)
    facts = []

    def fact(name: str, value) -> None:
        if value not in (None, ""):
            facts.append(Fact(field=name, value=value, observed_at=modified, record_id=rid))

    fact("owner", row.get(fields.owner))
    fact("contract_value", parse_money(row.get(fields.contract_value)))
    renewal = parse_date(row.get(fields.renewal_date))
    fact("renewal_date", renewal.isoformat() if renewal else None)
    fact("address", row.get(fields.street))
    return SourceRecord(
        record_id=rid,
        source="crm",
        locator=f"{locator}#{row[fields.id]}",
        name=row.get(fields.name),
        domain=business_domain(row.get(fields.website)) or business_domain(email),
        phone=normalize_phone(row.get(fields.phone)),
        email=email,
        address=row.get(fields.street),
        city=row.get(fields.city),
        tax_id=row.get(fields.tax_id),
        updated_at=modified,
        facts=facts,
        acl=list(acl),
    )
