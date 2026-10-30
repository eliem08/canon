"""Hardened parsers: an adversarial fixture set plus randomized round trips.

The rule under test: a parser may refuse (quarantine) a value, but must never return
a wrong one ("silent wrong value")."""

import json
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from canon.ingest.config import IngestConfig
from canon.ingest.contracts import parse_contract
from canon.ingest.crm import CRMFieldMap, crm_row_to_record, load_crm
from canon.ingest.parsing import (
    find_amounts,
    find_phones,
    infer_dayfirst,
    parse_amount,
    parse_date,
    parse_identifier,
    parse_phone,
)

MA = IngestConfig(default_country="212", currency="MAD")  # these tests use Moroccan data

CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "parsing_cases.json").read_text(encoding="utf-8")
)["cases"]
CONTRACT = (
    "Contrat N° : CN-1\nVersion : 1\nDate de signature : {sig}\nLe Client : Acme SARL\n"
    "Article 4 - Prix. Le montant annuel est fixé à {amt} HT.\n"
)


def run_case(case):
    """Return the parsed value through the public API (None = refused)."""
    kind, raw = case["kind"], case["raw"]
    if kind == "money":
        p = parse_amount(raw)
        return p.value.value if p.ok else None
    if kind == "date":
        p = parse_date(raw, dayfirst=case.get("dayfirst", True), century=case.get("century"))
        return p.value.isoformat() if p.ok else None
    if kind == "phone":
        return parse_phone(raw, case.get("country", "212")).value
    if kind == "identifier":
        return parse_identifier(raw).value
    record = parse_contract(
        CONTRACT.format(
            sig=raw if kind == "contract_date" else "17/03/2026",
            amt=raw if kind == "contract_amount" else "1 MAD",
        ),
        "contract:x",
        "x",
    )["record"]
    if kind == "contract_amount":
        return next((f.value for f in record.facts if f.field == "contract_value"), None)
    return record.updated_at.isoformat() if record.updated_at else None


def same(got, expected):
    if isinstance(expected, int | float) and isinstance(got, int | float):
        return abs(got - expected) < 1e-6
    return got == expected


def test_fixture_set_is_large_and_adversarial():
    assert len(CASES) >= 40
    assert sum(c["expect"] is None for c in CASES) >= 20  # many must be refused


def test_no_silent_wrong_values_and_95_percent_correct():
    wrong, correct = [], 0
    for case in CASES:
        got = run_case(case)  # must never raise
        if same(got, case["expect"]):
            correct += 1
        elif got is not None:  # returned a value that is not the right one
            wrong.append((case["id"], case["raw"], got, case["expect"]))
    assert wrong == [], f"silent wrong values: {wrong}"
    assert correct / len(CASES) >= 0.95, f"{correct}/{len(CASES)}"


@pytest.mark.parametrize("raw", ["1,426,000.00", "1.426.000,00", "1 426 000,00", "١٬٤٢٦٬٠٠٠"])
def test_the_audit_cases(raw):
    assert parse_amount(raw).value.value == 1_426_000


def test_refusals_say_why():
    assert parse_amount("1.426,000").reason == "ambiguous_separator"
    assert parse_amount("450 000 EUR").reason == "unexpected_currency:EUR"
    assert parse_amount("450k ou 500k MAD").reason == "multiple_amounts"
    assert parse_date("31/02/2026").reason == "impossible_date"
    assert parse_date("17/03/26").reason == "two_digit_year"
    assert parse_date("mars 2028").reason == "month_only"
    assert parse_phone("Fax: 0522123456").reason == "fax_number"
    assert parse_phone("+212412345678").reason == "invalid_prefix"


# ---------------------------------------------------------------- randomized round trips

RNG = random.Random(20261016)
ARABIC_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def render_amount(value: float, style: str) -> str:
    whole, cents = f"{value:.2f}".split(".")
    groups = f"{int(whole):,}"
    keep_cents = cents != "00" or RNG.random() < 0.5
    return {
        "us": groups + (f".{cents}" if keep_cents else ""),
        "eu": groups.replace(",", ".") + (f",{cents}" if keep_cents else ""),
        "fr": groups.replace(",", " ") + (f",{cents}" if keep_cents else ""),
        "ch": groups.replace(",", "'") + (f".{cents}" if keep_cents else ""),
        "bare": whole + (f".{cents}" if keep_cents else ""),
    }[style]


@pytest.mark.parametrize("trial", range(400))
def test_amount_round_trip_never_wrong(trial):
    value = round(RNG.uniform(1_000, 50_000_000), RNG.choice([0, 2]))
    text = render_amount(value, RNG.choice(["us", "eu", "fr", "ch", "bare"]))
    if RNG.random() < 0.3:
        text = text.translate(ARABIC_DIGITS)
    text = RNG.choice(["{}", "{} MAD", "MAD {}", "{} DH HT", "{} dirhams", "{} درهم"]).format(text)
    parsed = parse_amount(text)
    assert parsed.ok, (text, parsed.reason)
    assert parsed.value.value == pytest.approx(value), text


FR_MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
             "septembre", "octobre", "novembre", "décembre"]  # fmt: skip
EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"]  # fmt: skip
AR_MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "ماي", "يونيو", "يوليوز", "غشت", "شتنبر",
             "أكتوبر", "نونبر", "دجنبر"]  # fmt: skip


