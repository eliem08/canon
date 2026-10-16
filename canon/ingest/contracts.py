"""Contract connector: parses text extracted from contract PDFs (French or English).

Versions of the same contract number are linked: any version that a later one
explicitly supersedes ("annule et remplace", "supersedes and replaces") or that
is older than the highest version is marked `superseded`.
"""

from __future__ import annotations

import re
from pathlib import Path

from canon.ingest.common import business_domain, find_emails
from canon.ingest.config import IngestConfig
from canon.ingest.parsing import IssueLog, parse_amount, parse_date, parse_phone
from canon.models import Fact, SourceRecord

DEFAULT_CONTRACT_ACL = ("legal", "exec")

PATTERNS = {
    "number": r"(?:Contrat N°|Agreement No)\s*:?\s*(\S+)",
    "version": r"^Version\s*:?\s*(\d+)",
    "signed": r"(?:Date de signature|Signature date)\s*:?\s*([^\n]+)",
    "party": r"^(?:Le Client|Customer)\s*:\s*(.+)$",
    "party_ar": r"^الطرف الثاني\s*:\s*(.+)$",
    "tax_id": r"(?:ICE|Tax ID \(ICE\))\s*:?\s*(\d{15})",
    "address": r"^(?:Siège social|Registered office)\s*:\s*(.+)$",
    "contact": r"^Contact\s*:\s*(.+)$",
    # amounts and dates are captured loosely and validated by canon.ingest.parsing
    "value": r"(?:montant annuel est fixé à|annual fee is)\s*([^\n]+?)(?:\.\s|\.?\s*$)",
    "start": (
        r"(?:Date d'effet|Effective date)\s*:\s*([^\n]*?)"
        r"(?=\.?\s*(?:Date de renouvellement|Renewal date)|\.?\s*$)"
    ),
    "renewal": r"(?:Date de renouvellement|Renewal date)\s*:\s*([^\n]*?)\.?\s*$",
    "signatory": r"^(?:Représenté par|Represented by)\s*:\s*(.+)$",
    "supersedes": r"(?:annule et remplace|supersedes and replaces)\s+(?:la\s+)?version\s+(\d+)",
}


def _grab(text: str, key: str) -> str | None:
    m = re.search(PATTERNS[key], text, re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else None


def _where(text: str, key: str, locator: str) -> tuple[str | None, str | None]:
    """(`file#p<page>:L<line>`, the line's text) for a pattern; pages are split by form feeds."""
    m = re.search(PATTERNS[key], text, re.MULTILINE | re.IGNORECASE)
    if not m:
        return None, None
    before = text[: m.start(1)]
    page = before.count("\f") + 1
    line_start = max(before.rfind("\n"), before.rfind("\f")) + 1
    line = before.split("\f")[-1].count("\n") + 1
    end = text.find("\n", m.start(1))
    quote = text[line_start : end if end != -1 else len(text)].strip()
    return f"{locator}#p{page}:L{line}", quote[:300]


def parse_contract(
    text: str,
    record_id: str,
    locator: str,
    acl=DEFAULT_CONTRACT_ACL,
    config: IngestConfig | None = None,
) -> dict:
    """Return parsed fields plus a draft record (status fixed up by `load_contracts`)."""
    config = config or IngestConfig()
    dayfirst = config.dayfirst is not False
    log = IssueLog(record_id)

    def date_of(key: str, field: str):
        raw = _grab(text, key)
        return log.take(field, parse_date(raw, dayfirst=dayfirst)) if raw else None

    signed = date_of("signed", "signature_date")
    address_line = _grab(text, "address")
    address, city = address_line, None
    if address_line and "," in address_line:
        address, city = (s.strip() for s in address_line.rsplit(",", 1))
    contact = _grab(text, "contact") or ""
    emails = find_emails(contact)
    phone_part = re.split(r"T[ée]l\s*:", contact)
    phone = (
        log.take("phone", parse_phone(phone_part[1], config.default_country))
        if len(phone_part) > 1
        else None
    )
    raw_value = _grab(text, "value")
    amount = (
        log.take("contract_value", parse_amount(raw_value, expected_currency=config.currency), True)
        if raw_value
        else None
    )
    value = amount.value if amount else None
    facts = []

    number = _grab(text, "number")
    start = date_of("start", "contract_start")
    renewal = date_of("renewal", "renewal_date")

    def fact(name: str, v, key: str) -> None:
        # Contract terms are asserted for the whole contract period.
        if v not in (None, ""):
            ref, quote = _where(text, key, locator)
            facts.append(
                Fact(
                    field=name,
                    value=v,
                    observed_at=signed,
                    valid_until=renewal,
                    record_id=record_id,
                    source_ref=ref,
                    quote=quote,
                )
            )

    fact("contract_number", number, "number")
    fact("contract_value", value, "value")
    fact("contract_start", start.isoformat() if start else None, "start")
    fact("renewal_date", renewal.isoformat() if renewal else None, "renewal")
    fact("signatory", _grab(text, "signatory"), "signatory")
    fact("address", address, "address")
    record = SourceRecord(
        record_id=record_id,
        source="contract",
        locator=locator,
        name=_grab(text, "party"),
        alt_names=[n for n in [_grab(text, "party_ar")] if n],
        domain=business_domain(emails[0]) if emails else None,
        phone=phone,
        email=emails[0] if emails else None,
        address=address,
        city=city,
        tax_id=_grab(text, "tax_id"),
        updated_at=signed,
        facts=facts,
        acl=list(acl),
        issues=log.items,
    )
    version = _grab(text, "version")
    supersedes = _grab(text, "supersedes")
    return {
        "record": record,
        "number": number,
        "version": int(version) if version else 1,
        "supersedes": int(supersedes) if supersedes else None,
    }


def load_contracts(
    root: Path, acl=DEFAULT_CONTRACT_ACL, config: IngestConfig | None = None
) -> list[SourceRecord]:
    parsed = [
        parse_contract(p.read_text(encoding="utf-8"), f"contract:{p.stem}", str(p), acl, config)
        for p in sorted(Path(root).glob("*.txt"))
    ]
    by_number: dict[str, list[dict]] = {}
    for item in parsed:
        by_number.setdefault(item["number"] or item["record"].record_id, []).append(item)
    for versions in by_number.values():
        latest = max(v["version"] for v in versions)
        superseded = {v["supersedes"] for v in versions if v["supersedes"]}
        for v in versions:
            if v["version"] < latest or v["version"] in superseded:
                v["record"].status = "superseded"
    return [item["record"] for item in parsed]
