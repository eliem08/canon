"""Bilingual (French/English/Arabic/Darija) concept lexicon for company names.

Names in Arabic are often *translations*, not transliterations: "Maroc Telecom" is
"اتصالات المغرب" (telecom + Morocco, in another order). Mapping words to concepts,
and everything else to its consonant skeleton, lets such names compare as sets.

Business-type concepts drive two guards in pair scoring:
* different types ("Boulangerie" vs "Boucherie") are evidence of different companies;
* local-shop types ("Pharmacie", "Café", "Hôtel") make a name non-unique, so a name
  match alone is not enough to merge.

Extend per deployment through `ScoringConfig`; this list is deliberately small and generic.
"""

from __future__ import annotations

import re
import unicodedata

CONCEPTS: dict[str, tuple[str, ...]] = {
    # places and qualifiers
    "MOROCCO": ("maroc", "morocco", "marocaine", "marocain", "moroccan", "مغرب", "مغربية", "مغربي"),
    "ROYAL": ("royal", "royale", "ملكية", "ملكي"),
    "NATIONAL": ("national", "nationale", "وطني", "وطنية"),
    "POPULAR": ("populaire", "popular", "شعبي"),
    "OFFICE": ("office", "مكتب"),
    "GOLD": ("gold", "ذهب"),
    "AGENCY": ("agency", "agence", "وكالة"),
    # sectors / business types
    "TELECOM": ("telecom", "telecoms", "telecommunications", "اتصالات"),
    "BANK": ("banque", "bank", "بنك", "مصرف"),
    "INSURANCE": ("assurance", "assurances", "insurance", "تامين"),
    "AIRLINE": ("air", "airlines", "airline", "aerienne", "lignes", "خطوط", "جوية", "طيران"),
    "RAIL": ("chemins", "chemin", "fer", "rail", "railway", "railways", "سكك", "حديدية"),
    "ENERGY": ("energie", "energy", "طاقة"),
    "TRANSPORT": ("transport", "transports", "نقل"),
    "REALESTATE": ("immobilier", "immobiliere", "عقار", "عقارات", "عقارية"),
    "DISTRIBUTION": ("distribution", "توزيع"),
    "PACKAGING": ("packaging", "emballage", "emballages", "تغليف"),
    "TEXTILE": ("textile", "textiles", "نسيج"),
    "CEMENT": ("ciment", "ciments", "cement", "اسمنت"),
    "LOGISTICS": ("logistique", "logistics", "لوجيستيك"),
    "TRAVEL": ("tours", "tour", "voyages", "voyage", "travel", "سياحة", "اسفار"),
    "CONSULTING": ("consulting", "conseil", "consultants", "استشارات"),
    "SOFTWARE": ("software", "logiciels", "برمجيات"),
    "COSMETICS": ("cosmetics", "cosmetique", "cosmetiques", "تجميل"),
    "PHARMA": ("pharma", "pharmaceutique", "pharmaceutical", "pharmaceuticals"),
    # local shops (non-unique names)
    "PHARMACY": ("pharmacie", "pharmacy", "صيدلية"),
    "PARAPHARMACY": ("parapharmacie",),
    "BAKERY": ("boulangerie", "bakery", "مخبزة"),
    "PASTRY": ("patisserie", "حلويات"),
    "BUTCHER": ("boucherie", "butcher", "جزارة", "مجزرة"),
    "CAFE": ("cafe", "coffee", "مقهى"),
    "RESTAURANT": ("restaurant", "مطعم"),
    "HOTEL": ("hotel", "hotels", "فندق", "فنادق"),
    "CLINIC": ("clinique", "clinic", "مصحة"),
    "SCHOOL": ("ecole", "school", "مدرسة", "lycee"),
    "GARAGE": ("garage", "مراب"),
    "BOOKSHOP": ("librairie", "bookshop", "bookstore", "مكتبة"),
}  # fmt: skip
NOT_TYPES = frozenset({"MOROCCO", "ROYAL", "NATIONAL", "POPULAR", "OFFICE", "GOLD", "AGENCY"})
BUSINESS_TYPES = frozenset(CONCEPTS) - NOT_TYPES
LOCAL_SHOP_TYPES = frozenset(
    {"PHARMACY", "PARAPHARMACY", "BAKERY", "PASTRY", "BUTCHER", "CAFE", "RESTAURANT", "HOTEL",
     "CLINIC", "SCHOOL", "GARAGE", "BOOKSHOP"}
)  # fmt: skip
_WORD_TO_CONCEPT = {w: c for c, words in CONCEPTS.items() for w in words}
_ARABIC = re.compile(r"[؀-ۿ]")


def fold_arabic(word: str) -> str:
    word = re.sub(r"[ً-ٰٟـ]", "", word)  # diacritics, tatweel
    word = word.translate(str.maketrans("أإآٱى", "ااااي"))
    for prefix in ("وال", "بال", "لل", "ال"):  # "and the", "with the", "for the", "the"
        if word.startswith(prefix) and len(word) - len(prefix) >= 2:
            return word[len(prefix) :]
    return word


def name_concepts(name: str | None) -> tuple[str, ...]:
    """Concept id for known words, consonant skeleton for the rest (order-free set)."""
    from canon.resolve.normalize import ARABIC_LEGAL, _token_skeleton, _tokens, skeleton

    if not name:
        return ()
    out: list[str] = []
    if _ARABIC.search(name):
        text = name
        for suffix in ARABIC_LEGAL:
            text = text.replace(suffix, " ")
        for raw in re.split(r"[\s,.()\-]+", text):
            if not raw:
                continue
            if _ARABIC.search(raw):
                word = fold_arabic(raw)
                out.append(_WORD_TO_CONCEPT.get(word) or skeleton(word))
            else:
                folded = unicodedata.normalize("NFKD", raw).lower()
                out.append(_WORD_TO_CONCEPT.get(folded) or skeleton(raw))
    else:
        for tok in _tokens(name, drop_article=True):
            out.append(_WORD_TO_CONCEPT.get(tok) or _token_skeleton(tok))
    return tuple(dict.fromkeys(c for c in out if c))


def business_types(concepts: tuple[str, ...]) -> frozenset[str]:
    return frozenset(c for c in concepts if c in BUSINESS_TYPES)
