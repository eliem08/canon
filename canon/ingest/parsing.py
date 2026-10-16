"""Hardened value parsers: amounts, dates and phone numbers.

Policy: a wrong value that looks right is worse than a missing one. Every parser
returns a `Parsed` result that holds either a value or the reason it refused one;
ambiguous, malformed or implausible input is refused (and later quarantined by the
connector with its raw text), never guessed. Nothing here raises on bad input.

Conventions that cannot be inferred from a single value are explicit parameters:
`dayfirst` for numeric dates, `default_country` for national phone numbers and
`expected_currency` for amounts.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Parsed[T]:
    raw: str
    value: T | None = None
    reason: str | None = None  # machine-readable code, set when value is None
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.value is not None


# ---------------------------------------------------------------- text cleanup

_TRANSLATE = {
    **{0x0660 + i: str(i) for i in range(10)},  # Arabic-Indic digits
    **{0x06F0 + i: str(i) for i in range(10)},  # Extended Arabic-Indic (Persian/Urdu)
    0x066C: ",",  # Arabic thousands separator
    0x066B: ".",  # Arabic decimal separator
    0x060C: ",",  # Arabic comma
    0x00A0: " ",
    0x2007: " ",
    0x2009: " ",
    0x202F: " ",  # no-break / figure / thin / narrow spaces
    0x2019: "'",
    0x2212: "-",
    0x2013: "-",
    0x2014: "-",  # right quote, minus, dashes
}


def clean_text(raw: object) -> str:
    """NFKC, ASCII digits, plain spaces and separators. Keeps letters (incl. Arabic)."""
    text = unicodedata.normalize("NFKC", str(raw))
    return text.translate(_TRANSLATE).strip()


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[ً-ٰٟ]", "", text)  # Arabic diacritics
    return text.translate(str.maketrans("أإآ", "ااا")).lower()


# ---------------------------------------------------------------- amounts

CURRENCY_PATTERNS = (
    ("MAD", r"\bmad\b|\bdhs?\b|\bdirhams?\b|درهم|دراهم|د\.?\s?م\.?"),
    ("EUR", r"\beur\b|\beuros?\b|€"),
    ("USD", r"\busd\b|\bus\$|\bdollars?\b|\$"),
    ("GBP", r"\bgbp\b|£|\bpounds?\b"),
)
MULTIPLIERS = (
    (r"milliards?|billions?|bn|mds?|مليار", Decimal(10) ** 9),
    (r"millions?|m|mio|مليون|ملايين", Decimal(10) ** 6),
    (r"k|mille|ألف|الف|آلاف", Decimal(10) ** 3),
)
_MULT_RE = "|".join(p for p, _ in MULTIPLIERS)
# A number: digit groups with optional separators. Validation happens in _number().
_NUM = r"\d(?:\d|[.,' ](?=\d))*"  # a separator must sit between digits
# Digits glued to a word before them ("m3a" in Darija, "U07" in a mention) are not numbers.
_AMOUNT_RE = re.compile(
    rf"(?<![^\W_])(?P<sign>-(?=\d)|\(\s*)?(?P<num>{_NUM})"
    rf"(?:\s*(?P<mult>{_MULT_RE})(?![^\W\d_]))?(?P<tail>[^\W\d_]*)",
    re.IGNORECASE,
)
TAX_QUALIFIERS = {
    "ht": "excl_vat",
    "hors taxes": "excl_vat",
    "ttc": "incl_vat",
    "tva comprise": "incl_vat",
}


@dataclass(frozen=True)
class Amount:
    value: float
    currency: str | None  # None when the text names no currency
    tax_basis: str | None = None  # excl_vat | incl_vat | None


def _number(token: str) -> tuple[Decimal | None, str | None, tuple[str, ...]]:
    """Interpret one digit/separator token. Returns (value, refusal reason, warnings)."""
    t = token.strip()
    if " " in t or "'" in t:  # spaces/apostrophes can only be thousands separators
        m = re.fullmatch(r"(\d{1,3}(?:[ ']\d{3})+)(?:[.,](\d{1,2}))?", t)
        if not m:
            return None, "malformed_grouping", ()
        whole = re.sub(r"[ ']", "", m.group(1))
        return Decimal(f"{whole}.{m.group(2) or 0}"), None, ()
    dots, commas = t.count("."), t.count(",")
    if not dots and not commas:
        return Decimal(t), None, ()
    if dots and commas:  # the last separator is the decimal one; the other groups thousands
        dec_sep = "." if t.rfind(".") > t.rfind(",") else ","
        grp_sep = "," if dec_sep == "." else "."
        whole, _, frac = t.rpartition(dec_sep)
        if dec_sep in whole or not 1 <= len(frac) <= 2:
            return None, "ambiguous_separator", ()
        if not re.fullmatch(rf"\d{{1,3}}(?:{re.escape(grp_sep)}\d{{3}})+", whole):
            return None, "malformed_grouping", ()
        return Decimal(f"{whole.replace(grp_sep, '')}.{frac}"), None, ()
    sep = "." if dots else ","
    if t.count(sep) > 1:  # repeated separator: thousands grouping only
        if not re.fullmatch(rf"\d{{1,3}}(?:{re.escape(sep)}\d{{3}})+", t):
            return None, "malformed_grouping", ()
        return Decimal(t.replace(sep, "")), None, ()
    whole, _, frac = t.partition(sep)
    if len(frac) in (1, 2) or whole == "0":
        return Decimal(f"{whole}.{frac}"), None, ()
    if len(frac) == 3 and 1 <= len(whole) <= 3:
        # "450.000" / "1,426": read as thousands (common FR/EN money usage); flagged
        return Decimal(whole + frac), None, ("single_separator_read_as_thousands",)
    return None, "ambiguous_separator", ()


def _currency(text: str) -> tuple[str | None, list[str]]:
    found = [code for code, pat in CURRENCY_PATTERNS if re.search(pat, text, re.IGNORECASE)]
    return (found[0] if len(found) == 1 else None), found


def _tax_basis(text: str) -> str | None:
    low = _fold(text)
    for word, basis in TAX_QUALIFIERS.items():
        if re.search(rf"\b{word}\b", low):
            return basis
    return None


def find_amounts(text: str, require_marker: bool = False) -> list[Parsed[Amount]]:
    """Every amount-like token in `text`. With `require_marker`, bare numbers without a
    currency, multiplier or digit grouping are skipped (free text is full of numbers)."""
    clean = clean_text(text)
    scrub = clean
    if require_marker:  # free text: dates, percentages and phone-like runs are not amounts
        scrub = re.sub(
            r"(?<![\d.,])(?:\d{1,4}[/.\-]\d{1,2}[/.\-]\d{2,4}"
            r"|\d+(?:[.,]\d+)?\s*%|\+\d[\d ]{7,})(?![.,]?\d)",
            " ",
            clean,
        )
    currency, all_found = _currency(scrub)
    out = []
    for m in _AMOUNT_RE.finditer(scrub):
        raw = m.group(0).strip()
        if m.group("tail") and not re.fullmatch(r"(?i)mad|dhs?|eur|usd|gbp", m.group("tail")):
            if not require_marker:  # in free text, "3la" or "2nd" are just words
                out.append(Parsed(raw, reason="malformed_amount"))
            continue
        number, reason, warnings = _number(m.group("num"))
        if number is None:
            out.append(Parsed(raw, reason=reason))
            continue
        marked = bool(
            m.group("mult") or m.group("tail") or re.search(r"[.,' ]\d{3}", m.group("num"))
        )
        if require_marker and not marked and not currency:
            continue
        if require_marker and not marked and re.fullmatch(r"(19|20)\d\d", m.group("num")):
            continue  # a year
        if m.group("sign"):
            out.append(Parsed(raw, reason="negative_or_signed"))
            continue
        mult = next(
            (
                f
                for p, f in MULTIPLIERS
                if m.group("mult") and re.fullmatch(p, m.group("mult"), re.I)
            ),
            Decimal(1),
        )
        value = number * mult
        out.append(
            Parsed(raw, Amount(float(value), currency, _tax_basis(clean)), warnings=warnings)
            if len(all_found) <= 1
            else Parsed(raw, reason="mixed_currencies")
        )
    return out


def parse_amount(
    raw: object,
    expected_currency: str | None = "MAD",
    max_value: float = 1e12,
    require_marker: bool = False,
) -> Parsed[Amount]:
    """Parse a field or phrase that should contain exactly one amount."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return Parsed("", reason="empty")
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        if raw < 0:
            return Parsed(str(raw), reason="negative_or_signed")
        if raw > max_value:
            return Parsed(str(raw), reason="implausible_value")
        return Parsed(str(raw), Amount(float(raw), None))
    text = str(raw)
    found = find_amounts(text, require_marker=require_marker)
    if not found:
        return Parsed(text, reason="no_amount")
    values = {p.value.value for p in found if p.ok}
    if len(values) > 1 or (values and any(not p.ok for p in found)):
        return Parsed(text, reason="multiple_amounts")
    first = found[0]
    if not first.ok:
        return Parsed(text, reason=first.reason)
    amount = first.value
    if amount.value > max_value:
        return Parsed(text, reason="implausible_value")
    if expected_currency and amount.currency and amount.currency != expected_currency:
        return Parsed(text, reason=f"unexpected_currency:{amount.currency}")
    warnings = first.warnings + (() if amount.currency else ("currency_assumed",))
    return Parsed(text, amount, warnings=warnings)


