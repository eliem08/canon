# Canon MCP server (Milestone 4)

A permission-aware [MCP](https://modelcontextprotocol.io) server over Canon's resolved,
scored customer data. It is built on the official MCP Python SDK (`mcp` 2.x, `MCPServer`) and
runs over stdio.

## Tools

Every tool takes a `caller` (the identity of the person the agent acts for) and returns
typed, structured output (see `canon/mcp_server/schemas.py`).

| Tool | Arguments | Returns |
|---|---|---|
| `get_customer` | `name`, `caller`, optional `fields` | canonical name, aliases, and profile fields: domain, phone, tax id, city, address, owner, contract value, renewal date |
| `find_contract_terms` | `customer`, `caller`, optional `fields` | contract number, annual value, start, renewal date, signatory, plus the visible contract versions with status |
| `who_owns` | `customer`, `caller` | internal account owner |
| `list_conflicts` | `customer`, `caller` | every field where sources disagree, lowest confidence first |

Every individual answer is an `Answer`. This is `find_contract_terms("Boulangerie Al Baraka", caller="hind.legal",
fields=["contract_value"])`, as of 2026-10-01 (`documents` omitted):

```json
{
  "found": true,
  "partial_view": true,
  "customer": {"entity_id": "Eacdf3bf222", "name": "Boulangerie Al Baraka SARL", "match_score": 1.0},
  "records": {"contract:CN-2023-135_v1": "data/synthetic/contracts/CN-2023-135_v1.txt",
              "contract:CN-2023-135_v2": "data/synthetic/contracts/CN-2023-135_v2.txt"},
  "terms": {"contract_value": {
    "field": "contract_value", "value": 1426000.0, "confidence": 0.8541, "last_updated": "2026-03-17",
    "sources": [{"record_id": "contract:CN-2023-135_v2", "source": "contract", "status": "active",
                 "observed_at": "2026-03-17", "weight": 0.95, "source_ref": "#p1:L17",
                 "quote": "Article 4 - Prix. Le montant annuel est fixé à 1 426 000 MAD HT."}],
    "alternatives": [{"value": 1085000.0, "score": 0.1067, "last_updated": "2023-11-25",
                      "sources": [{"record_id": "contract:CN-2023-135_v1", "source": "contract",
                                   "status": "superseded", "observed_at": "2023-11-25",
                                   "weight": 0.1067, "source_ref": "#p1:L17"}]}],
    "conflict": true,
    "explanation": "2 conflicting values; kept 1426000.0 (score 0.95, best source contract/active from 2026-03-17) over 1085000.0 (score 0.11)"}}
}
```

**Compact by design.** Each file or channel path appears once, in `records`. Sources cite a position in it
(`#p1:L17`, `#ts=...`). At most 3 sources are listed per answer (`more_sources` counts the rest), and only
the strongest one carries its quote. Each alternative lists its strongest source plus one with a different
status, so a superseded contract still shows. Fields that are empty or at their default are omitted, except
that every answer always has `value`, `confidence`, `last_updated`, `sources` and `alternatives`. With
`fields=[...]`, the eval's Canon context dropped from 7.2k to 1.4k characters per answer, smaller than the
strong RAG baseline's 3.7k, with the same accuracy.

Each response also carries:

* `found`, `message` (if any), `records` (record id → where it lives), `withheld` (if any)
* `customer`: `entity_id`, `name`, `match_score`
* `candidates`: set when a name is ambiguous, e.g. "Atlas" matches both Atlas Logistique and
  Atlas Tours. Retry with the `entity_id`.
* `partial_view`: true when some of the customer's sources are restricted for this caller.

`customer`/`name` accepts any spelling, legal form or script (`atlas logistiqeu sarl`,
`أطلس لوجيستيك`) or an `entity_id`.

## Permissions

* Source records carry ACL principals: CRM → `sales`, `exec`; public Slack channels → `sales`;
  contracts → `legal`, `exec`, or whatever the nearest `_acl.json` in the contracts folder says
  (`{"acl": ["exec"]}`). **Private Slack channels** (`groups.json` in the export) are readable only
  by their members, as `slack-user:<id>` principals.
* A caller directory (`data/synthetic/identities.json`) maps caller ids to groups, plus an
  optional `slack_user_id` that grants that user's private channels. Unknown callers have no groups.
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
* **Shared server (HTTP + bearer tokens):** `canon serve --http --tokens tokens.json`. Every
  request needs `Authorization: Bearer <token>`, and the token's caller replaces the `caller`
  argument. Tokens come from `canon token add --caller <id>` (printed once). The file stores only
  SHA-256 hashes and is re-read per request, so `canon token revoke --caller <id>` works without a
  restart. Tests run a real HTTP server and check that a sales argument can't widen a legal
  token's view, and that missing, wrong or revoked tokens get 401.

### Prompt injection

Canon returns text written by third parties (message quotes, names, addresses, contract lines).
Text matching injection patterns (FR/EN/Darija: "ignore previous instructions", chat-role markup,
"you are now", tool-hijack and exfiltration phrasings, zero-width obfuscation) is replaced with
`[withheld: ...]`, and the response's `withheld` count tells the agent. Parsed values (amounts,
dates) are kept: only the free text is withheld. The same check runs at ingest and lists hits in
`quarantine.json` as `possible_prompt_injection:<rule>`. The server instructions also tell the agent
that source text is data. The pattern list is one layer, not a guarantee: paraphrased injections
will get through.

### Audit log

`canon serve --audit-log audit.jsonl` appends one line per tool call: timestamp, tool, caller,
whether the caller is in the directory, query, found, entity id, `partial_view`, every record id
cited, and the withheld count.

## Run it

```bash
uv sync
uv run canon serve --as-of 2026-10-01                 # stdio; builds out/canon.sqlite if missing
uv run canon serve --caller salma.el.idrissi          # pin identity
uv run python examples/mcp_client.py "Zitoun"         # example client: same questions, 4 callers
```

HTTP, for a shared server:

```bash
uv run canon token add --caller hind.legal --tokens tokens.json     # prints the token once
uv run canon serve --http --tokens tokens.json --port 8765 --audit-log out/audit.jsonl
# clients connect to http://127.0.0.1:8765/mcp with "Authorization: Bearer <token>"
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

* **Self-asserted identity on stdio:** without `--caller` (stdio) or `--http --tokens`, `caller`
  is self-asserted. Static tokens are not SSO: no expiry or rotation policy, and no OAuth/OIDC
  (the SDK supports a full OAuth provider; not wired).
* **ACLs from exports, not live systems:** private-channel membership is read from the export.
  Someone removed from a channel keeps access until the next export is ingested.
* **Injection detection is pattern-based.** It reduces risk; it does not remove it.
* **Group-level ACLs only:** per-field or row-level policies (e.g. "sales may see owner but not
  contract value from CRM") would need field-scoped ACLs on `Fact`.
* **Clusters ignore ACLs:** entity resolution runs over all records. A caller can't see hidden
  records, but whether two visible records were linked can depend on a hidden one, which leaks a
  tiny amount of information.
* **Per-request recomputation:** facts are rescored on every request. That's fine at this scale;
  production should cache per (entity, group-set).