@pytest.mark.parametrize("trial", range(300))
def test_date_round_trip_never_wrong(trial):
    d = date(2020, 1, 1) + timedelta(days=RNG.randrange(0, 3650))
    dayfirst = RNG.random() < 0.7
    numeric = (
        f"{d.day:02d}/{d.month:02d}/{d.year}" if dayfirst else f"{d.month:02d}/{d.day:02d}/{d.year}"
    )
    text = RNG.choice(
        [
            d.isoformat(),
            numeric,
            f"{d.day} {FR_MONTHS[d.month - 1]} {d.year}",
            f"{EN_MONTHS[d.month - 1]} {d.day}, {d.year}",
            f"{d.day} {AR_MONTHS[d.month - 1]} {d.year}",
        ]
    )
    if RNG.random() < 0.3:
        text = text.translate(ARABIC_DIGITS)
    parsed = parse_date(text, dayfirst=dayfirst)
    assert parsed.ok, (text, parsed.reason)
    assert parsed.value == d, text


@pytest.mark.parametrize("trial", range(200))
def test_moroccan_phone_round_trip_never_wrong(trial):
    nsn = RNG.choice("5678") + "".join(RNG.choice("0123456789") for _ in range(8))
    if len(set(nsn)) == 1:
        nsn = "5" + nsn[1:-1] + "7"
    national = "0" + nsn
    text = RNG.choice(
        [
            "+212" + nsn,
            "00212" + nsn,
            " ".join([national[:2], national[2:4], national[4:6], national[6:8], national[8:]]),
            "-".join([national[:4], national[4:6], national[6:8], national[8:]]),
            f"+212 (0){nsn[0]} {nsn[1:3]} {nsn[3:5]} {nsn[5:7]} {nsn[7:]}",
            f"Tél : {national}",
        ]
    )
    if RNG.random() < 0.3:
        text = text.translate(ARABIC_DIGITS)
    assert parse_phone(text).value == "+212" + nsn, text


# ---------------------------------------------------------------- free text and connectors


def test_free_text_amounts_ignore_darija_words_dates_and_years():
    assert (
        find_amounts("Deal signé m3a acme: 120 000 MAD par an", require_marker=True)[0].value.value
        == 120_000
    )
    assert (
        find_amounts("contrat tla3 l 450k f 2026, renouvellement 01/03/2028", require_marker=True)[
            0
        ].value.value
        == 450_000
    )
    assert find_amounts("rappel: meeting ghda 10h, 3 personnes", require_marker=True) == []
    # a date followed by punctuation, and digits inside a user mention, are not amounts
    found = find_amounts("contrat: 820k MAD/an, renouvellement le 01/09/2028, owner <@U07>", True)
    assert [p.value.value for p in found] == [820_000]


def test_free_text_phones_drop_amounts_and_dates():
    assert find_phones("contrat 120 000 000 MAD signé le 01/03/2028") == []
    assert find_phones("3ayto l Hamid f 06 61 23 45 67") == ["+212661234567"]


def test_infer_dayfirst():
    assert infer_dayfirst(["25/03/2026", "01/02/2026"]) == (True, False)
    assert infer_dayfirst(["03/25/2026"]) == (False, False)
    assert infer_dayfirst(["25/03/2026", "03/25/2026"]) == (None, True)
    assert infer_dayfirst(["2026-03-25", "01/02/2026"]) == (None, False)


def row(**kw):
    base = {"Id": "1", "Account Name": "Acme", "Owner": "Ali", "LastModifiedDate": "2026-07-06"}
    return {**base, **kw}


def test_crm_quarantines_instead_of_guessing():
    r = crm_row_to_record(
        row(
            **{
                "Annual Contract Value": "1.426,000",
                "Renewal Date": "31/02/2027",
                "Phone": "120 000",
            }
        ),
        "crm.json",
        CRMFieldMap(),
        ("sales",),
        MA,
    )
    facts = {f.field for f in r.facts}
    assert "contract_value" not in facts and "renewal_date" not in facts and r.phone is None
    held = {(i.field, i.reason, i.raw) for i in r.issues if i.severity == "quarantined"}
    assert ("contract_value", "ambiguous_separator", "1.426,000") in held
    assert ("renewal_date", "impossible_date", "31/02/2027") in held
    assert ("phone", "missing_country_or_trunk_prefix", "120 000") in held


def test_crm_other_currency_is_quarantined():
    r = crm_row_to_record(
        row(**{"Annual Contract Value": 50000, "Currency": "EUR"}), "x", CRMFieldMap(), ()
    )
    assert not any(f.field == "contract_value" for f in r.facts)
    assert r.issues[0].reason == "unexpected_currency:EUR"


def test_crm_file_with_mixed_date_conventions_refuses_ambiguous_dates(tmp_path):
    rows = [
        row(Id="a", **{"Renewal Date": "25/03/2027"}),  # only readable day-first
        row(Id="b", **{"Renewal Date": "03/25/2027"}),  # only readable month-first
        row(Id="c", **{"Renewal Date": "03/04/2027"}),  # ambiguous: refuse
    ]
    path = tmp_path / "crm.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    records = {r.record_id: r for r in load_crm(path, config=MA)}
    assert [i.reason for i in records["crm:c"].issues] == ["conflicting_date_conventions_in_file"]
    assert not any(f.field == "renewal_date" for f in records["crm:c"].facts)


def test_contract_long_form_dates_and_currency_guard():
    rec = parse_contract(
        CONTRACT.format(sig="17 mars 2026", amt="1,426,000.00 MAD"), "c:1", "x", config=MA
    )["record"]
    assert rec.updated_at == date(2026, 3, 17)
    assert [f.value for f in rec.facts if f.field == "contract_value"] == [1_426_000]
    eur = parse_contract(
        CONTRACT.format(sig="17/03/2026", amt="450 000 EUR"), "c:2", "x", config=MA
    )["record"]
    assert not any(f.field == "contract_value" for f in eur.facts)
    assert eur.issues[0].reason == "unexpected_currency:EUR"