# ---------------------------------------------------------------- dates

_MONTHS = {
    # French
    "janvier": 1, "janv": 1, "fevrier": 2, "fevr": 2, "fev": 2, "mars": 3, "avril": 4, "avr": 4,
    "mai": 5, "juin": 6, "juillet": 7, "juil": 7, "aout": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "decembre": 12,
    # English
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9,
    "sept": 9, "sep": 9, "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12,
    "dec": 12,
    # Arabic: Moroccan, Middle-Eastern and Algerian/Tunisian forms (folded: no hamza on alef)
    "يناير": 1, "جانفي": 1, "فبراير": 2, "فيفري": 2, "مارس": 3, "ابريل": 4, "افريل": 4,
    "ماي": 5, "مايو": 5, "يونيو": 6, "جوان": 6, "يوليوز": 7, "يوليو": 7, "جويليه": 7,
    "جويلية": 7, "غشت": 8, "اغسطس": 8, "اوت": 8, "شتنبر": 9, "سبتمبر": 9, "اكتوبر": 10,
    "نونبر": 11, "نوفمبر": 11, "دجنبر": 12, "ديسمبر": 12,
}  # fmt: skip
_MONTH_RE = "|".join(sorted((re.escape(m) for m in _MONTHS), key=len, reverse=True))
_DATE_PATTERNS = (
    ("iso", re.compile(r"(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)")),
    ("numeric", re.compile(r"(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})(?!\d)")),
    (
        "day_month_year",
        re.compile(
            rf"(?<!\d)(\d{{1,2}})(?:er|st|nd|rd|th|e|eme)?\s+(?:de\s+|of\s+)?({_MONTH_RE})\.?,?\s+(\d{{4}})(?!\d)"
        ),
    ),
    (
        "month_day_year",
        re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})(?!\d)"),
    ),
)
_TWO_DIGIT_YEAR = re.compile(r"(?<!\d)\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2}(?![\d/.\-])")
_MONTH_YEAR = re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{4}})\b")


