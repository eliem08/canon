import json
from datetime import date
from pathlib import Path

import anyio
import pytest
from mcp import Client

from canon.cli import build_store
from canon.mcp_server import CallerDirectory, CanonService, ServiceConfig, build_server
from canon.score import FactScoringConfig

DATA = Path(__file__).resolve().parents[1] / "data" / "synthetic"
AS_OF = date(2026, 10, 1)
TRUTH = json.loads((DATA / "ground_truth" / "ground_truth.json").read_text(encoding="utf-8"))
NAMES = [e["name"] for e in TRUTH["entities"].values()]
TOOLS = ("get_customer", "find_contract_terms", "who_owns", "list_conflicts")


@pytest.fixture(scope="module")
def service(tmp_path_factory):
    out = tmp_path_factory.mktemp("store")
    build_store(DATA, out, AS_OF)
    return CanonService.from_store(
        out / "canon.sqlite",
        CallerDirectory.from_file(DATA / "identities.json"),
        ServiceConfig(facts=FactScoringConfig(as_of=AS_OF)),
    )


def call(service, tool, customer, caller):
    return getattr(service, tool)(customer, caller)


def source_refs(obj):
    """Every SourceRef-shaped dict anywhere in a response."""
    if isinstance(obj, dict):
        if {"record_id", "source", "weight"} <= obj.keys():
            yield obj
        for v in obj.values():
            yield from source_refs(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from source_refs(v)


# ---------------------------------------------------------------- access control


@pytest.mark.parametrize("caller", ["intern", "mallory-not-in-directory", ""])
def test_unauthorized_callers_get_nothing(service, caller):
    for name in NAMES:
        for tool in TOOLS:
            r = call(service, tool, name, caller).model_dump(mode="json")
            assert (
                r["found"] is False and r.get("customer") is None and r.get("candidates", []) == []
            )
            assert not list(source_refs(r)), (tool, name)
    for entity_id in service.clusters:  # guessing ids does not help either
        assert not service.get_customer(entity_id, "intern").found


@pytest.mark.parametrize(
    "caller", ["revops.admin", "ceo", "hind.legal", "salma.el.idrissi", "intern"]
)
def test_no_response_cites_a_record_the_caller_cannot_see(service, caller):
    groups = service.directory.resolve(caller).groups
    seen = 0
    for name in NAMES:
        for tool in TOOLS:
            r = call(service, tool, name, caller).model_dump(mode="json")
            cited = {ref["record_id"] for ref in source_refs(r)} | set(r.get("records", {}))
            seen += len(cited)
            for rid in cited:
                assert groups & set(service.records[rid].acl), (caller, tool, name, rid)
            assert set(r.get("records", {})) >= {ref["record_id"] for ref in source_refs(r)}
    assert seen > 0 or not groups  # the check must not pass vacuously


def test_role_specific_views(service):
    sales = service.find_contract_terms("Boulangerie Al Baraka", "salma.el.idrissi")
    assert sales.found and sales.documents == [] and sales.partial_view
    assert "No contract visible" in sales.message
    legal = service.who_owns("Boulangerie Al Baraka", "hind.legal")
    assert legal.found and legal.owner is None and legal.partial_view
    admin = service.who_owns("Boulangerie Al Baraka", "revops.admin")
    assert admin.owner is not None and not admin.partial_view


# ---------------------------------------------------------------- answers


def test_every_answer_has_the_required_shape(service):
    profile = service.get_customer("Atlas Logistique", "revops.admin")
    assert profile.found and profile.fields
    for answer in profile.fields.values():
        d = answer.model_dump()
        assert {"value", "sources", "last_updated", "confidence", "alternatives"} <= d.keys()
        assert 0.0 <= answer.confidence <= 1.0 and answer.sources


def test_contract_terms_match_ground_truth_for_full_access(service):
    correct = 0
    for e in TRUTH["entities"].values():
        terms = service.find_contract_terms(e["name"], "revops.admin")
        assert terms.found, e["name"]
        value = terms.terms["contract_value"].value
        correct += abs(float(value) - e["contract_value"]) < 0.5
        correct += terms.terms["renewal_date"].value == e["renewal_date"]
        assert [d.status for d in terms.documents] == ["superseded", "active"]
    assert correct == 2 * len(TRUTH["entities"])


def test_superseded_and_stale_values_are_alternatives(service):
    e = TRUTH["entities"]["E01"]
    terms = service.find_contract_terms(e["name"], "revops.admin")
    value = terms.terms["contract_value"]
    assert value.conflict and value.alternatives
    alt_sources = {s.status for a in value.alternatives for s in a.sources}
    assert "superseded" in alt_sources


def test_lookup_handles_spelling_script_and_ambiguity(service):
    by_arabic = service.get_customer("أطلس لوجيستيك", "revops.admin")
    by_typo = service.get_customer("atlas logistiqeu sarl", "revops.admin")
    assert by_arabic.found and by_typo.found
    assert by_arabic.customer.entity_id == by_typo.customer.entity_id
    ambiguous = service.get_customer("Atlas", "revops.admin")
    assert not ambiguous.found and len(ambiguous.candidates) == 2
    retry = service.get_customer(ambiguous.candidates[0].entity_id, "revops.admin")
    assert retry.found
    assert not service.get_customer("Totally Unknown Widgets", "revops.admin").found


def test_list_conflicts_sorted_by_confidence(service):
    conflicts = service.list_conflicts("Atlas Logistique", "revops.admin").conflicts
    assert conflicts and all(c.conflict and c.alternatives for c in conflicts)
    assert [c.confidence for c in conflicts] == sorted(c.confidence for c in conflicts)


# ---------------------------------------------------------------- over MCP


def test_tools_over_mcp_protocol(service):
    async def scenario():
        async with Client(build_server(service)) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            assert set(tools) == set(TOOLS)
            for t in tools.values():
                assert "caller" in t.input_schema["required"]
            ok = await client.call_tool("who_owns", {"customer": "Zitoun", "caller": "ceo"})
            denied = await client.call_tool("who_owns", {"customer": "Zitoun", "caller": "intern"})
            return ok, denied

    ok, denied = anyio.run(scenario)
    assert not ok.is_error and ok.structured_content["found"] is True
    assert ok.structured_content["owner"]["value"]
    assert denied.structured_content["found"] is False
    assert denied.structured_content.get("owner") is None


def test_pinned_caller_cannot_be_overridden_by_the_model(service):
    async def scenario():
        async with Client(build_server(service, pinned_caller="intern")) as client:
            args = {"customer": "Zitoun", "caller": "revops.admin"}  # model claims admin
            return await client.call_tool("who_owns", args)

    result = anyio.run(scenario)
    assert result.structured_content["found"] is False


# ---------------------------------------------------------------- compact responses


def test_fields_argument_returns_only_what_was_asked(service):
    phone = service.get_customer("Atlas Logistique", "revops.admin", fields=["phone"])
    assert set(phone.fields) == {"phone"} and phone.aliases == []
    full = service.get_customer("Atlas Logistique", "revops.admin")
    assert {"name", "phone", "owner", "contract_value"} <= set(full.fields) and full.aliases
    terms = service.find_contract_terms("Atlas Logistique", "revops.admin", ["renewal_date"])
    assert set(terms.terms) == {"renewal_date"} and terms.documents


def test_responses_are_compact_but_every_citation_resolves(service):
    r = service.find_contract_terms("Atlas Logistique", "revops.admin")
    data = r.model_dump(mode="json")
    refs = list(source_refs(data))
    assert refs and all("locator" not in ref and "value" not in ref for ref in refs)
    assert {ref["record_id"] for ref in refs} <= set(data["records"])  # locators listed once
    value = r.terms["contract_value"]
    assert len(value.sources) <= 3 and value.sources[0].quote  # strongest source quoted
    assert all(s.quote is None for s in value.sources[1:])
    assert "null" not in json.dumps(data)  # empty fields are omitted...
    assert "alternatives" in data["terms"]["contract_value"]  # ...except required ones


def test_alternatives_keep_the_superseded_source(service):
    value = service.find_contract_terms("Atlas Logistique", "revops.admin").terms["contract_value"]
    statuses = {s.status for a in value.alternatives for s in a.sources}
    assert "superseded" in statuses


def test_indexed_lookup_matches_a_full_scan(service, monkeypatch):
    """The name index is an optimization only: results equal scoring every entity."""
    import canon.mcp_server.service as svc

    queries = [*NAMES, *(n.lower() for n in NAMES), "atlas logistiqeu sarl", "أطلس لوجيستيك"]
    queries += ["AFC", "Rif Cement", "chrikat Zitoun", "khg", "Atlas", "no such company"]
    questions = json.loads((DATA / "ground_truth" / "eval_questions.json").read_text("utf-8"))
    queries += [q["mention"] for q in questions]
    paraphrases = json.loads(
        (DATA.parent / "eval" / "paraphrase_questions.json").read_text("utf-8")
    )
    from canon.evals.agents import candidate_spans

    queries += [s for q in paraphrases["questions"] for s in candidate_spans(q["question"], 6)]
    callers = ("revops.admin", "salma.el.idrissi", "hind.legal")
    indexed = {
        (q, c): service._match(q, service.directory.resolve(c)) for q in queries for c in callers
    }
    monkeypatch.setattr(svc, "_name_keys", lambda f: set())  # no keys -> score every entity
    for (q, c), got in indexed.items():
        assert got == service._match(q, service.directory.resolve(c)), (q, c)


def test_example_client_runs_against_the_server(service, capsys):
    """examples/mcp_client.py is what a prospect sees in the demo: keep it working."""
    import importlib.util

    path = DATA.parents[1] / "examples" / "mcp_client.py"
    spec = importlib.util.spec_from_file_location("mcp_client_example", path)
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)

    async def scenario():
        async with Client(build_server(service)) as client:
            await example.show(client, "Boulangerie Al Baraka")

    anyio.run(scenario)
    out = capsys.readouterr().out
    assert "1426000.0" in out and "restricted for this caller" in out
    assert "intern asks" in out and "No customer found." in out
