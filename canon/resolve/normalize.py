"""Name and address normalization for entity resolution.

Three representations of a name are produced:

* `normalize_name`  — folded Latin text: lowercase, no accents, no punctuation,
  legal suffixes / company nouns / stopwords removed. Arabic script is
  transliterated first.
* `skeleton`        — consonant skeleton used to compare across scripts and
  spellings: "Atlas Logistique", "atlas lojistik" and "أطلس لوجيستيك" all map
  to "tls ljstk". Vowels, h, w, y and the Arabic ain are dropped because
  Arabic script does not write short vowels and transliterations disagree on
  them.
* `acronym`         — initials of the normalized tokens ("tmf", "khg").
"""

from __future__ import annotations

import re
import unicodedata

# Multi-word legal forms first so they are removed before single tokens.
LEGAL_PHRASES = (
    "societe a responsabilite limitee",
    "societe anonyme simplifiee",
    "societe anonyme",
    "private limited company",
    "public limited company",
    "limited liability company",
    "sarl au",
)
LEGAL_TOKENS = frozenset(
    {
        "sarl", "sarlau", "sa", "sas", "sasu", "snc", "ltd", "limited", "llc", "inc", "plc",
        "gmbh", "co", "cie", "ste", "societe", "company", "corp",
        # Darija-in-Latin "company" nouns
        "chrika", "chrikat", "charika", "charikat", "sharika",
    }
)  # fmt: skip
ARABIC_LEGAL = ("ش.م.م", "ش.م.ب", "ش.م", "شركة", "المحدودة", "ش م م")
ARTICLES = frozenset({"al", "el"})
STOPWORDS = frozenset(
    {"de", "du", "des", "la", "le", "les", "l", "d", "et", "the", "and", "of", "dyal", "dial"}
)

# Arabic letter -> Latin consonant class (vowel letters map to "a", dropped later).
ARABIC_TO_LATIN = {
    "ا": "a", "أ": "a", "إ": "a", "آ": "a", "ء": "", "ئ": "y", "ؤ": "w", "ى": "a",
    "ب": "b", "ت": "t", "ث": "t", "ج": "j", "ح": "h", "خ": "kh", "د": "d", "ذ": "d",
    "ر": "r", "ز": "z", "س": "s", "ش": "sh", "ص": "s", "ض": "d", "ط": "t", "ظ": "z",
    "ع": "", "غ": "gh", "ف": "f", "ق": "k", "ك": "k", "ل": "l", "م": "m", "ن": "n",
    "ه": "h", "ة": "a", "و": "w", "ي": "y", "پ": "b", "ڤ": "f", "گ": "g", "ـ": "",
}  # fmt: skip
ARABIC_RE = re.compile(r"[؀-ۿ]")

# Latin spelling -> sound class, applied in order on folded text.
_LATIN_RULES = (
    (r"qu", "k"),
    (r"ph", "f"),
    (r"(?:ch|sh)", "\x01"),  # sh sound placeholder
    (r"kh", "k"),
    (r"gh", "g"),
    (r"th", "t"),
    (r"dh", "d"),
    (r"ou", "w"),
    (r"c(?=[eiy])", "s"),
    (r"g(?=[eiy])", "j"),
    (r"[cqk]", "k"),
    (r"x", "ks"),
    (r"p", "b"),
    (r"v", "f"),
    (r"3", ""),  # Darija ain
    (r"7", "h"),
    (r"9", "k"),
    (r"2", ""),
)
_SKELETON_DROP = re.compile(r"[aeiouyhw]")