def _make_date(
    year: int, month: int, day: int, years: tuple[int, int]
) -> tuple[date | None, str | None]:
    if not years[0] <= year <= years[1]:
        return None, "implausible_year"
    try:
        return date(year, month, day), None
    except ValueError:
        return None, "impossible_date"


def parse_date(
    raw: object, dayfirst: bool = True, years: tuple[int, int] = (1990, 2100)
) -> Parsed[date]:
    """Parse a field or phrase that should contain exactly one calendar date."""
    if raw is None or not str(raw).strip():
        return Parsed("", reason="empty")
    text = clean_text(raw)
    low = _fold(text)
    found: list[tuple[date | None, str | None, str | None]] = []  # (value, reason, warning)
    spans: list[tuple[int, int]] = []
    for kind, pattern in _DATE_PATTERNS:
        for m in pattern.finditer(low):
            if any(s <= m.start() < e for s, e in spans):
                continue
            spans.append(m.span())
            g = m.groups()
            warning = None
            if kind == "iso":
                y, mo, d = int(g[0]), int(g[1]), int(g[2])
            elif kind == "numeric":
                a, b, y = int(g[0]), int(g[1]), int(g[2])
                d, mo = (a, b) if dayfirst else (b, a)
                if a <= 12 and b <= 12 and a != b:
                    warning = "day_month_order_by_convention"
            elif kind == "day_month_year":
                d, mo, y = int(g[0]), _MONTHS[g[1]], int(g[2])
            else:
                mo, d, y = _MONTHS[g[0]], int(g[1]), int(g[2])
            value, reason = _make_date(y, mo, d, years)
            found.append((value, reason, warning))
    if not found:
        if _TWO_DIGIT_YEAR.search(low):
            return Parsed(text, reason="two_digit_year")
        if _MONTH_YEAR.search(low):
            return Parsed(text, reason="month_only")
        return Parsed(text, reason="no_date")
    values = {v for v, _, _ in found if v}
    if len(found) > 1 and len(values | {r for _, r, _ in found if r}) > 1:
        return Parsed(text, reason="multiple_dates")
    value, reason, warning = found[0]
    if value is None:
        return Parsed(text, reason=reason)
    return Parsed(text, value, warnings=(warning,) if warning else ())


