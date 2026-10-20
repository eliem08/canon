"""Contract terms from free-form contract text: parties, agreement date, effective date, end date.

The template patterns in `contracts.py` read Canon's own layout ("Le Client :", "Date d'effet :").
Real contracts are prose. This module reads the conventions most commercial contracts share, in
English and French:

- the preamble: "This Agreement is made as of <date> (the "Effective Date") by and between <A>, a
  Delaware corporation ("A"), and <B> ...", "Entre les soussignés : <A> ... et <B> ...";
- a defined date: <date> (the "Effective Date"), "Effective Date" means <date>;
- the term clause: "shall expire on <date>", "for a term of five (5) years from the Effective
  Date", "pour une durée de trois (3) ans à compter de la Date d'effet".

Each value comes with the character span it was read from, for citation. Precision comes first:
when two readings disagree the field is refused (`conflicting_values_in_contract`), and an end date
is computed from a term length only when the term runs from a date this module read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from canon.ingest.parsing import Parsed, parse_date

PREAMBLE_SEARCH = 20_000  # the preamble is near the top; a table of contents can push it down
PREAMBLE_MAX = 2_500  # a preamble longer than this is not a preamble

_DATE_TEXT = (
    r"(?:\d{1,2}\s?(?:s\s?t|n\s?d|r\s?d|t\s?h|er)?\s+(?:day\s+of\s+)?[A-Za-zéû]+\.?,?\s+\d{4}"
    r"|[A-Za-zéû]+\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}"
    r"|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}|\d{4}-\d{2}-\d{2})"
)
_Q = r"[\"“”'‘’]"

_BETWEEN = re.compile(
    r"\b(?:by\s+and\s+)?between\b\s*:?|\bentre\s*(?:les\s+soussign[ée]s\s*)?:?", re.I
)
_PREAMBLE_END = re.compile(
    r"\b(?:WHEREAS|RECITALS|BACKGROUND|W\s?I\s?T\s?N\s?E\s?S\s?S\s?E\s?T\s?H|NOW,?\s+THEREFORE"
    r"|agree\s+as\s+follows|hereby\s+agree|IL\s+A\s+[ÉE]T[ÉE]\s+CONVENU|PR[ÉE]AMBULE"
    r"|EXPOS[ÉE]\s+PR[ÉE]ALABLE|ci-apr[eè]s\s+collectivement)",
)
# what ends a party's name: its defined term, its description or its address
_NAME_END = re.compile(
    r"\s*\(|,?\s+(?:a|an)\s+(?=[A-Z][a-z]|limited|private|public|corporation|company|non-profit"
    r"|individual|national|state)"
    r"|,\s+(?:located|having|with\s+(?:its|offices|an\s+address|a\s+principal)|whose|of\s+\d"
    r"|organized|incorporated|existing|registered|registration|a\s+corporation|soci[ée]t[ée]|SARL|SA\b"
    r"|au\s+capital|dont\s+le\s+si[eè]ge|si[eè]ge|immatricul|repr[ée]sent)"
    r"|\s+(?:located\s+at|having\s+(?:its|a)|with\s+(?:its|an)\s+(?:principal|address|offices))"
    r"|,\s*\d|\s+(?:[Aa][Nn][Dd]|&)\s+(?=[A-Z])"
    r"|\s+(?:DATED|Dated|dated|Source:|Address:|Adresse\s*:|TABLE\s+OF\s+CONTENTS)"
)
_NEXT_PARTY = re.compile(
    r"(?:^|[),;.]|\s)\s*[-–]?\s*(?:and|AND|And|et|ET)\s*[:,\-–]?\s+(?:the\s+Covenanter\s*:\s*)?(?=[\w(])"
)
_LEAD = re.compile(r"^(?:\(\s*\d\s*\)|\d\.|[-–:;,]|\s)+")
_NOT_A_NAME = re.compile(
    r"\b(?:this|these|each|parties|party|agreement|hereinafter|herein|hereto|whereas|contrat"
    r"|convention|ci-apr[eè]s|les\s+parties)\b",
    re.I,
)

_DATED = re.compile(
    r"\b(?:dated|made|entered\s+into|executed|concluded|signed)"
    r"(?:\s+and\s+(?:entered\s+into|effective)|\s+effective)?\s*(?:as\s+of|on|this|:)?\s*"
    r"(?:this|the)?\s*"
    rf"(?P<d>{_DATE_TEXT})"
    r"|\b(?:fait|conclu|sign[ée]|[ée]tabli)e?\s+(?:[àa]\s+[A-Z][\w\-]+(?:\s+[A-Z][\w\-]+)?,?\s+)?le\s+"
    rf"(?P<f>{_DATE_TEXT})"
    rf"|\ben\s+date\s+du\s+(?P<g>{_DATE_TEXT})",
    re.I,
)
# "This Agreement ..." / "Le présent contrat ...": the sentence that dates *this* contract
_THIS_AGREEMENT = re.compile(
    r"\b(?:this|the\s+present|le\s+pr[ée]sent|la\s+pr[ée]sente)\b[^.]{0,250}?"
    r"\b(?:agreement|contract|addendum|amendment|schedule|contrat|convention|avenant)\b",
    re.I,
)
# a date that names another document: "..., dated as of May 15, 2002 (the "Note Agreement")"
_OTHER_DOCUMENT = re.compile(
    rf"\s*,?\s*\((?:the\s+)?{_Q}[^\"“”]{{0,60}}(?:Agreement|Indenture|Plan|Contract|Lease|Note)",
    re.I,
)
# "... the Agreement dated ...", "that certain License Agreement Number 12965 dated ...",
# "previously entered into ...": the date belongs to an earlier document
_REFERENCE_BEFORE = re.compile(
    r"(?:\b(?:previously|originally|certain|existing|prior|underlying)\b[^.]{0,120}"
    r"|\b(?:the|that|said|an?)\s+(?:[A-Z][\w&-]*\s+){0,8}(?:Agreement|Contract|Lease|Indenture|Plan)"
    r"(?:\s+(?:No\.|Number)\s*\S+)?\s*,?\s*)$"
)
_DEFINED_EFFECTIVE = re.compile(
    rf"(?P<d>{_DATE_TEXT})\s*,?\s*\(\s*(?:the|this|hereinafter(?:\s+the)?|la|ci-apr[eè]s)?\s*"
    rf"(?:referred\s+to\s+as\s+(?:the\s+)?)?{_Q}?(?-i:Effective\s+Date|Date\s+d.effet|Commencement\s+Date)"
    rf"|{_Q}(?-i:Effective\s+Date|Date\s+d.effet)\S?\s*(?:shall\s+)?(?:means?|d[ée]signe)\s+"
    rf"(?P<e>{_DATE_TEXT})",
    re.I,
)
_EFFECTIVE_AS_OF = re.compile(
    r"\b(?:made\s+and\s+effective|effective\s+(?:as\s+(?:of|from)\s+)?|prend\s+effet\s+le"
    rf"|entre\s+en\s+vigueur\s+le)\s*(?:the\s+)?(?P<d>{_DATE_TEXT})",
    re.I,
)
_EXPIRES = re.compile(
    r"\b(?:expire|expires|terminate|terminates|end|ends|ending|continue\s+(?:in\s+(?:full\s+)?force"
    r"(?:\s+and\s+effect)?\s+)?until|remain\s+in\s+(?:full\s+)?(?:force|effect)(?:\s+and\s+effect)?"
    r"\s+until|expirera|prendra\s+fin|(?:end|expire)s?\s+as\s+of|extended\s+(?:to|until)|through"
    r"|until|jusqu.au)\s*(?:on|at\s+midnight\s+on|le)?\s*"
    rf"(?P<d>{_DATE_TEXT})"
    rf"|(?P<e>{_DATE_TEXT})\s*,?\s*\(\s*(?:the\s+)?{_Q}?(?:Expiration\s+Date|Termination\s+Date)"
    # "TERM: November 01, 2014 to October 31, 2017", "durée : du 1er janvier 2024 au 31/12/2026"
    rf"|\b(?:term|dur[ée]e)\s*:\s*(?:from\s+|du\s+)?{_DATE_TEXT}\s+(?:to|through|au|[-–])\s+"
    rf"(?P<f>{_DATE_TEXT})",
    re.I,
)
_CALENDAR_YEAR_END = re.compile(
    r"\buntil\s+(?:the\s+)?end\s+of\s+the\s+(?:current|then[- ]current)\s+calendar\s+year"
    r"|jusqu.(?:à\s+la|au)\s+(?:fin|31\s+d[ée]cembre)\s+de\s+l.ann[ée]e\s+en\s+cours",
    re.I,
)
_EN_NUMBERS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty"
)
_FR_NUMBERS = "zéro un deux trois quatre cinq six sept huit neuf dix onze douze"
_NUMBER_WORDS = {w: i for i, w in enumerate(_EN_NUMBERS.split())} | {
    w: i for i, w in enumerate(_FR_NUMBERS.split())
}
_TERM = re.compile(
    r"\b(?:initial\s+)?(?:term|dur[ée]e)\b[^.;]{0,80}?\b(?:of|for|de)\s+(?:a\s+period\s+of\s+)?"
    r"(?P<n>\d{1,2}|[a-zéè]+)\s*(?:\(\s*(?P<n2>\d{1,2})\s*\))?\s*"
    r"(?P<unit>years?|months?|ans?|ann[ée]es?|mois)\b[^.;]{0,40}?"
    r"\b(?:from|after|commencing\s+on|beginning\s+on|following|à\s+compter\s+d[eu]|"
    r"à\s+partir\s+d[eu])\s+(?:the\s+|la\s+|l')?"
    r"(?P<anchor>Effective\s+Date|Commencement\s+Date|date\s+(?:of\s+)?(?:this\s+Agreement|hereof"
    r"|of\s+execution)|Date\s+d.effet|signature|date\s+de\s+signature)",
    re.I,
)
# the anchor first: "... effective on the Effective Date and shall remain in effect for an initial
# period of 1 year", "à compter de la Date d'effet pour une durée de trois (3) ans"
_TERM_AFTER_ANCHOR = re.compile(
    r"\b(?:on|from|as\s+of|à\s+compter\s+d[eu]|à\s+partir\s+d[eu])\s+(?:the\s+|la\s+|l')?"
    r"(?P<anchor>Effective\s+Date|Commencement\s+Date|Date\s+d.effet|date\s+(?:of\s+)?"
    r"(?:this\s+Agreement|hereof|above|(?:its\s+)?execution))\b[^.;]{0,80}?"
    r"\b(?:for|pour)\s+(?:an?\s+|une\s+)?(?:initial\s+)?(?:(?:period|term|dur[ée]e)\s+(?:of|de)\s+)?"
    r"(?P<n>\d{1,2}|[a-zéè]+)\s*(?:\(\s*(?P<n2>\d{1,2})\s*\))?\s*"
    r"(?P<unit>years?|months?|ans?|ann[ée]es?|mois)\b",
    re.I,
)
# no anchor stated: "This agreement is for a term of ten (10) years." A term runs from the
# contract's effective date (or, failing that, its date) unless the text says otherwise.
_TERM_NO_ANCHOR = re.compile(
    r"\b(?:this\s+agreement|the\s+(?:initial\s+)?term(?:\s+of\s+this\s+agreement)?|le\s+pr[ée]sent"
    r"\s+contrat)\s+(?:is|shall\s+be|will\s+be|est\s+conclu)\s+(?:for|pour)\s+(?:a|the|une)?\s*"
    r"(?:initial\s+)?(?:(?:term|period|dur[ée]e)\s+(?:of|de)\s+)?"
    r"(?P<n>\d{1,2}|[a-zéè]+)\s*(?:\(\s*(?P<n2>\d{1,2})\s*\))?\s*"
    r"(?P<unit>years?|months?|ans?|ann[ée]es?|mois)\b"
    r"(?![\s\S]{0,160}?\b(?:from|after|following|commencing|beginning|start\s+of\s+the\s+term"
    r"|à\s+compter)\b)",
    re.I,
)


@dataclass
class Term:
    value: object
    start: int
    end: int
    warnings: tuple[str, ...] = ()


@dataclass
class ContractTerms:
    parties: list[Term] = field(default_factory=list)
    agreement_date: Term | None = None
    effective_date: Term | None = None
    end_date: Term | None = None
    renewal_months: Term | None = None  # auto-renewal period, when the term renews by itself
    notice: Term | None = None  # non-renewal notice as an ISO 8601 duration ("P60D", "P3M")
    refused: list[tuple[str, str, str]] = field(default_factory=list)  # (field, raw, reason)


def _one_date(raw: str, dayfirst: bool | None) -> date | None:
    """One date; 03/04/2021 only when the deployment states its date order (`dayfirst` not None)."""
    p: Parsed[date] = parse_date(raw, dayfirst=dayfirst is not False)
    if not p.ok or (dayfirst is None and "day_month_order_by_convention" in p.warnings):
        return None
    return p.value


_LEGAL_SUFFIX = re.compile(
    r"\b(?:Inc|Incorporated|LLC|L\.L\.C|Ltd|Limited|Corp|Corporation|Company|Co|plc|PLC|LLP|L\.?P"
    r"|S\.?A|S\.?A\.?S|S\.?A\.?R\.?L|SARL|GmbH|AG|N\.?V|B\.?V|Pty|S\.?p\.?A|University|Trust|Bank"
    r"|Group|Holdings?|Partners)\b\.?,?$",
    re.I,
)
_CONNECTORS = {"of", "the", "and", "de", "du", "des", "la", "le", "et", "&", "for", "d'", "l'"}
_SECTION_NUMBER = re.compile(r"\b\d+\.\d+\b")


def _clean_name(raw: str) -> str | None:
    name = re.sub(r"\s+", " ", raw)
    name = re.sub(
        r"^\s*(?:(?:party|partie)\s+[ab12]|parties\s+to\s+this\s+agreement|the\s+covenanter)\s*:?\s*",
        "",
        name,
        flags=re.I,
    )
    name = _LEAD.sub("", name).strip(" ,.;:\"“”'")
    name = re.sub(r"\s+and/or\s+(?:its\s+)?assigns$", "", name, flags=re.I)
    if not name or not (name[0].isupper() or name[0].isdigit() or _LEGAL_SUFFIX.search(name)):
        return None
    words = name.split()
    if len(words) > 12 or len(name) > 120 or _NOT_A_NAME.search(name):
        return None
    if not any(c.isalpha() for c in name) or _SECTION_NUMBER.search(name):
        return None
    content = [w for w in words if w.lower() not in _CONNECTORS]
    capitalized = sum(1 for w in content if not w[0].islower() or any(c.isupper() for c in w))
    if not content or capitalized / len(content) < 0.75:
        return None
    return name


def _is_alias(name: str, text: str) -> bool:
    """A defined term ("the "Distributor"") rather than a legal name."""
    parts = [re.sub(r"^(?:the|la|le|l')\s*", "", p.strip(), flags=re.I) for p in name.split(",")]
    return all(p and re.search(rf"{_Q}{re.escape(p)}{_Q}", text) for p in parts)


def _parties_at(text: str, start: int) -> tuple[list[Term], int, bool]:
    """Parties listed after a "between" at `start`: (parties, preamble end, credible)."""
    end_m = _PREAMBLE_END.search(text, start, start + PREAMBLE_MAX)
    end = end_m.start() if end_m else min(len(text), start + PREAMBLE_MAX)
    seg = text[start:end]
    parties: list[Term] = []
    credible = False  # an entity suffix, or a name followed by its description or defined term
    pos = 0
    for _ in range(4):
        m = _NAME_END.search(seg, pos)
        if not m:  # the last party runs to the end of the preamble ("... and Acme LLC. RECITALS")
            name = _clean_name(seg[pos:])
            if name and parties and not _is_alias(name, text) and _LEGAL_SUFFIX.search(name):
                parties.append(Term(name, start + pos, end))
            break
        name = _clean_name(seg[pos : m.start()])
        if name and _is_alias(name, text):
            name = None  # 'between Licensor and Licensee': defined terms, not names
        if name and all(p.value != name for p in parties):
            parties.append(Term(name, start + pos, start + m.start()))
            by_and = m.group(0).strip().lower() in ("and", "&")
            credible |= bool(_LEGAL_SUFFIX.search(name)) or not by_and
        elif not name:
            break  # the list of parties is over (or never started)
        nxt = _NEXT_PARTY.search(
            seg, m.end() if m.group(0).strip().lower() not in ("and", "&") else m.start()
        )
        if not nxt:
            break
        pos = nxt.end()
    return parties, end, credible


def _preamble_parties(text: str) -> tuple[list[Term], tuple[int, int] | None]:
    head = text[:PREAMBLE_SEARCH]
    for m in _BETWEEN.finditer(head):
        parties, end, credible = _parties_at(head, m.end())
        if len(parties) >= 2 and credible:
            return parties, (m.end(), end)
    return _labelled_parties(head), None


_PARTY_LABEL = re.compile(
    r"\b(?:Party|Partie)\s+(?P<k>[AB12])\s*(?:\([^)]{0,40}\))?\s*:\s*"
    r"(?P<name>[^\n:;]{2,120}?)(?=\s+(?:Address|Adresse|Legal\s+Representative|Registered)\b|\s*\(|,|\n|$)"
)


def _labelled_parties(head: str) -> list[Term]:
    found: dict[str, Term] = {}
    for m in _PARTY_LABEL.finditer(head):
        name = _clean_name(m.group("name"))
        if name and not _is_alias(name, head) and m.group("k") not in found:
            found[m.group("k")] = Term(name, m.start("name"), m.end("name"))
    return list(found.values()) if len(found) >= 2 else []


def read_parties(text: str) -> list[Term]:
    return _preamble_parties(text)[0]


def _dates(pattern: re.Pattern, text: str, dayfirst: bool | None) -> list[Term]:
    out = []
    for m in pattern.finditer(text):
        group = next(g for g in pattern.groupindex if m.group(g))
        d = _one_date(m.group(group), dayfirst)
        if d:
            out.append(Term(d, m.start(group), m.end(group)))
    return out


def _agree(candidates: list[Term], name: str, refused: list) -> Term | None:
    values = {c.value for c in candidates}
    if len(values) > 1:
        refused.append(
            (name, "; ".join(sorted(str(v) for v in values)), "conflicting_values_in_contract")
        )
        return None
    return candidates[0] if candidates else None


_TERM_CONTEXT = re.compile(
    rf"{_Q}Term{_Q}|\b(?:term|dur[ée]e)\s*:"
    r"|\b(?:this\s+(?:Agreement|Contract|Amendment)|the\s+Term|Initial\s+Term|term\s+of\s+this"
    r"|Term\s+of\s+(?:the\s+)?Agreement|le\s+pr[ée]sent\s+contrat|la\s+dur[ée]e|ce\s+contrat)\b",
    re.I,
)


_DEFINITION = re.compile(
    rf"{_Q}[A-Z][^\"“”]{{0,40}}{_Q}\s*(?:shall\s+)?means?\b|\b(?:quarter|fiscal)\b", re.I
)
# auto-renewal: "shall automatically renew for successive one (1) year periods",
# "se renouvellera par tacite reconduction par périodes d'un an", "reconduit tacitement pour un an"
_AUTO_RENEW = re.compile(
    r"\b(?:(?:automatically|auto-)\s*(?:be\s+)?renew(?:ed|s)?|renew(?:ed|s)?\s+automatically"
    r"|(?:reconduit|renouvel[ée])e?s?\s+tacitement|(?:se\s+renouvellera|renouvel[ée]e?)\s+par\s+"
    r"tacite\s+reconduction|tacite\s+reconduction)\b[^.;]{0,60}?\b(?:for|by|pour|par)\s+"
    r"(?:(?:an?|une?|successive|additional|further|consecutive|renewal|p[ée]riodes?|successives?"
    r"|suppl[ée]mentaires?|nouvelles?|de)\s+)*(?:d['’])?"
    r"(?P<n>\d{1,2}|[a-zéè]+)?\s*(?:\(\s*(?P<n2>\d{1,2})\s*\))?\s*"
    r"(?P<unit>years?|months?|ans?|ann[ée]es?|mois)\b",
    re.I,
)
# non-renewal notice: "unless either party gives at least sixty (60) days' prior written notice",
# "upon 90 days notice", "notice of non-renewal at least 3 months", "préavis de trois (3) mois"
_NOTICE = re.compile(
    r"\b(?:(?:at\s+least|not\s+less\s+than|no\s+less\s+than|minimum\s+of|au\s+moins|moyennant"
    r"|un|d.un|avec)\s+)?(?:(?P<n>\d{1,3}|[a-zéè]+)\s*(?:\(\s*(?P<n2>\d{1,3})\s*\))?\s*"
    r"(?P<unit>days?|months?|jours?|mois)['’]?\s+(?:(?:prior|advance|written|préalable|écrit)\s+)*"
    r"(?:notice|préavis)|(?:notice|préavis)\s+(?:of\s+(?:non-?renewal\s+)?|de\s+)"
    r"(?:(?:at\s+least|not\s+less\s+than|au\s+moins)\s+)?"
    r"(?P<m>\d{1,3}|[a-zéè]+)\s*(?:\(\s*(?P<m2>\d{1,3})\s*\))?\s*"
    r"(?P<unit2>days?|months?|jours?|mois)\b)",
    re.I,
)
_RENEWAL_CONTEXT = re.compile(r"renew|reconduction|reconduit|renouvel", re.I)
# an option is not the end date: "Flotek may elect for the Term to be extended to December 31, 2024"
_OPTION = re.compile(
    r"\b(?:may|elect|option|right\s+to)\b[^.;]{0,80}\bextended(?:\s+(?:to|until))?$", re.I
)


def _about_the_term(text: str, start: int, end: int | None = None) -> bool:
    """The clause around a date is about this contract's term (not a licence window or a TOC)."""
    sentence_start = max(text.rfind(". ", 0, start), text.rfind("\n\n", 0, start), start - 150)
    clause = text[sentence_start : end or start]
    if re.search(r"(?:\s\d+){3}", clause) or _DEFINITION.search(clause):
        return False
    return bool(_TERM_CONTEXT.search(clause))


