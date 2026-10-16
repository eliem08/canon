"""Example MCP client: launches the Canon server over stdio and asks the same questions
as three different people, showing that answers depend on who is asking.

    uv run python examples/mcp_client.py [customer name]
"""

from __future__ import annotations

import sys
from pathlib import Path

import anyio
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]
SERVER = StdioServerParameters(
    command=sys.executable,
    args=["-m", "canon.cli", "serve", "--as-of", "2026-10-01", "--store", "out/canon.sqlite"],
    cwd=ROOT,
)
CALLERS = ("revops.admin", "salma.el.idrissi", "hind.legal", "intern")


def fmt(answer: dict | None) -> str:
    if not answer:
        return "—"
    sources = ", ".join(f"{s['source']}:{s['status']}" for s in answer["sources"])
    alts = "; ".join(str(a["value"]) for a in answer["alternatives"])
    out = f"{answer['value']}  (confidence {answer['confidence']:.2f}, from {sources}"
    out += f"; updated {answer['last_updated']})"
    return out + (f"\n      alternatives: {alts}" if alts else "")


async def main(customer: str) -> None:
    async with Client(SERVER) as client:
        tools = await client.list_tools()
        print("tools:", ", ".join(t.name for t in tools.tools))
        for caller in CALLERS:
            print(f"\n=== {caller} asks about {customer!r}")
            args = {"customer": customer, "caller": caller}
            owner = (await client.call_tool("who_owns", args)).structured_content
            if not owner["found"]:
                print("  ", owner["message"])
                continue
            terms = (await client.call_tool("find_contract_terms", args)).structured_content
            conflicts = (await client.call_tool("list_conflicts", args)).structured_content
            print(f"   customer: {owner['customer']['name']} ({owner['customer']['entity_id']})")
            if owner["partial_view"]:
                print("   note: some sources are restricted for this caller")
            print("   owner:", fmt(owner["owner"]) if owner["owner"] else owner["message"])
            for field in ("contract_value", "renewal_date"):
                print(f"   {field}:", fmt(terms["terms"].get(field)))
            print("   conflicts:", ", ".join(c["field"] for c in conflicts["conflicts"]) or "none")


if __name__ == "__main__":
    anyio.run(main, " ".join(sys.argv[1:]) or "Boulangerie Al Baraka")
