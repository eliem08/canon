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
        if {"record_id", "source", "locator"} <= obj.keys():
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
            assert r["found"] is False and r["customer"] is None and r["candidates"] == []
            assert not list(source_refs(r)), (tool, name)
    for entity_id in service.clusters:  # guessing ids does not help either
        assert not service.get_customer(entity_id, "intern").found


@pytest.mark.parametrize(
    "caller", ["revops.admin", "ceo", "hind.legal", "salma.el.idrissi", "intern"]
)
def test_no_response_cites_a_record_the_caller_cannot_see(service, caller):
    groups = service.directory.resolve(caller).groups
    for name in NAMES:
        for tool in TOOLS:
            r = call(service, tool, name, caller).model_dump(mode="json")
            for ref in source_refs(r):
                record = service.records[ref["record_id"]]
                assert groups & set(record.acl), (caller, tool, name, ref["record_id"])


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
    assert denied.structured_content["owner"] is None


def test_pinned_caller_cannot_be_overridden_by_the_model(service):
    async def scenario():
        async with Client(build_server(service, pinned_caller="intern")) as client:
            args = {"customer": "Zitoun", "caller": "revops.admin"}  # model claims admin
            return await client.call_tool("who_owns", args)

    result = anyio.run(scenario)
    assert result.structured_content["found"] is False