def add_months(d: date, months: int) -> date | None:
    y, m = divmod(d.month - 1 + months, 12)
    try:
        return d.replace(year=d.year + y, month=m + 1)
    except ValueError:  # 29 February, 31st of a short month: no single right answer
        return None


def next_renewal(end: date, months: int, today: date) -> date | None:
    """The first renewal after `today` of a term that ended on `end` and renews every `months`.
    None while the initial term runs, or when the roll lands on a day that does not exist."""
    if end > today or months <= 0:
        return None
    steps = ((today.year - end.year) * 12 + today.month - end.month) // months
    nxt = add_months(end, months * steps)
    while nxt is not None and nxt <= today:
        steps += 1
        nxt = add_months(end, months * steps)
    return nxt


def cancel_by(renewal: date, notice: str) -> date | None:
    """The last day to give notice ("P60D", "P3M") before `renewal`."""
    m = re.fullmatch(r"P(\d+)([DM])", notice)
    if not m:
        return None
    n = int(m.group(1))
    return renewal - timedelta(days=n) if m.group(2) == "D" else add_months(renewal, -n)


def _agreement_date(head: str, dayfirst: bool | None, pattern: re.Pattern = _DATED) -> Term | None:
    """The first date in the sentence that introduces this contract, else a "Dated:" line in the
    title block. Dates that name another document are skipped."""
    windows = [(m.start(), m.end() + 600) for m in _THIS_AGREEMENT.finditer(head)][:3]
    recitals = _PREAMBLE_END.search(head, 0, 1500)  # recitals talk about earlier documents
    windows.append((0, recitals.start() if recitals else 1500))
    for lo, hi in windows:
        for m in pattern.finditer(head, lo, hi):
            group = next(g for g in pattern.groupindex if m.group(g))
            if _OTHER_DOCUMENT.match(head, m.end(group)):
                continue
            if _REFERENCE_BEFORE.search(head[max(0, m.start() - 160) : m.start()]):
                continue
            d = _one_date(m.group(group), dayfirst)
            if d:
                return Term(d, m.start(group), m.end(group))
    return None