def infer_dayfirst(samples: list[object]) -> tuple[bool | None, bool]:
    """Infer the day/month order of a column of numeric dates.

    Returns (dayfirst, conflict): dayfirst is None when the samples give no evidence;
    conflict is True when some samples can only be day-first and others month-first."""
    first_big = second_big = False
    pattern = _DATE_PATTERNS[1][1]
    for s in samples:
        for m in pattern.finditer(clean_text(s) if s is not None else ""):
            a, b = int(m.group(1)), int(m.group(2))
            first_big |= a > 12
            second_big |= b > 12
    if first_big and second_big:
        return None, True
    if first_big:
        return True, False
    if second_big:
        return False, False
    return None, False


# ---------------------------------------------------------------- phones

# calling code -> (allowed national significant number lengths, allowed first digits or "")
COUNTRY_RULES: dict[str, tuple[tuple[int, ...], str]] = {
    "212": ((9,), "5678"),  # Morocco
    "213": ((8, 9), ""),  # Algeria
    "216": ((8,), ""),  # Tunisia
    "33": ((9,), "123456789"),  # France
    "34": ((9,), ""),  # Spain
    "32": ((8, 9), ""),  # Belgium
    "41": ((9,), ""),  # Switzerland
    "44": ((10,), ""),  # UK
    "49": ((10, 11), ""),  # Germany
    "1": ((10,), "23456789"),  # NANP
    "971": ((8, 9), ""),  # UAE
    "966": ((9,), ""),  # Saudi Arabia
    "221": ((9,), ""),  # Senegal
}
_EXT_RE = re.compile(r"(?i)\s*(?:ext\.?|extension|poste|p\.|x|#|داخلي)\s*(\d{1,6})\s*$")
_SPLIT_RE = re.compile(r"\s*(?:/|;|,|\||\bou\b|\bor\b|\bet\b|\band\b)\s*", re.IGNORECASE)


def _is_placeholder(nsn: str) -> bool:
    return len(set(nsn)) == 1 or nsn in "01234567890123456789" or nsn in "98765432109876543210"


def _one_phone(text: str, default_country: str | None) -> Parsed[str]:
    if re.search(r"(?i)\bfax\b|\bfacsimile\b|فاكس", text):
        return Parsed(text, reason="fax_number")
    body = re.sub(
        r"(?i)^\s*(?:t[ée]l(?:[ée]phone)?|phone|tel|mob(?:ile)?|gsm|hatif|هاتف)\.?\s*:?\s*",
        "",
        text,
    )
    if re.search(r"[^\W\d_]", body):
        return Parsed(text, reason="contains_letters")
    body = body.replace("(0)", "")
    plus = body.lstrip().startswith("+")
    digits = re.sub(r"\D", "", body)
    if not digits:
        return Parsed(text, reason="no_phone")
    if plus or digits.startswith("00"):
        digits = digits[2:] if not plus else digits
        for size in (3, 2, 1):
            cc, nsn = digits[:size], digits[size:]
            if cc in COUNTRY_RULES:
                lengths, prefixes = COUNTRY_RULES[cc]
                if len(nsn) not in lengths:
                    return Parsed(text, reason="bad_length_for_country")
                if prefixes and nsn[0] not in prefixes:
                    return Parsed(text, reason="invalid_prefix")
                break
        else:
            if not 8 <= len(digits) <= 15:
                return Parsed(text, reason="bad_length")
            cc, nsn = "", digits
        if _is_placeholder(nsn):
            return Parsed(text, reason="placeholder")
        return Parsed(text, "+" + digits, warnings=() if cc else ("country_unverified",))
    if digits.startswith("0"):
        if not default_country or default_country not in COUNTRY_RULES:
            return Parsed(text, reason="no_default_country")
        lengths, prefixes = COUNTRY_RULES[default_country]
        nsn = digits[1:]
        if len(nsn) not in lengths:
            return Parsed(text, reason="bad_national_format")
        if _is_placeholder(nsn):
            return Parsed(text, reason="placeholder")
        if prefixes and nsn[0] not in prefixes:
            return Parsed(text, reason="invalid_prefix")
        return Parsed(text, f"+{default_country}{nsn}")
    return Parsed(text, reason="missing_country_or_trunk_prefix")


