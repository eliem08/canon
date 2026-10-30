"""Example MCP client: launches the Canon server over stdio and asks the same questions
as three different people, showing that answers depend on who is asking.

    uv run python examples/mcp_client.py [customer name]
    uv run python examples/mcp_client.py --west [customer name]   # US demo data

The Moroccan default reads out/canon.sqlite (`canon resolve`); `--west` reads out_west/canon.sqlite
(`canon pilot --data data/synthetic_west --out out_west`).
"""

from __future__ import annotations

import sys
from pathlib import Path

import anyio
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]
WEST = "--west" in sys.argv
DATA, STORE = ("data/synthetic_west", "out_west") if WEST else ("data/synthetic", "out")
SERVER = StdioServerParameters(
    command=sys.executable,
    args=["-m", "canon.cli", "serve", "--as-of", "2026-10-01", "--store", f"{STORE}/canon.sqlite",
          "--data", DATA],
    cwd=ROOT,
)  # fmt: skip
CALLERS = (
    ("revops.admin", "sarah.chen", "dana.legal", "intern")
    if WEST
    else ("revops.admin", "salma.el.idrissi", "hind.legal", "intern")
)


def fmt(answer: dict | None) -> str:
    if not answer:
        return "—"
    sources = ", ".join(f"{s['source']}:{s['status']}" for s in answer.get("sources", []))
    alts = "; ".join(str(a["value"]) for a in answer.get("alternatives", []))
    out = f"{answer['value']}  (confidence {answer['confidence']:.2f}, from {sources}"
    out += f"; updated {answer.get('last_updated')})"
    return out + (f"\n      alternatives: {alts}" if alts else "")


async def show(client: Client, customer: str) -> None:
    """Ask the same questions as each caller. Responses omit empty fields, hence `.get`."""
    tools = await client.list_tools()
    print("tools:", ", ".join(t.name for t in tools.tools))
    for caller in CALLERS:
        print(f"\n=== {caller} asks about {customer!r}")
        args = {"customer": customer, "caller": caller}
        owner = (await client.call_tool("who_owns", args)).structured_content
        if not owner["found"]:
            print("  ", owner.get("message", "not found"))
            continue
        terms = (await client.call_tool("find_contract_terms", args)).structured_content
        conflicts = (await client.call_tool("list_conflicts", args)).structured_content
        print(f"   customer: {owner['customer']['name']} ({owner['customer']['entity_id']})")
        if owner.get("partial_view"):
            print("   note: some sources are restricted for this caller")
        print("   owner:", fmt(owner.get("owner")) if owner.get("owner") else owner.get("message"))
        for field in ("contract_value", "renewal_date"):
            print(f"   {field}:", fmt(terms.get("terms", {}).get(field)))
        fields = [c["field"] for c in conflicts.get("conflicts", [])]
        print("   conflicts:", ", ".join(fields) or "none")


async def main(customer: str) -> None:
    async with Client(SERVER) as client:
        await show(client, customer)


if __name__ == "__main__":
    words = [a for a in sys.argv[1:] if a != "--west"]
    anyio.run(main, " ".join(words) or ("Harbor Foods" if WEST else "Boulangerie Al Baraka"))
