import pytest

from canon.resolve.normalize import (
    acronym,
    normalize_address,
    normalize_name,
    skeleton,
    strip_legal_suffix,
)


@pytest.mark.parametrize(
    "variant",
    [
        "Atlas Logistique SARL",
        "ATLAS LOGISTIQUE S.A.R.L.",
        "Atlas Logistique, Société à Responsabilité Limitée",
        "Sté Atlas Logistique",
        "Chrikat Atlas Logistique",
        "atlas logistique sarl au",
    ],
)
def test_legal_suffix_and_case_variants_collapse(variant):
    assert normalize_name(variant) == "atlas logistique"


def test_accents_fold():
    assert normalize_name("Nour Énergie S.A.") == normalize_name("NOUR ENERGIE SA")


@pytest.mark.parametrize(
    ("latin", "arabic"),
    [
        ("Atlas Logistique", "أطلس لوجيستيك ش.م.م"),
        ("Medina Pharma", "مدينة فارما"),
        ("Dar El Hana", "دار الهناء"),
        ("Al Massira", "المسيرة"),
    ],
)
def test_arabic_and_latin_share_a_skeleton(latin, arabic):
    assert skeleton(latin) == skeleton(arabic)


def test_spelling_variants_share_a_skeleton():
    assert skeleton("Atlas Logistique") == skeleton("atlas lojistik")
    assert skeleton("Chefchaouen") == skeleton("Shefshawen")


def test_acronym_latin_only():
    assert acronym("Tanger Med Freight Ltd") == "tmf"
    assert acronym("Kasbah Hospitality Group") == "khg"
    assert acronym("أطلس لوجيستيك") == ""


def test_strip_legal_suffix_keeps_casing():
    assert strip_legal_suffix("Argan d'Or S.A.R.L.") == "Argan d'Or"
    assert strip_legal_suffix("Ste Fennec Software Ltd") == "Fennec Software"
    assert strip_legal_suffix("مخبزة البركة ش.م.م") == "مخبزة البركة"


def test_address_abbreviations():
    assert normalize_address("112 Bd Zerktouni") == normalize_address("112, Boulevard Zerktouni")


@pytest.mark.parametrize(
    "a, b",
    [("New York City", "new york"), ("Ville de Fès", "Fes"), ("Ville d'Agadir", "agadir")],
)
def test_the_word_for_city_is_not_part_of_the_name(a, b):
    from canon.resolve.normalize import normalize_city

    assert normalize_city(a) == normalize_city(b)


def test_cities_that_merely_contain_city_stay_distinct():
    from canon.resolve.normalize import normalize_city

    assert normalize_city("Cityville") == "cityville"
    assert normalize_city("Casablanca") != normalize_city("Rabat")