def parse_phone(raw: object, default_country: str | None = "212") -> Parsed[str]:
    """Parse a phone field. Several numbers -> the first valid one, others as warnings."""
    if raw is None or not str(raw).strip():
        return Parsed("", reason="empty")
    text = clean_text(raw)
    warnings: list[str] = []
    ext = _EXT_RE.search(text)
    if ext:
        warnings.append(f"extension={ext.group(1)}")
        text_wo_ext = text[: ext.start()]
    else:
        text_wo_ext = text
    results = [
        _one_phone(part, default_country) for part in _SPLIT_RE.split(text_wo_ext) if part.strip()
    ]
    valid = list(dict.fromkeys(r.value for r in results if r.ok))
    if not valid:
        return Parsed(text, reason=results[0].reason if results else "no_phone")
    warnings += [f"alternate={v}" for v in valid[1:]]
    first = next(r for r in results if r.ok)
    return Parsed(text, valid[0], warnings=tuple(warnings) + first.warnings)


_PHONE_CANDIDATE = re.compile(r"(?:\+|00)?\d[\d ().\-]{7,}\d")


def find_phones(text: str, default_country: str | None = "212") -> list[str]:
    """Valid phone numbers mentioned in free text (invalid candidates are dropped)."""
    clean = clean_text(text)
    out = []
    for m in _PHONE_CANDIDATE.finditer(clean):
        candidate = m.group(0)
        if parse_date(candidate).ok:
            continue
        parsed = parse_phone(candidate, default_country)
        if parsed.ok and parsed.value not in out:
            out.append(parsed.value)
    return out


# ---------------------------------------------------------------- issue logging

# Reasons that just mean "nothing there" (not a refusal worth a human's time).
# ---------------------------------------------------------------- identifiers

_ID_SEPARATORS = re.compile(r"[\s.\-/]")


def parse_identifier(raw: object) -> Parsed[str]:
    """A registry identifier (tax id / ICE, company number). Identifiers are text: a value that
    arrives as a number (spreadsheets do this) may have lost leading zeros, so it is refused.
    Spaces, dots, dashes and slashes between characters are removed."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return Parsed("", reason="empty")
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        return Parsed(str(raw), reason="identifier_stored_as_number")
    text = clean_text(raw).strip()
    compact = _ID_SEPARATORS.sub("", text)
    if not compact.isalnum():
        return Parsed(text, reason="malformed_identifier")
    return Parsed(text, compact.upper())


ABSENT_REASONS = frozenset({"empty", "no_amount", "no_date", "no_phone"})
# Warnings worth surfacing: the value was used, but under an assumption.
NOTABLE_WARNINGS = ("single_separator_read_as_thousands", "country_unverified", "alternate=")


class IssueLog:
    """Collects quarantined values and notable warnings for one source record."""

    def __init__(self, record_id: str) -> None:
        from canon.models import ParseIssue  # local import: models must not depend on parsing

        self._issue = ParseIssue
        self.record_id = record_id
        self.items: list = []

    def refuse(self, field: str, raw: object, reason: str) -> None:
        self.items.append(
            self._issue(record_id=self.record_id, field=field, raw=str(raw)[:300], reason=reason)
        )

    def take(self, field: str, parsed: Parsed, report_absent: bool = False):
        """Return the parsed value, or None after logging why it was refused."""
        if not parsed.ok:
            if report_absent or parsed.reason not in ABSENT_REASONS:
                self.refuse(field, parsed.raw, parsed.reason or "unparseable")
            return None
        for w in parsed.warnings:
            if w.startswith(NOTABLE_WARNINGS):
                self.items.append(
                    self._issue(
                        record_id=self.record_id,
                        field=field,
                        raw=parsed.raw[:300],
                        reason=w,
                        severity="warning",
                    )
                )
        return parsed.value
