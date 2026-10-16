"""Fact extraction from free-text messages (Slack, e-mail bodies).

Rules first: each field needs a *cue* (a phrase that asserts the fact) and no *blocker* (a phrase
that makes the number or date mean something else: an invoice, a discount, a meeting, a
proposal). Questions and hedged messages assert nothing. Values are read with the hardened
parsers, so an ambiguous value is refused, not guessed.

An optional LLM extractor can fill fields the rules left empty. Its output is never trusted:
a value is kept only if the same parsers find it verbatim in the message, and an owner only
if it is a known user mentioned in the message.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from canon.ingest.parsing import IssueLog, _fold, find_amounts, parse_amount, parse_date

FIELDS = ("owner", "contract_value", "renewal_date")


def _rx(*patterns: str) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)


@dataclass(frozen=True)
class ExtractionRules:
    """Multilingual (FR / EN / Darija / Arabic) cue and blocker patterns, matched on folded text."""

    owner_cues: re.Pattern[str] = _rx(  # noqa: RUF009 (compiled patterns are immutable)
        r"\b(account )?owner\b",
        r"\baccount manager\b",
        r"\bkam\b",
        r"\bownership\b",
        r"\btakes? over\b",
        r"\breprend (le compte|le dossier|le client)\b",
        r"\bprend le relais\b",
        r"\bresponsable (du compte|commercial)",
        r"\bgere(e)? (par|le compte)\b",
        r"\bqui gere\b",
        r"\b(re)?attribue\b|\breassigne\b",
        r"\bpassation\b",
        r"\bcompte\b.{0,40}\bpasse a\b",
        r"\bkatgeri\b|\bkaygeri\b",
    )
    owner_blockers: re.Pattern[str] = _rx(  # noqa: RUF009 (compiled patterns are immutable)
        r"\b(tache|task|ticket|action|relance|demo|facture|invoice)\b",
        r"\bwas\b|\buntil\b|\bancien(ne)?\b|\bformer\b|\bprevious\b",
        r"\ba confirmer\b|\btbc\b|\bmaybe\b|\bpeut-etre\b",
    )
    value_cues: re.Pattern[str] = _rx(  # noqa: RUF009 (compiled patterns are immutable)
        r"\bcontra(t|ct)\b",
        r"\bdeal\b",
        r"\bsigne\b|\bsigned\b|\bclosed\b",
        r"\bmontant annuel\b|\bannuel(s|le)?\b|\bannual\b",
        r"\bpar an\b|/an\b|/year\b|\bper year\b|\bacv\b",
        r"\bvaleur du contrat\b|\bavenant\b",
        r"\btla3\b",
        r"عقد|العقد",
    )
    value_blockers: re.Pattern[str] = _rx(  # noqa: RUF009 (compiled patterns are immutable)
        r"\bfactur|\binvoice\b",
        r"\bremise\b|\bdiscount\b|\bavoir\b|\brabais\b",
        r"\bmrr\b|\bmensuel|\bmonthly\b|\bpar mois\b|/mois\b",
        r"\bbudget\b|\bpropos|\bproposal\b|\boffre\b|\bdevis\b|\bquote\b",
        r"\bpenalite\b|\bacompte\b|\bdeposit\b|\bpaye\b|\bpaid\b|\bpaiement\b|\bpayment\b",
        r"\bsi on\b|\bif we\b|\bconcurrent\b|\bcompetitor\b",
        r"\brien (n'est )?signe\b|\bpas (encore )?signe\b|\bnot signed\b",
    )
    renewal_cues: re.Pattern[str] = _rx(  # noqa: RUF009 (compiled patterns are immutable)
        r"\brenouvel",
        r"\brenew",
        r"\becheance\b|\bexpire",
        r"\bend date\b|\bfin de contrat\b",
        r"\bjusqu'au\b",
        r"\btajdid\b",
        r"تجديد",
    )
    renewal_blockers: re.Pattern[str] = _rx(  # noqa: RUF009 (compiled patterns are immutable)
        r"\bcall\b|\breunion\b|\bmeeting\b|\bpoint\b|\bdemo\b|\brdv\b",
        r"\bfactur|\binvoice\b|\bpaiement\b|\bpayment\b|\bpayer\b",
        r"\blivraison\b|\bdelivery\b",
        r"\bsigne le\b|\bsigned on\b",
    )
    question: re.Pattern[str] = _rx(  # noqa: RUF009 (compiled patterns are immutable)
        r"\?\s*$", r"^\s*(chkon|wach|est-ce que|who)\b", r"\?\s"
    )


# counts and durations: "3 ans", "40 utilisateurs", "10h" are not amounts
_COUNTS = re.compile(
    r"(?<![\d.,])\d+\s*(?:ans?|years?|mois|months?|jours?|days?|utilisateurs|users|sites|"
    r"employes|employés|agences|licences|h)\b",
    re.IGNORECASE,
)
_MENTION = re.compile(r"<@(U\w+)>")
_ORDINAL = re.compile(r"\b(\d{1,2})(?:er|st|nd|rd|th)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Extracted:
    field: str
    value: str | float
    quote: str  # the message text the value was read from


class TextModel(Protocol):
    def complete(self, prompt: str) -> str: ...


def resolve_owner(text: str, users: dict[str, str]) -> str | None:
    """The single known user a message names: a `<@U..>` mention, else a unique first name."""
    mentioned = {users[u] for u in _MENTION.findall(text) if u in users}
    if mentioned:
        return mentioned.pop() if len(mentioned) == 1 else None
    folded = _fold(text)
    named = {
        full
        for full in users.values()
        if re.search(rf"\b{re.escape(_fold(full.split()[0]))}\b", folded)
    }
    return named.pop() if len(named) == 1 else None


def _amount(text: str, currency: str | None, log: IssueLog):
    return log.take(
        "contract_value",
        parse_amount(_COUNTS.sub(" ", text), expected_currency=currency, require_marker=True),
    )


def _date(text: str, dayfirst: bool, log: IssueLog):
    clean = _ORDINAL.sub(r"\1", _MENTION.sub(" ", text))
    return log.take("renewal_date", parse_date(clean, dayfirst=dayfirst))


def extract_rules(
    text: str,
    users: dict[str, str],
    log: IssueLog,
    currency: str | None = "MAD",
    dayfirst: bool = True,
    rules: ExtractionRules | None = None,
) -> list[Extracted]:
    rules = rules or ExtractionRules()
    low = _fold(text)
    if rules.question.search(low):
        return []
    out = []
    if rules.owner_cues.search(low) and not rules.owner_blockers.search(low):
        owner = resolve_owner(text, users)
        if owner:
            out.append(Extracted("owner", owner, text))
    if rules.renewal_cues.search(low) and not rules.renewal_blockers.search(low):
        when = _date(text, dayfirst, log)
        if when:
            out.append(Extracted("renewal_date", when.isoformat(), text))
    if rules.value_cues.search(low) and not rules.value_blockers.search(low):
        amount = _amount(text, currency, log)
        if amount:
            out.append(Extracted("contract_value", amount.value, text))
    return out


LLM_PROMPT = """Extract facts about a customer account from one chat message.
Return JSON only, with null for anything the message does not state:
{{"owner": str|null, "contract_value": number|null, "renewal_date": "YYYY-MM-DD"|null}}
- owner: the person who now owns the customer account (not a task, ticket or past owner).
- contract_value: the signed annual contract value (not an invoice, discount, proposal or budget).
- renewal_date: when the contract renews or ends (not a meeting, payment or delivery date).
Known users: {users}
Message: {text}"""


def _json_object(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def validate_llm(
    proposal: dict, text: str, users: dict[str, str], currency: str | None, dayfirst: bool
) -> tuple[list[Extracted], list[str]]:
    """Keep only LLM values the message supports verbatim; return (kept, rejected fields)."""
    kept, rejected = [], []
    owner = proposal.get("owner")
    if owner:
        named = resolve_owner(text, users)
        if named and _fold(str(owner)) == _fold(named):
            kept.append(Extracted("owner", named, text))
        else:
            rejected.append("owner")
    value = proposal.get("contract_value")
    if value not in (None, ""):
        found = {
            p.value.value
            for p in find_amounts(_COUNTS.sub(" ", text), require_marker=True)
            if p.ok and (not currency or p.value.currency in (None, currency))
        }
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = None
        if number is not None and number in found:
            kept.append(Extracted("contract_value", number, text))
        else:
            rejected.append("contract_value")
    renewal = proposal.get("renewal_date")
    if renewal:
        parsed = parse_date(_ORDINAL.sub(r"\1", _MENTION.sub(" ", text)), dayfirst=dayfirst)
        try:
            claimed = date.fromisoformat(str(renewal))
        except ValueError:
            claimed = None
        if parsed.ok and claimed == parsed.value:
            kept.append(Extracted("renewal_date", claimed.isoformat(), text))
        else:
            rejected.append("renewal_date")
    return kept, rejected


def extract_message(
    text: str,
    users: dict[str, str],
    log: IssueLog,
    currency: str | None = "MAD",
    dayfirst: bool = True,
    rules: ExtractionRules | None = None,
    llm: TextModel | None = None,
) -> list[Extracted]:
    """Rule extraction, then (optionally) validated LLM extraction for the fields still empty."""
    found = extract_rules(text, users, log, currency, dayfirst, rules)
    if llm is None:
        return found
    missing = set(FIELDS) - {e.field for e in found}
    if not missing:
        return found
    prompt = LLM_PROMPT.format(users=", ".join(sorted(users.values())), text=text)
    proposal = {k: v for k, v in _json_object(llm.complete(prompt)).items() if k in missing}
    kept, rejected = validate_llm(proposal, text, users, currency, dayfirst)
    for field in rejected:
        log.refuse(field, text, "llm_value_not_in_source")
    return found + kept
