"""Canon MCP server: four typed, permission-aware tools over resolved customer data.

Run over stdio:  uv run canon serve --store out/canon.sqlite --identities <file>
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .schemas import ConflictList, ContractTerms, CustomerProfile, OwnerAnswer
from .service import CanonService

INSTRUCTIONS = """Canon answers questions about customers from resolved, scored company data.
Every answer includes its value, the source records it came from, when it was last updated,
a confidence in [0, 1] and any conflicting alternative values. Always pass the identity of
the person you are acting for as `caller`; results only include data that caller may see.
Prefer citing `sources` and mention low confidence or conflicts to the user."""


def build_server(service: CanonService, pinned_caller: str | None = None) -> MCPServer:
    """Build the MCP server. With `pinned_caller`, every request runs as that identity and
    the `caller` argument is ignored. Use it when the server runs on behalf of one person
    (e.g. a local stdio server), so the model cannot claim someone else's access."""
    server = MCPServer("canon", instructions=INSTRUCTIONS, version="0.4.0")

    def who(caller: str) -> str:
        return pinned_caller if pinned_caller is not None else caller

    @server.tool()
    def get_customer(name: str, caller: str) -> CustomerProfile:
        """Look up a customer by name (any spelling, script or legal form) or entity id.

        Returns its canonical name, aliases and profile fields (domain, phone, tax id, city,
        address, owner, contract value, renewal date), each with sources, last_updated,
        confidence and alternatives. If the name is ambiguous, `found` is false and
        `candidates` lists the options; retry with an entity_id.
        """
        return service.get_customer(name, who(caller))

    @server.tool()
    def find_contract_terms(customer: str, caller: str) -> ContractTerms:
        """Current contract terms for a customer: contract number, annual value, start date,
        renewal date and signatory, from the active (non-superseded) contract when the caller
        may see it. Superseded versions and stale CRM/Slack values appear as alternatives."""
        return service.find_contract_terms(customer, who(caller))

    @server.tool()
    def who_owns(customer: str, caller: str) -> OwnerAnswer:
        """Who owns the customer account internally (account owner / sales rep), with the
        evidence for it and any conflicting previous owners."""
        return service.who_owns(customer, who(caller))

    @server.tool()
    def list_conflicts(customer: str, caller: str) -> ConflictList:
        """Every field where sources disagree for this customer, lowest confidence first,
        with the chosen value, the alternatives and why the winner was chosen."""
        return service.list_conflicts(customer, who(caller))

    return server