def fold(text: str) -> str:
    """Lowercase, strip accents and compatibility characters."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def transliterate_arabic(text: str, drop_article: bool = False) -> str:
    for suffix in ARABIC_LEGAL:
        text = text.replace(suffix, " ")
    if drop_article:  # definite article ال / لل is written attached to the word
        text = re.sub(r"(?<!\S)(?:ال|لل)(?=\S{2,})", "", text)
    return "".join(ARABIC_TO_LATIN.get(c, c) for c in text)


def has_arabic(text: str) -> bool:
    return bool(ARABIC_RE.search(text))


def _tokens(name: str, drop_article: bool = False) -> list[str]:
    if has_arabic(name):
        name = transliterate_arabic(name, drop_article)
    text = fold(name).replace("&", " et ").replace("'", " ").replace("’", " ")
    # Join dotted abbreviations (S.A.R.L. -> sarl, S.A -> sa) before splitting on punctuation.
    text = re.sub(r"\b(?:[a-z]\.){1,4}[a-z]?\b\.?", lambda m: m.group(0).replace(".", ""), text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"_", " ", text)
    # letter-by-letter acronyms: "A V E C" -> "avec" (3+ single letters in a row)
    text = re.sub(r"\b(?:[a-z] ){2,}[a-z]\b", lambda m: m.group(0).replace(" ", ""), text)
    for phrase in LEGAL_PHRASES:
        text = re.sub(rf"\b{phrase}\b", " ", text)
    tokens = [t for t in text.split() if t not in LEGAL_TOKENS and t not in STOPWORDS]
    if drop_article:
        tokens = [t for t in tokens if t not in ARTICLES] or tokens
    return tokens


def normalize_name(name: str | None) -> str:
    return " ".join(_tokens(name)) if name else ""


def _token_skeleton(token: str) -> str:
    for pattern, repl in _LATIN_RULES:
        token = re.sub(pattern, repl, token)
    token = token.replace("\x01", "sh")
    token = _SKELETON_DROP.sub("", token)
    return re.sub(r"(.)\1+", r"\1", token)  # collapse doubled consonants


def skeleton(name: str | None) -> str:
    """Space-separated consonant skeleton of each normalized token."""
    if not name:
        return ""
    sk = [_token_skeleton(t) for t in _tokens(name, drop_article=True)]
    return " ".join(s for s in sk if s)


# Company nouns that people keep in acronyms ("AFC" = Atlantic Fishing Company),
# unlike legal-form abbreviations (SARL, SA, Ltd), which never appear in them.
ACRONYM_NOUNS = frozenset({"company", "societe", "group", "groupe", "corp"})


# Short words that acronyms usually skip ("Conseil aux Entreprises" -> CE), besides STOPWORDS.
ACRONYM_SKIPPED = frozenset({"a", "au", "aux", "en", "pour", "sur", "par", "for", "in", "on"})


def acronyms(name: str | None) -> set[str]:
    """Initials of a Latin-script name, with and without company nouns, and with and without the
    linking words that some acronyms keep ("Association Vie Et Cancer" -> AVEC)."""
    if not name or has_arabic(name):
        return set()
    out = set()
    core = _tokens(name, drop_article=True)
    if len(core) >= 2:
        out.add("".join(t[0] for t in core))
    words = [t for t in re.findall(r"\w+", fold(name)) if t not in ARTICLES]
    for keep_links in (False, True):
        kept = [
            t
            for t in words
            if (t not in LEGAL_TOKENS or t in ACRONYM_NOUNS)
            and (keep_links or (t not in STOPWORDS and t not in ACRONYM_SKIPPED))
        ]
        if len(kept) >= 2:
            out.add("".join(t[0] for t in kept))
    return out


def acronym(name: str | None) -> str:
    """Primary acronym (legal forms and company nouns removed)."""
    if not name or has_arabic(name):
        return ""
    tokens = _tokens(name, drop_article=True)
    return "".join(t[0] for t in tokens) if len(tokens) >= 2 else ""


def strip_legal_suffix(name: str) -> str:
    """Remove trailing legal forms while keeping the original casing."""
    out = name.strip().rstrip(",")
    for suffix in ARABIC_LEGAL:
        out = out.replace(suffix, "").strip()
    pattern = re.compile(
        r"[\s,]+(?:S\.?A\.?R\.?L\.?(?:\s*AU)?|S\.?A\.?S\.?|S\.?A\.?|Ltd\.?|Limited|LTD|"
        r"Soci[ée]t[ée] (?:à|a) Responsabilit[ée] Limit[ée]e|Soci[ée]t[ée] Anonyme)\s*$",
        re.IGNORECASE,
    )
    prev = None
    while prev != out:
        prev = out
        out = pattern.sub("", out).strip().rstrip(",")
    return re.sub(r"^(?:St[ée]|Chrikat?)\s+", "", out, flags=re.IGNORECASE)


_STREET_ABBREV = {
    "bd": "boulevard", "blvd": "boulevard", "av": "avenue", "ave": "avenue", "r": "rue",
    "zi": "zone industrielle", "imm": "immeuble", "bldg": "building", "n": "", "no": "",
    # French postal standard (La Poste): the registry and many CRMs write these forms
    "sq": "square", "pl": "place", "che": "chemin", "chem": "chemin", "imp": "impasse",
    "all": "allee", "rte": "route", "qua": "quai", "fg": "faubourg", "fbg": "faubourg",
    "crs": "cours", "res": "residence", "lot": "lotissement", "za": "zone artisanale",
    "zac": "zone amenagement concerte", "ham": "hameau", "pas": "passage", "prom": "promenade",
    "rpt": "rond point", "vla": "villa", "mte": "montee", "sen": "sentier", "pkg": "parking",
    "ccal": "centre commercial", "cc": "centre commercial", "esp": "esplanade",
    # repetition index after a street number: 1 bis, 3 ter, 1 T
    "bis": "", "ter": "", "b": "", "t": "",
}  # fmt: skip


def normalize_address(address: str | None) -> str:
    if not address:
        return ""
    text = re.sub(r"[^\w\s]", " ", fold(address))
    tokens = []
    for t in text.split():
        t = _STREET_ABBREV.get(t, t)
        if t:
            tokens.append(t)
    return " ".join(tokens)


_CITY_WORDS = re.compile(r"^(?:ville|city|municipalite)\s+(?:de\s+|d'|of\s+)?|\s+(?:city|ville)$")


def normalize_city(city: str | None) -> str:
    """'New York City' = 'new york', 'Ville de Fès' = 'Fes': the word for city is not the name."""
    if not city:
        return ""
    return re.sub(r"[^a-z]", "", _CITY_WORDS.sub("", fold(city).strip()))
