"""Day-1 intake: `canon.json` deployment file, `canon check`, client question sheets."""

import csv
import json
import shutil
from pathlib import Path

import pytest

from canon.evals.questions import load_questions
from canon.ingest import load_all
from canon.ingest.deployment import load_deployment, parse_deployment
from canon.ingest.testdocs import xlsx
from canon.intake import check_export, render_check, suggest_column, suggested_deployment

MA = {"default_country": "212", "currency": "MAD"}  # these tests use Moroccan data

DATA = Path(__file__).resolve().parents[1] / "data" / "synthetic"

# A HubSpot-style export of the same accounts: other column names, one false friend.
HUBSPOT = {
    "Id": "Record ID",
    "Account Name": "Company name",
    "Website": "Website URL",
    "Phone": "Phone Number",
    "Primary Contact Email": "Email",
    "Billing Street": "Street Address",
    "Billing City": "City",
    "ICE": "Tax ID",
    "Owner": "Company owner",
    "Annual Contract Value": "ACV",
    "Renewal Date": "Contract renewal date",
    "Currency": "Currency",
    "LastModifiedDate": "Last Modified Date",
    "Industry": "Industry",
}


def _rows() -> list[dict]:
    return json.loads((DATA / "crm" / "accounts.json").read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: list[dict], rename: dict, extra: dict | None = None) -> None:
    out = [
        {rename[k]: ("" if v is None else v) for k, v in r.items()} | (extra or {}) for r in rows
    ]
    columns = list(dict.fromkeys(k for r in out for k in r))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, columns)
        writer.writeheader()
        writer.writerows(out)


def _crm_view(records) -> dict:
    return {
        r.record_id: (
            r.name,
            r.phone,
            r.tax_id,
            r.city,
            sorted((f.field, f.value) for f in r.facts),
        )
        for r in records
        if r.source == "crm"
    }


@pytest.fixture
def hubspot(tmp_path):
    for part in ("slack", "contracts"):
        shutil.copytree(DATA / part, tmp_path / part)
    shutil.copy(DATA / "identities.json", tmp_path)
    _write_csv(
        tmp_path / "crm" / "companies.csv", _rows(), HUBSPOT, {"Annual Revenue": "90 000 000"}
    )
    return tmp_path


def test_without_a_deployment_file_an_unnamed_crm_export_is_flagged(hubspot):
    report = check_export(hubspot)
    assert not report["ok"] and report["crm_unnamed"] == ["crm/companies.csv"]
    assert suggested_deployment(report) == {"crm": {"file": "crm/companies.csv"}}


def test_check_suggests_the_mapping_and_the_suggestion_reproduces_the_default_export(hubspot):
    (hubspot / "canon.json").write_text(
        json.dumps({"crm": {"file": "crm/companies.csv"}, "ingest": MA})
    )
    report = check_export(hubspot)
    crm = report["crm"][0]
    assert report["ok"] and crm["mapped"] == {"currency": "Currency"}
    got = {k: v["column"] for k, v in crm["suggested"].items()}
    expected = {
        "id": "Record ID",
        "name": "Company name",
        "website": "Website URL",
        "phone": "Phone Number",
        "email": "Email",
        "street": "Street Address",
        "city": "City",
        "tax_id": "Tax ID",
        "owner": "Company owner",
        "contract_value": "ACV",
        "renewal_date": "Contract renewal date",
        "modified": "Last Modified Date",
    }
    assert got == expected
    # the company's revenue is not the contract value: left unused, never suggested
    assert "Annual Revenue" in crm["unused_columns"]
    assert crm["fields"]["contract_value"]["filled"] == len(_rows())
    # the suggested file, once a person copies it in, ingests exactly like the default export
    (hubspot / "canon.json").write_text(json.dumps({**suggested_deployment(report), "ingest": MA}))
    from_hubspot = _crm_view(load_all(hubspot))
    default = _crm_view(load_all(DATA))
    assert from_hubspot.keys() == default.keys()
    assert from_hubspot == default
    assert "Suggested mappings" in render_check(report)


def test_french_column_names(tmp_path):
    french = {
        "Id": "ID du compte",
        "Account Name": "Raison sociale",
        "Owner": "Responsable du compte",
        "Annual Contract Value": "Montant annuel",
        "Renewal Date": "Date de renouvellement",
        "LastModifiedDate": "Dernière modification",
        "Billing City": "Ville",
        "Phone": "Téléphone",
    }
    columns = [*french.values(), "Secteur"]
    taken: set[str] = set()
    for field, col in [
        ("id", "ID du compte"),
        ("name", "Raison sociale"),
        ("owner", "Responsable du compte"),
        ("contract_value", "Montant annuel"),
        ("renewal_date", "Date de renouvellement"),
        ("modified", "Dernière modification"),
        ("city", "Ville"),
        ("phone", "Téléphone"),
    ]:
        assert suggest_column(field, columns, taken) == (col, "alias"), field
    assert suggest_column("tax_id", columns, taken) is None  # "Secteur" is not a tax id


def test_false_friends_are_not_suggested():
    assert suggest_column("contract_value", ["Annual Revenue", "Amount"], set()) is None
    assert suggest_column("modified", ["Last Activity Date"], set()) is None


def test_missing_name_column_blocks(tmp_path):
    rename = {k: k for k in HUBSPOT} | {"Account Name": "Libellé"}
    _write_csv(tmp_path / "crm" / "accounts.csv", _rows(), rename)
    report = check_export(tmp_path)
    assert not report["ok"] and report["crm"][0]["blocking"] == ["name"]
    assert "Blocking" in render_check(report)