def read_terms(text: str, dayfirst: bool | None = None) -> ContractTerms:
    parties, _ = _preamble_parties(text)
    terms = ContractTerms(parties=parties)
    head = text[:PREAMBLE_SEARCH]
    terms.agreement_date = _agreement_date(head, dayfirst)
    as_of = _agreement_date(head, dayfirst, _EFFECTIVE_AS_OF)
    terms.effective_date = _agree(
        _dates(_DEFINED_EFFECTIVE, text, dayfirst) + ([as_of] if as_of else []),
        "contract_start",
        terms.refused,
    )
    explicit = [
        t
        for t in _dates(_EXPIRES, text, dayfirst)
        if _about_the_term(text, t.start)
        and not _OPTION.search(text[max(0, t.start - 120) : t.start].rstrip())
    ]
    derived = []
    for m in [
        *_TERM.finditer(text),
        *_TERM_AFTER_ANCHOR.finditer(text),
        *_TERM_NO_ANCHOR.finditer(text),
    ]:
        if not _about_the_term(text, m.start(), m.end()):
            continue
        n = m.group("n2") or m.group("n")
        n = int(n) if n.isdigit() else _NUMBER_WORDS.get(n.lower())
        anchor = (m.groupdict().get("anchor") or "").lower()
        if not anchor:
            base = terms.effective_date or terms.agreement_date
        elif "effective" in anchor or "effet" in anchor or "commencement" in anchor:
            base = terms.effective_date
        else:
            base = terms.agreement_date
        if not n or not base:
            continue
        months = n * 12 if m.group("unit").lower()[0] in "ya" else n
        end = add_months(base.value, months)
        if end:
            derived.append(Term(end, m.start(), m.end(), ("derived_from_term_length",)))
    year_end = _CALENDAR_YEAR_END.search(text)
    start = terms.effective_date or terms.agreement_date
    if year_end and start and _about_the_term(text, year_end.start(), year_end.end()):
        derived.append(
            Term(date(start.value.year, 12, 31), year_end.start(), year_end.end(),
                 ("derived_from_calendar_year",))
        )  # fmt: skip
    # a stated end date beats one computed from the term length (which may be off by a day)
    terms.end_date = _agree(explicit or derived, "renewal_date", terms.refused)
    periods = []
    for m in _AUTO_RENEW.finditer(text):
        n = m.group("n2") or m.group("n")
        if n is None or n.lower() in {"a", "an", "un", "une"}:
            n = 1
        else:
            n = int(n) if n.isdigit() else _NUMBER_WORDS.get(n.lower())
        if n:
            months = n * 12 if m.group("unit").lower()[0] in "ya" else n
            periods.append(Term(months, m.start(), m.end()))
    terms.renewal_months = _agree(periods, "renewal_period_months", terms.refused)
    notices = []
    for m in _NOTICE.finditer(text):
        lo = max(text.rfind(". ", 0, m.start()), text.rfind("\n\n", 0, m.start()), 0)
        hi = text.find(". ", m.end())
        if not _RENEWAL_CONTEXT.search(text[lo : hi if hi >= 0 else len(text)]):
            continue  # a notice to cure a breach or to terminate for cause is not about renewal
        n = m.group("n2") or m.group("n") or m.group("m2") or m.group("m")
        n = int(n) if n.isdigit() else _NUMBER_WORDS.get(n.lower())
        unit = (m.group("unit") or m.group("unit2")).lower()
        if n:
            notices.append(Term(f"P{n}{'M' if unit.startswith(('mo', 'mois')) else 'D'}",
                                m.start(), m.end()))  # fmt: skip
    terms.notice = _agree(notices, "renewal_notice", terms.refused)
    return terms
