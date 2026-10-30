"""Helpers shared by connectors. Value parsing lives in `canon.ingest.parsing`;
the functions here keep the simple `value | None` signatures for existing callers."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from canon.ingest.parsing import find_phones as _find_phones
from canon.ingest.parsing import parse_amount, parse_phone
from canon.ingest.parsing import parse_date as _parse_date

FREE_MAIL_DOMAINS = frozenset(
    {
        "gmail.com", "googlemail.com", "hotmail.com", "hotmail.fr", "yahoo.com", "yahoo.fr",
        "outlook.com", "outlook.fr", "live.com", "live.fr", "icloud.com", "menara.ma",
    }
)  # fmt: skip

EMAIL_RE = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
DMY_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")


def normalize_phone(raw: str | None, country_code: str = "212") -> str | None:
    """E.164 phone or None. Thin wrapper over `parsing.parse_phone` (which says why)."""
    return parse_phone(raw, default_country=country_code).value


def domain_of(raw: str | None) -> str | None:
    """Extract a lowercase host from a URL, bare domain or e-mail address."""
    if not raw:
        return None
    text = raw.strip().lower()
    if "@" in text:
        text = text.rsplit("@", 1)[1]
    text = re.sub(r"^[a-z]+://", "", text)
    text = text.split("/", 1)[0].split("?", 1)[0]
    text = text.removeprefix("www.")
    return text if "." in text else None


def business_domain(raw: str | None) -> str | None:
    """Like `domain_of`, but returns None for free-mail providers (gmail, ...)."""
    domain = domain_of(raw)
    return None if domain in FREE_MAIL_DOMAINS else domain


def parse_money(raw: str | float | int | None) -> float | None:
    """Single amount or None (refused/absent). Wrapper over `parsing.parse_amount`."""
    parsed = parse_amount(raw, expected_currency=None)
    return parsed.value.value if parsed.ok else None


def parse_date(raw: str | None, dayfirst: bool = True) -> date | None:
    """Single date or None (refused/absent). Wrapper over `parsing.parse_date`."""
    return _parse_date(raw, dayfirst=dayfirst).value


def date_from_ts(ts: str | float) -> date:
    return datetime.fromtimestamp(float(ts), tz=UTC).date()


def find_emails(text: str) -> list[str]:
    return [m.group(0) for m in EMAIL_RE.finditer(text)]


def find_phones(text: str, default_country: str | None = "212") -> list[str]:
    return _find_phones(text, default_country)