def test_refusals_are_counted_per_field(tmp_path):
    rows = _rows()
    rows[0]["Annual Contract Value"] = "1 200 000 EUR"
    rows[1]["ICE"] = "0012#3456"
    _write_csv(tmp_path / "crm" / "accounts.csv", rows, {k: k for k in HUBSPOT})
    (tmp_path / "canon.json").write_text(json.dumps({"ingest": MA}))
    fields = check_export(tmp_path)["crm"][0]["fields"]
    assert fields["contract_value"]["refused"] == 1 and fields["tax_id"]["refused"] == 1


def test_deployment_file_overrides_acls(tmp_path):
    shutil.copytree(DATA / "crm", tmp_path / "crm")
    shutil.copytree(DATA / "contracts", tmp_path / "contracts")
    (tmp_path / "canon.json").write_text(
        json.dumps({"crm": {"acl": ["revops"]}, "contracts": {"acl": ["legal"]}})
    )
    records = load_all(tmp_path)
    assert {tuple(r.acl) for r in records if r.source == "crm"} == {("revops",)}
    assert {tuple(r.acl) for r in records if r.source == "contract"} == {("legal",)}


@pytest.mark.parametrize(
    "bad, message",
    [
        ({"crm": {"colums": {}}}, "unknown key"),
        ({"crm": {"columns": {"owener": "Owner"}}}, "owener"),
        ({"ingest": {"curency": "EUR"}}, "curency"),
        ({"slack": {"acl": "sales"}}, "list of group names"),
        ({"crm": {"columns": {"owner": ""}}}, "column names"),
    ],
)
def test_typos_in_the_deployment_file_are_errors(bad, message):
    with pytest.raises(ValueError, match=message):
        parse_deployment(bad)


def test_missing_crm_file_is_an_error(tmp_path):
    (tmp_path / "canon.json").write_text(json.dumps({"crm": {"file": "crm/nope.csv"}}))
    with pytest.raises(ValueError, match="does not exist"):
        load_deployment(tmp_path).crm_paths(tmp_path)


def test_synthetic_data_needs_only_its_conventions_in_the_deployment_file():
    report = check_export(DATA)
    assert report["ok"] and report["deployment_file"]
    assert json.loads((DATA / "canon.json").read_text(encoding="utf-8")) == {"ingest": MA}
    assert suggested_deployment(report) is None


# ---------------------------------------------------------------- client question sheets

SHEET = [
    {
        "id": "q1",
        "type": "contract_value",
        "question": "ACV of Rif Cement?",
        "expected": "2,4 M MAD",
    },
    {
        "id": "q2",
        "type": "renewal_date",
        "question": "Renouvellement Atlas ?",
        "expected": "25/03/2027",
    },
    {"id": "", "type": "owner", "question": "Who owns Zitoun?", "expected": " Omar Fassi "},
    {"id": "", "type": "", "question": "", "expected": ""},  # blank row
]


def test_questions_from_csv(tmp_path):
    path = tmp_path / "questions.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, ["id", "type", "question", "expected"])
        writer.writeheader()
        writer.writerows(SHEET)
    qs = load_questions(path)
    assert [(q.id, q.expected) for q in qs] == [
        ("q1", 2_400_000.0),
        ("q2", "2027-03-25"),
        ("row4", "Omar Fassi"),
    ]


def test_questions_from_xlsx_with_excel_dates_and_numbers(tmp_path):
    rows = [
        {"ID": "a", "Type": "contract_value", "Question": "ACV?", "Expected": 461000},
        {"ID": "b", "Type": "renewal_date", "Question": "Renewal?", "Expected": "2027-03-25"},
    ]
    path = tmp_path / "q.xlsx"
    path.write_bytes(xlsx(rows, ("Expected",)))
    qs = load_questions(path)
    assert [(q.id, q.expected) for q in qs] == [("a", 461000.0), ("b", "2027-03-25")]


@pytest.mark.parametrize(
    "row, message",
    [
        ({"type": "renewal_date", "expected": "03/04/2027"}, "ambiguous"),
        ({"type": "contract_value", "expected": "1,2 ou 1,4 M"}, "refused"),
        ({"type": "headcount", "expected": "12"}, "type must be"),
        ({"type": "owner", "expected": ""}, "no expected"),
    ],
)
def test_question_sheet_refuses_rather_than_guesses(tmp_path, row, message):
    path = tmp_path / "q.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, ["id", "type", "question", "expected"])
        writer.writeheader()
        writer.writerow({"id": "x", "question": "?", **row})
    with pytest.raises(ValueError, match=message):
        load_questions(path)


def test_two_digit_years_need_the_century_in_the_deployment_file(tmp_path):
    rows = _rows()[:3]
    for r in rows:
        r["Renewal Date"] = "25/03/27"
    _write_csv(tmp_path / "crm" / "accounts.csv", rows, {k: k for k in HUBSPOT})
    refused = load_all(tmp_path)
    assert all(not [f for f in r.facts if f.field == "renewal_date"] for r in refused)
    assert all(any(i.reason == "two_digit_year" for i in r.issues) for r in refused)
    (tmp_path / "canon.json").write_text(
        json.dumps({"ingest": {**MA, "century": 20, "dayfirst": True}})
    )
    read = load_all(tmp_path)
    assert {f.value for r in read for f in r.facts if f.field == "renewal_date"} == {"2027-03-25"}
