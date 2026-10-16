"""CRM account export connector (Salesforce-style JSON list of accounts)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from canon.ingest.common import business_domain
from canon.ingest.config import IngestConfig
from canon.ingest.parsing import IssueLog, infer_dayfirst, parse_amount, parse_date, parse_phone
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
    currency: str = "Currency"
    modified: str = "LastModifiedDate"


DEFAULT_CRM_ACL = ("sales", "exec")


def load_crm(
    path: Path,
    fields: CRMFieldMap | None = None,
    acl: tuple[str, ...] = DEFAULT_CRM_ACL,
    config: IngestConfig | None = None,
) -> list[SourceRecord]:
    fields = fields or CRMFieldMap()
    config = config or IngestConfig()
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    # One export uses one date convention: infer it from the dates that can only be read one way.
    inferred, conflict = infer_dayfirst(
        [row.get(f) for row in rows for f in (fields.renewal_date, fields.modified)]
    )
    dayfirst = config.dayfirst if config.dayfirst is not None else (inferred is not False)
    return [
        crm_row_to_record(
            row, str(path), fields, acl, config, dayfirst, conflict and config.dayfirst is None
        )
        for row in rows
    ]


def crm_row_to_record(
    row: dict,
    locator: str,
    fields: CRMFieldMap,
    acl: tuple[str, ...],
    config: IngestConfig | None = None,
    dayfirst: bool = True,
    date_conflict: bool = False,
) -> SourceRecord:
    config = config or IngestConfig()
    rid = f"crm:{row[fields.id]}"
    log = IssueLog(rid)

    def date_field(name: str, raw):
        parsed = parse_date(raw, dayfirst=dayfirst)
        if date_conflict and parsed.ok and "day_month_order_by_convention" in parsed.warnings:
            log.refuse(name, raw, "conflicting_date_conventions_in_file")
            return None
        return log.take(name, parsed)

    modified = date_field("updated_at", row.get(fields.modified))
    email = row.get(fields.email)
    facts = []

    def fact(name: str, value) -> None:
        if value not in (None, ""):
            facts.append(Fact(field=name, value=value, observed_at=modified, record_id=rid))

    fact("owner", row.get(fields.owner))
    row_currency = (row.get(fields.currency) or "").strip().upper() or None
    raw_value = row.get(fields.contract_value)
    if (
        row_currency
        and config.currency
        and row_currency != config.currency
        and raw_value not in (None, "")
    ):
        log.refuse("contract_value", raw_value, f"unexpected_currency:{row_currency}")
    else:
        amount = log.take(
            "contract_value", parse_amount(raw_value, expected_currency=config.currency)
        )
        fact("contract_value", amount.value if amount else None)
    renewal = date_field("renewal_date", row.get(fields.renewal_date))
    fact("renewal_date", renewal.isoformat() if renewal else None)
    fact("address", row.get(fields.street))
    phone = log.take("phone", parse_phone(row.get(fields.phone), config.default_country))
    return SourceRecord(
        record_id=rid,
        source="crm",
        locator=f"{locator}#{row[fields.id]}",
        name=row.get(fields.name),
        domain=business_domain(row.get(fields.website)) or business_domain(email),
        phone=phone,
        email=email,
        address=row.get(fields.street),
        city=row.get(fields.city),
        tax_id=row.get(fields.tax_id),
        updated_at=modified,
        facts=facts,
        acl=list(acl),
        issues=log.items,
    )
