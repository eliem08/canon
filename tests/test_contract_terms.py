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


HEAD = (
    'This Agreement is made as of March 3, 2021 (the "Effective Date") by and between Atlas '
    'Logistics, Inc. ("Atlas"), and Cedar Analytics LLC ("Cedar").\n'
)


@pytest.mark.parametrize(
    "clause, end",
    [
        ("1. Term. The Term shall commence on the date hereof and shall end as of December 31, "
         "2023.", date(2023, 12, 31)),
        ("TERM: March 3, 2021 to March 2, 2024", date(2024, 3, 2)),
        ("1. Term. This Agreement is for a term of two (2) years.", date(2023, 3, 3)),
        ("1. Term. The Term of this Agreement will commence on the date above and shall continue "
         "for a term of one (1) year.", date(2022, 3, 3)),
        ("1. Term. This Agreement shall remain in effect until the end of the current calendar "
         "year and renew automatically.", date(2021, 12, 31)),
    ],
)  # fmt: skip
def test_more_ways_contracts_state_their_end(clause, end):
    assert read_terms(HEAD + clause, dayfirst=False).end_date.value == end


def test_an_option_to_extend_is_not_the_end_date():
    clause = (
        '1. Term. The "Term" shall begin on the date hereof and shall expire December 31, 2023. '
        "Atlas may elect for the Term to be extended to December 31, 2024."
    )
    assert read_terms(HEAD + clause, dayfirst=False).end_date.value == date(2023, 12, 31)


def test_a_term_that_starts_later_is_not_counted_from_the_effective_date():
    clause = (
        "1. Term. This Agreement is for a term of two (2) years. The start of the Term will be "
        "the launch of the service."
    )
    assert read_terms(HEAD + clause, dayfirst=False).end_date is None


def test_french_term_range():
    start = FR.index("Article 1")
    end = FR.index("Fait à")
    text = FR[:start] + "Article 1 - Durée : du 1er février 2024 au 31 janvier 2026.\n" + FR[end:]
    assert read_terms(text).end_date.value == date(2026, 1, 31)


@pytest.mark.parametrize(
    ("clause", "months"),
    [
        ("This Agreement shall automatically renew for successive one (1) year periods.", 12),
        ("Thereafter the Term renews automatically for additional six (6) month terms.", 6),
        ("The Term shall be automatically renewed for a year unless either party objects.", 12),
        ("Le présent contrat est reconduit tacitement par périodes d'un an.", 12),
        ("Le contrat se renouvellera par tacite reconduction pour deux (2) ans.", 24),
    ],
)
def test_auto_renewal_period(clause, months):
    assert read_terms(EN + clause).renewal_months.value == months


def test_conflicting_renewal_periods_are_refused():
    text = EN + "It shall automatically renew for one (1) year. Renews automatically for 2 years."
    terms = read_terms(text)
    assert terms.renewal_months is None
    assert any(f == "renewal_period_months" for f, _, _ in terms.refused)


def test_renewal_period_is_a_cited_fact():
    text = EN + "Thereafter it shall automatically renew for successive one (1) year periods.\n"
    rec = parse_contract(text, "contract:msa", "contracts/msa.txt", config=US)["record"]
    facts = {f.field: f for f in rec.facts}
    assert facts["renewal_period_months"].value == 12
    assert "automatically renew" in facts["renewal_period_months"].quote


@pytest.mark.parametrize(
    ("clause", "notice"),
    [
        ("It shall automatically renew for one (1) year periods unless either party gives at "
         "least sixty (60) days' prior written notice of non-renewal.", "P60D"),
        ("Renews automatically for one year. Notice of non-renewal at least 3 months before the "
         "renewal date is required to stop renewal.", "P3M"),
        ("Le contrat est reconduit tacitement par périodes d'un an, sauf dénonciation moyennant un "
         "préavis de trois (3) mois.", "P3M"),
    ],
)  # fmt: skip
def test_renewal_notice(clause, notice):
    assert read_terms(EN + clause).notice.value == notice


def test_a_cure_notice_is_not_a_renewal_notice():
    text = EN + "Either party may terminate for breach upon thirty (30) days written notice."
    assert read_terms(text).notice is None


@pytest.mark.parametrize(
    ("clause", "months", "notice"),
    [
        ("Following the Initial Term, this Agreement shall automatically renew for successive "
         "terms of six (6) months unless written notice is given by either Party no later than "
         "thirty (30) days in advance of the expiration of the Initial Term.", 6, "P30D"),
        ("Thereafter, this Agreement shall automatically be renewed for successive 1-year terms.",
         12, None),
        ("It is established by calendar year and renewed tacitly every year.", 12, None),
        ("The Term shall renew on a year to year basis, unless either Party notifies the other at "
         "least 30 days prior to the end of the then current term of its intention not to renew.",
         12, "P30D"),
        ("This Agreement shall be automatically renewed for successive three (3) year terms unless "
         "either Party provides written notice of non-renewal no later than ninety (90) days prior "
         "the end of the Initial Term.", 36, "P90D"),
    ],
)  # fmt: skip
def test_real_contract_renewal_wordings(clause, months, notice):
    terms = read_terms(EN + clause)
    assert terms.renewal_months.value == months
    assert (terms.notice.value if terms.notice else None) == notice


@pytest.mark.parametrize(
    "clause",
    [
        # English "an", not French "an" (year)
        "This Agreement shall automatically renew for an additional period as agreed.",
        # insurance notices of cancellation or non-renewal are about the policy
        "This Agreement renews automatically for one (1) year. Vendor shall have the insurer "
        "provide at least thirty (30) days' advance written notice of cancellation, non-renewal, "
        "or reduction in insurance coverage.",
        # a notice period without any auto-renewal is not a renewal notice
        "This Agreement may be terminated by either party upon thirty (30) days written notice "
        "prior to the end of the term.",
    ],
)
def test_no_renewal_notice_from_lookalikes(clause):
    terms = read_terms(EN + clause)
    assert terms.notice is None
    if "an additional period" in clause:
        assert terms.renewal_months is None
