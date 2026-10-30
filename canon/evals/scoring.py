"""Question routing and answer grading (free-text answers vs. ground-truth values)."""

from __future__ import annotations

import re
from datetime import date

from rapidfuzz import fuzz

from canon.ingest.common import find_phones, parse_date, parse_money
from canon.resolve.normalize import fold, normalize_address

# Multilingual cues per question type (EN / FR / Darija-in-Latin), checked in order.
TYPE_CUES = (
    ("owner", ("owner", "owns", "account manager", "responsable", "chkoun", "looks after",
               "handles", "handled by", "in charge", "s'occupe", "kaytkellef", "gere ")),
    ("renewal_date", ("renew", "renouvel", "tjedded", "echeance", "échéance")),
    ("phone", ("phone", "telephone", "téléphone", "numero", "numéro", "nemra", "number",
               "dial")),
    ("address", ("address", "adresse", "siege", "siège", "fin kayn", "located",
                 "head office", "offices")),
    ("contract_value", ("contract value", "montant", "ch7al", "how much", "valeur", "fee",
                        "per year", "par an", "annual", "worth", "combien")),
)  # fmt: skip

MONTHS = {
    **{m: i for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july", "august",
         "september", "october", "november", "december"], start=1)},
    **{m: i for i, m in enumerate(
        ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout",
         "septembre", "octobre", "novembre", "decembre"], start=1)},
}  # fmt: skip
UNKNOWN = {"", "unknown", "none", "n/a", "not found", "inconnu"}


def route(question: str) -> str | None:
    """The question type its wording points to, or None when no cue matches."""
    q = fold(question)
    for qtype, cues in TYPE_CUES:
        if any(fold(c) in q for c in cues):
            return qtype
    return None


def classify(question: str) -> str:
    return route(question) or "contract_value"


def _parse_any_date(text: str) -> date | None:
    d = parse_date(text) if re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}", text) else None
    if d:
        return d
    t = fold(text)
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th|er)?\s+([a-z]+)\s+(\d{4})", t)
    if m and m.group(2) in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
    m = re.search(r"([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", t)
    if m and m.group(1) in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
    return None


def _money(text: str) -> float | None:
    # ignore 4-digit years so "valid until 2027" is not read as an amount
    return parse_money(re.sub(r"\b(19|20)\d{2}\b(?![ .,]\d{3})", " ", text))


def is_correct(qtype: str, expected, answer: str | None) -> bool:
    if answer is None or fold(str(answer)).strip(" .") in UNKNOWN:
        return False
    answer = str(answer)
    if qtype == "contract_value":
        got = _money(answer)
        return got is not None and abs(got - float(expected)) <= 0.005 * float(expected)
    if qtype == "renewal_date":
        got = _parse_any_date(answer)
        return got is not None and got.isoformat() == str(expected)
    if qtype == "owner":
        exp = fold(str(expected))
        return exp in fold(answer) or (fold(answer).strip() and fold(answer).strip() in exp
                                       and len(fold(answer).split()) >= 2)  # fmt: skip
    if qtype == "phone":
        phones = find_phones(answer) or ([answer] if re.sub(r"\D", "", answer) else [])
        want = re.sub(r"\D", "", str(expected))[-9:]
        return any(re.sub(r"\D", "", p)[-9:] == want for p in phones)
    if qtype == "address":
        exp, got = normalize_address(str(expected)), normalize_address(answer)
        return bool(got) and fuzz.token_set_ratio(exp, got) >= 90
    raise ValueError(f"unknown question type {qtype}")
