"""Contract connector: parses contract text (French or English) from .txt, PDF, DOCX or scans.

Versions of the same contract number are linked: any version that a later one
explicitly supersedes ("annule et remplace", "supersedes and replaces") or that
is older than the highest version is marked `superseded`.
"""

from __future__ import annotations

import re
from pathlib import Path

from canon.ingest.common import business_domain, find_emails
from canon.ingest.config import IngestConfig
from canon.ingest.contract_terms import Term, read_terms
from canon.ingest.documents import OCRConfig, extract_text, folder_acl, iter_documents
from canon.ingest.parsing import IssueLog, parse_amount, parse_date, parse_phone
from canon.models import Fact, ParseIssue, SourceRecord

DEFAULT_CONTRACT_ACL = ("legal", "exec")

PATTERNS = {
    "number": r"(?:Contrat N°|Agreement No)\s*:?\s*(\S+)",
    "version": r"^Version\s*:?\s*(\d+)",
    "signed": r"(?:Date de signature|Signature date)\s*:?\s*([^\n]+)",
    "party": r"^(?:Le Client|Customer)\s*:\s*(.+)$",
    # OCR may reorder a right-to-left line, so take the whole line and drop the label words
    "party_ar": r"^(.*الطرف.*)$",
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
    return m.group(1).split("\f")[0].strip() if m else None  # never read across a page break


_AR_LABEL = {"الطرف", "الثاني", ":"}


def _arabic_party(text: str) -> str | None:
    line = _grab(text, "party_ar")
    if not line:
        return None
    words = [
        w.strip(":")
        for w in line.replace(":", " : ").split()
        if w not in _AR_LABEL and re.search(r"[\u0600-\u06ff]", w)
    ]
    return " ".join(w for w in words if w) or None


def _where(text: str, key: str, locator: str) -> tuple[str | None, str | None]:
    """(`file#p<page>:L<line>`, the line's text) for a pattern; pages are split by form feeds."""
    m = re.search(PATTERNS[key], text, re.MULTILINE | re.IGNORECASE)
    return _cite(text, m.start(1), locator) if m else (None, None)


def _cite(text: str, pos: int, locator: str) -> tuple[str, str]:
    before = text[:pos]
    page = before.count("\f") + 1
    line_start = max(before.rfind("\n"), before.rfind("\f")) + 1
    line = before.split("\f")[-1].count("\n") + 1
    end = min(i for i in (text.find("\n", pos), text.find("\f", pos), len(text)) if i != -1)
    quote = text[line_start:end].strip()
    if len(quote) > 300:  # prose: one long line per paragraph; quote around the value
        lo = max(line_start, pos - 120)
        quote = text[lo : min(end, lo + 300)].strip()
    return f"{locator}#p{page}:L{line}", quote


def _fold_name(name: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def counterparty(parties: list[str], own_names: tuple[str, ...]) -> str | None:
    """The one party that is not the deployment itself; None when that is not clear-cut."""
    if not own_names:
        return None
    from rapidfuzz import fuzz

    own = [_fold_name(n) for n in own_names]
    others = [
        p for p in parties if not any(fuzz.token_set_ratio(_fold_name(p), o) >= 90 for o in own)
    ]
    return others[0] if len(others) == 1 and len(others) < len(parties) else None


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

    # free-form contracts: the template lines below win when present (see contract_terms.py)
    terms = read_terms(text, config.dayfirst)
    generic: dict[str, Term] = {}

    def fallback(value, field: str, term: Term | None):
        if value is not None or term is None:
            return value
        generic[field] = term
        return term.value

    signed = fallback(date_of("signed", "signature_date"), "signature_date", terms.agreement_date)
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
    start = fallback(date_of("start", "contract_start"), "contract_start", terms.effective_date)
    renewal = fallback(date_of("renewal", "renewal_date"), "renewal_date", terms.end_date)
    for field, raw, reason in terms.refused:
        if field not in generic and not any(i.field == field for i in log.items):
            log.refuse(field, raw, reason)
    for field, term in generic.items():
        for w in term.warnings:
            log.items.append(
                ParseIssue(
                    record_id=record_id, field=field, raw=str(term.value), reason=w,
                    severity="warning",
                )
            )  # fmt: skip

    def fact(name: str, v, key: str) -> None:
        # Contract terms are asserted for the whole contract period.
        if v not in (None, ""):
            if name in generic:
                ref, quote = _cite(text, generic[name].start, locator)
            else:
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
    parties = [p.value for p in terms.parties]
    record = SourceRecord(
        record_id=record_id,
        source="contract",
        locator=locator,
        name=_grab(text, "party") or counterparty(parties, config.own_names),
        parties=parties,
        alt_names=[n for n in [_arabic_party(text)] if n],
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
    root: Path,
    acl=DEFAULT_CONTRACT_ACL,
    config: IngestConfig | None = None,
    ocr: OCRConfig | None = None,
    unreadable: list[ParseIssue] | None = None,
) -> list[SourceRecord]:
    """Every document under `root` (.txt, .pdf, .docx, scans), recursively.

    Access comes from the nearest `_acl.json` sidecar, else `acl`. Documents with no readable text
    become `ParseIssue`s in `unreadable` instead of empty records."""
    root = Path(root)
    parsed = []
    seen: set[str] = set()
    for path in iter_documents(root):
        rel = path.relative_to(root)
        rid = f"contract:{rel.with_suffix('').as_posix()}"
        if rid in seen:  # same name, two formats
            rid = f"contract:{rel.as_posix()}"
        seen.add(rid)
        doc = extract_text(path, ocr)
        if doc.method == "none":
            for reason, detail in doc.issues or [("no_text", "")]:
                issue = ParseIssue(record_id=rid, field="document", raw=detail, reason=reason)
                if unreadable is not None:
                    unreadable.append(issue)
            continue
        item = parse_contract(doc.text, rid, str(path), folder_acl(path, root, acl), config)
        if doc.denoised and item["record"].alt_names:
            # denoising erases the dots that distinguish Arabic letters: refuse, don't guess
            doc.issues.append(
                ("arabic_unreliable_after_denoise", ", ".join(item["record"].alt_names))
            )
            item["record"].alt_names = []
        item["record"].issues += [
            ParseIssue(record_id=rid, field="document", raw=d, reason=r, severity="warning")
            for r, d in doc.issues
        ]
        parsed.append(item)
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
