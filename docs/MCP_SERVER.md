# Canon MCP server (Milestone 4)

A permission-aware [MCP](https://modelcontextprotocol.io) server over Canon's resolved,
scored customer data. It is built on the official MCP Python SDK (`mcp` 2.x, `MCPServer`) and
runs over stdio.

## Tools

Every tool takes a `caller` (the identity of the person the agent acts for) and returns
typed, structured output (see `canon/mcp_server/schemas.py`).

| Tool | Arguments | Returns |
|---|---|---|
| `get_customer` | `name`, `caller` | canonical name, aliases, and profile fields: domain, phone, tax id, city, address, owner, contract value, renewal date |
| `find_contract_terms` | `customer`, `caller` | contract number, annual value, start, renewal date, signatory, plus the visible contract versions with status |
| `who_owns` | `customer`, `caller` | internal account owner |
| `list_conflicts` | `customer`, `caller` | every field where sources disagree, lowest confidence first |

Every individual answer is an `Answer`. This one is `find_contract_terms("Boulangerie Al Baraka", caller="hind.legal")`, as of 2026-10-01:

```json
{
  "field": "contract_value",
  "value": 1426000.0,
  "confidence": 0.8541,
  "last_updated": "2026-03-17",
  "sources": [{"record_id": "contract:CN-2023-135_v2", "source": "contract", "status": "active",
               "locator": "data/synthetic/contracts/CN-2023-135_v2.txt",
               "observed_at": "2026-03-17", "value": 1426000.0, "weight": 0.95}],
  "alternatives": [{"value": 1085000.0, "score": 0.1067, "last_updated": "2023-11-25",
                    "sources": [{"record_id": "contract:CN-2023-135_v1", "source": "contract",
                                 "status": "superseded", "weight": 0.1067, "...": "..."}]}],
  "conflict": true,
  "explanation": "2 conflicting values; kept 1426000.0 (score 0.95, best source contract/active from 2026-03-17) over 1085000.0 (score 0.11)"
}
```

Each response also carries:

* `found`, `message`
* `customer`: `entity_id`, `name`, `match_score`
* `candidates`: set when a name is ambiguous, e.g. "Atlas" matches both Atlas Logistique and
  Atlas Tours. Retry with the `entity_id`.
* `partial_view`: true when some of the customer's sources are restricted for this caller.

`customer`/`name` accepts any spelling, legal form or script (`atlas logistiqeu sarl`,
`أطلس لوجيستيك`) or an `entity_id`.

## Permissions

* Source records carry ACL groups: CRM → `sales`, `exec`; Slack → `sales`; contracts → `legal`,
  `exec`. Connectors set these and they are configurable.
* A caller directory (`data/synthetic/identities.json`) maps caller ids to groups. Unknown
  callers have no groups.
* **Filtering happens before scoring.** Each request recomputes an entity's facts from only the
  records the caller can see. A value asserted only by a hidden source can never win, appear as
  an alternative, or shift a confidence.
* An entity with no visible records does not exist for that caller: lookups by name or by guessed
  `entity_id` return `found: false`, the same as for an unknown company.
* `partial_view` tells the agent that restricted sources exist (not what they say), so it can
  suggest asking someone with broader access instead of asserting a stale value.

The same question gets different, correct-for-the-caller answers. Here is "Boulangerie Al Baraka",
from `examples/mcp_client.py`:

| Caller | Groups | Owner | Contract value |
|---|---|---|---|
| `revops.admin` | sales, legal, exec | Youssef Benali (0.24) | 1,426,000 (0.51, contract; CRM's stale 1,085,000 kept as an alternative) |
| `salma.el.idrissi` | sales | Youssef Benali (0.24) | 1,085,000 (0.80, CRM only), `partial_view` |
| `hind.legal` | legal | not visible | 1,426,000 (0.85, contracts only), `partial_view` |
| `intern` | — | `found: false` | `found: false` |

Tests (`tests/test_mcp.py`) check that unauthorized callers get nothing from any tool for any
customer, and that no response from any caller ever cites a record that caller cannot read.

### Identity binding

The `caller` argument is chosen by the model, so on its own it is **self-asserted**. Two modes:

* **Pinned (recommended for personal/local use):** `canon serve --caller <id>` runs every
  request as that identity and ignores the argument. A test checks the model cannot override it.
* **Shared server:** bind identity from the transport (MCP OAuth / `token_verifier` on an HTTP
  transport) and ignore or verify the argument. This is not implemented yet.

## Run it

```bash
uv sync
uv run canon serve --as-of 2026-10-01                 # stdio; builds out/canon.sqlite if missing
uv run canon serve --caller salma.el.idrissi          # pin identity
uv run python examples/mcp_client.py "Zitoun"         # example client: same questions, 4 callers
```

Options: `--store` (default `out/canon.sqlite`), `--data` (rebuild source),
`--identities` (default `data/synthetic/identities.json`), `--rebuild`, `--as-of`
(freshness reference date; default today).

## Connect it to Claude

**Claude Code**, from the repo root:

```bash
claude mcp add canon -- uv run --directory "$PWD" canon serve --caller salma.el.idrissi
```

Then ask, for example, "Who owns Boulangerie Al Baraka and when does their contract renew?"
Drop `--caller` to let the agent pass `caller` itself (demo only; see Identity binding). In that
case, tell Claude who it is acting for, e.g. "I am hind.legal".

**Claude Desktop**: add to `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "canon": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/canon", "canon", "serve",
               "--caller", "salma.el.idrissi"]
    }
  }
}
```

Restart Claude Desktop, and the four tools appear under the connector.

## Known gaps

* **Self-asserted identity:** without `--caller`, `caller` is self-asserted. Shared deployments
  need transport-level auth.
* **Group-level ACLs only:** per-field or row-level policies (e.g. "sales may see owner but not
  contract value from CRM") would need field-scoped ACLs on `Fact`.
* **Clusters ignore ACLs:** entity resolution runs over all records. A caller can't see hidden
  records, but whether two visible records were linked can depend on a hidden one, which leaks a
  tiny amount of information.
* **Per-request recomputation:** facts are rescored on every request. That's fine at this scale;
  production should cache per (entity, group-set).
