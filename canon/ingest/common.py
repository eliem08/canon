"""Parsing helpers shared by connectors: phones, domains, money, dates."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

FREE_MAIL_DOMAINS = frozenset(
    {
        "gmail.com", "googlemail.com", "hotmail.com", "hotmail.fr", "yahoo.com", "yahoo.fr",
        "outlook.com", "outlook.fr", "live.com", "live.fr", "icloud.com", "menara.ma",
    }
)  # fmt: skip

EMAIL_RE = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
PHONE_RE = re.compile(r"(?:\+|00)?[\d][\d ().\-]{7,}\d")
DMY_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")


def normalize_phone(raw: str | None, country_code: str = "212") -> str | None:
    """Return an E.164 phone (`+212522123456`) or None if it does not look like one."""
    if not raw:
        return None
    text = raw.replace("(0)", "")
    digits = re.sub(r"\D", "", text)
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 10:
        digits = country_code + digits[1:]
    if len(digits) < 9 or len(digits) > 15:
        return None
    return "+" + digits


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


_MONEY_RE = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[ .,  ]\d{3})+|\d+(?:[.,]\d+)?)\s*([km])?(?![\w])",
    re.IGNORECASE,
)


def parse_money(raw: str | float | int | None) -> float | None:
    """Parse amounts such as `450k MAD`, `1 426 000 MAD`, `1.200.000 DH`, `461,000`."""
    if raw is None:
        return None
    if isinstance(raw, int | float):
        return float(raw)
    best = None
    for number, suffix in _MONEY_RE.findall(raw):
        if re.fullmatch(r"\d{1,3}(?:[ .,  ]\d{3})+", number):
            value = float(re.sub(r"\D", "", number))
        else:
            value = float(number.replace(",", "."))
        if suffix:
            value *= 1_000 if suffix.lower() == "k" else 1_000_000
        best = value if best is None else max(best, value)
    return best


def parse_date(raw: str | None) -> date | None:
    """Parse ISO dates/datetimes and day-first `dd/mm/yyyy`."""
    if not raw:
        return None
    text = raw.strip()
    m = DMY_RE.search(text)
    if m:
        day, month, year = (int(g) for g in m.groups())
        return date(year, month, day)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def date_from_ts(ts: str | float) -> date:
    return datetime.fromtimestamp(float(ts), tz=UTC).date()


def find_emails(text: str) -> list[str]:
    return [m.group(0) for m in EMAIL_RE.finditer(text)]


def find_phones(text: str) -> list[str]:
    phones = []
    for m in PHONE_RE.finditer(text):
        phone = normalize_phone(m.group(0))
        if phone and not DMY_RE.search(m.group(0)):
            phones.append(phone)
    return phones
