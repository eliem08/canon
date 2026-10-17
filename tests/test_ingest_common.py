from datetime import date

import pytest

from canon.ingest.common import (
    business_domain,
    domain_of,
    find_phones,
    normalize_phone,
    parse_date,
    parse_money,
)


@pytest.mark.parametrize(
    "raw",
    ["+212522123456", "05 22 12 34 56", "0522-12-34-56", "00212522123456", "+212 (0)5 22 12 34 56"],
)
def test_phone_formats_normalize_to_e164(raw):
    assert normalize_phone(raw) == "+212522123456"


def test_phone_rejects_garbage():
    assert normalize_phone("12") is None
    assert normalize_phone(None) is None


@pytest.mark.parametrize(
    "raw", ["https://acme.ma/", "http://www.acme.ma", "www.acme.ma", "contact@acme.ma", "ACME.MA"]
)
def test_domain_variants(raw):
    assert domain_of(raw) == "acme.ma"


def test_free_mail_is_not_a_business_domain():
    assert business_domain("hamid.acme@gmail.com") is None
    assert business_domain("hamid@acme.ma") == "acme.ma"


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("450k MAD", 450_000),
        ("1 426 000 MAD", 1_426_000),
        ("1.200.000 DH", 1_200_000),
        ("461,000 MAD", 461_000),
        ("1300000", 1_300_000),
        (745000, 745_000),
        ("Deal signé m3a acme: 1.5k MAD par an", 1_500),
    ],
)
def test_money(raw, value):
    assert parse_money(raw) == value


def test_dates():
    assert parse_date("01/03/2027") == date(2027, 3, 1)
    assert parse_date("2027-03-01") == date(2027, 3, 1)
    assert parse_date("2026-07-06T12:00:00Z") == date(2026, 7, 6)
    assert parse_date("renouvellement f 15/09/2027") == date(2027, 9, 15)
    assert parse_date("bientôt") is None


def test_find_phones_ignores_dates():
    assert find_phones("3ayto l Hamid f 06 61 23 45 67 avant 01/03/2027") == ["+212661234567"]
