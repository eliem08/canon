"""Free-form contract terms (canon/ingest/contract_terms.py). Texts are written for the tests."""

from datetime import date

import pytest

from canon.ingest.config import IngestConfig
from canon.ingest.contract_terms import read_terms
from canon.ingest.contracts import counterparty, parse_contract

US = IngestConfig(dayfirst=False, currency="USD", default_country="1")

EN = """EXHIBIT 10.4
MASTER SERVICES AGREEMENT

This Master Services Agreement (the "Agreement") is made as of March 3, 2021 (the "Effective
Date") by and between Atlas Logistics, Inc., a Delaware corporation having its principal place of
business at 10 Main Street, Wilmington, DE 19801 ("Atlas"), and Cedar Analytics LLC, a California
limited liability company ("Cedar").

WHEREAS, the parties entered into a Mutual Nondisclosure Agreement, dated as of January 5, 2020
(the "NDA Agreement");

1. Term. The initial term of this Agreement shall be for a period of three (3) years commencing
on the Effective Date, unless terminated earlier.
"""

FR = """CONTRAT DE PRESTATION DE SERVICES

Entre les soussignés :
Rif Ciments SA, société anonyme au capital de 10 000 000 MAD, dont le siège social est à Tanger,
ci-après dénommée « le Client »,
et
Atlas Data SARL, au capital de 100 000 MAD, ci-après dénommée « le Prestataire ».

Il a été convenu ce qui suit :
Article 1 - Durée. Le présent contrat prend effet le 1er février 2024. Le présent contrat est
conclu pour une durée de deux (2) ans à compter de la Date d'effet.
Fait à Tanger, le 15 janvier 2024.
"""


def test_english_preamble():
    t = read_terms(EN, dayfirst=False)
    assert [p.value for p in t.parties] == ["Atlas Logistics, Inc", "Cedar Analytics LLC"]
    assert t.agreement_date.value == date(2021, 3, 3)
    assert t.effective_date.value == date(2021, 3, 3)
    # three years from the Effective Date, computed and flagged as derived
    assert t.end_date.value == date(2024, 3, 3)
    assert t.end_date.warnings == ("derived_from_term_length",)
    assert not t.refused


def test_french_preamble():
    t = read_terms(FR)
    assert [p.value for p in t.parties] == ["Rif Ciments SA", "Atlas Data SARL"]
    assert t.agreement_date.value == date(2024, 1, 15)
    assert t.effective_date.value == date(2024, 2, 1)
    assert t.end_date.value == date(2026, 2, 1)


def test_a_date_that_names_another_document_is_not_this_contracts_date():
    text = (
        "AMENDMENT NO. 1\nWHEREAS, the parties previously entered into the Supply Agreement dated "
        'June 1, 2019 (the "Supply Agreement").\nThis Amendment is entered into by and between '
        'Atlas Logistics, Inc. ("Atlas") and Cedar Analytics LLC ("Cedar").'
    )
    assert read_terms(text, dayfirst=False).agreement_date is None


def test_conflicting_end_dates_are_refused():
    text = EN + (
        "\n2. This Agreement shall expire on June 30, 2023.\n"
        "3. This Agreement shall expire on June 30, 2025.\n"
    )
    t = read_terms(text, dayfirst=False)
    assert t.end_date is None
    assert [r[0] for r in t.refused] == ["renewal_date"]
    assert t.refused[0][2] == "conflicting_values_in_contract"


def test_a_stated_end_date_beats_one_computed_from_the_term_length():
    text = EN + "\n2. This Agreement shall expire on March 2, 2024.\n"
    t = read_terms(text, dayfirst=False)
    assert t.end_date.value == date(2024, 3, 2) and t.end_date.warnings == ()


@pytest.mark.parametrize(
    "text",
    [
        'This Agreement is between Licensor and Licensee. "Licensor" means Acme; "Licensee" '
        "means Beta.",  # defined terms, not names
        "Any dispute between Monday through Friday shall be heard.",
        'The Term ends on the last day of each Calendar Quarter. "Calendar Quarter" means a '
        "quarter ending on June 30, 2019.",
    ],
)
def test_no_terms_from_text_that_only_looks_like_a_preamble(text):
    t = read_terms(text, dayfirst=False)
    assert t.parties == [] and t.end_date is None


def test_numeric_dates_follow_the_deployment_convention():
    text = 'This Agreement is dated 03/04/2021 by and between Atlas Inc. ("A") and Beta LLC ("B").'
    assert read_terms(text, dayfirst=False).agreement_date.value == date(2021, 3, 4)
    assert read_terms(text, dayfirst=True).agreement_date.value == date(2021, 4, 3)
    assert read_terms(text).agreement_date is None  # order not stated: refuse, never guess


def test_counterparty_needs_the_deployments_own_names():
    parties = ["Atlas Logistics, Inc", "Cedar Analytics LLC"]
    assert counterparty(parties, ()) is None  # who is the customer? not stated: refuse
    assert counterparty(parties, ("Cedar Analytics",)) == "Atlas Logistics, Inc"
    assert counterparty(parties, ("Someone Else SA",)) is None  # neither party is us


def test_parse_contract_reads_free_form_contracts_with_citations():
    own = IngestConfig(dayfirst=False, currency="USD", own_names=("Cedar Analytics LLC",))
    rec = parse_contract(EN, "contract:msa", "contracts/msa.txt", config=own)["record"]
    assert rec.name == "Atlas Logistics, Inc"
    assert rec.parties == ["Atlas Logistics, Inc", "Cedar Analytics LLC"]
    assert rec.updated_at == date(2021, 3, 3)
    facts = {f.field: f for f in rec.facts}
    assert facts["contract_start"].value == "2021-03-03"
    assert facts["renewal_date"].value == "2024-03-03"
    assert facts["renewal_date"].source_ref == "contracts/msa.txt#p1:L12"
    assert "three (3) years" in facts["renewal_date"].quote
    assert any(i.reason == "derived_from_term_length" for i in rec.issues)
    # without its own names the deployment cannot tell which party is the customer
    rec = parse_contract(EN, "contract:msa", "contracts/msa.txt", config=US)["record"]
    assert rec.name is None and len(rec.parties) == 2


def test_the_template_still_wins_over_the_free_form_reader():
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "data/synthetic/contracts/CN-2024-107_v2.txt"
    text = path.read_text(encoding="utf-8")
    rec = parse_contract(text, "c", "x")["record"]
    assert rec.name and not [i for i in rec.issues if i.reason.startswith("conflicting")]
