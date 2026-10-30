# Security review

*Part of the product document set (`docs/product/`). Code claims cite repository paths. Written by the agent that built most of the code: a self-assessment, not independent review. Updated 2026-10-30.*

Scope: the code at `main` + this branch on 2026-10-30. Method: code reading, the existing security tests, a
dependency scan and a history secret scan run on that date. No external penetration test has been done.

## Checks run

| Check | Result | How |
|---|---|---|
| Known-vulnerable dependencies | **Found and fixed**: pillow 12.3.0 (11 advisories), pypdf 6.21.0 (4). Now pillow 13.0.0, pypdf 6.21.4: none found | `pip-audit 2.9.0` on the locked runtime deps; now a CI job |
| Secrets in git history | 0 matches for common key formats | `git log -p --all` pattern scan |
| Auth bypass on HTTP | Requests without or with a bad token get 401; identity comes from the token, not the `caller` argument | `tests/test_security.py` |
| Revocation | Revoked token stops working immediately | `tests/test_security.py` |
| Authorization (data leaks) | No tool response cites a record the caller cannot read, for every caller × tool | `tests/test_mcp.py`; 4,400-answer benchmark |
| Prompt injection in source text | Instruction-like text is withheld and counted | `canon/guard.py`, tests |
| HTML injection in deliverables | Source text escaped in review page and dashboard; JSON embedded safely | `tests/test_deliver.py`, `tests/test_pilot.py` |
| Token storage | Only SHA-256 hashes stored | `canon/mcp_server/auth.py`, test |
| SSRF / credential leak in CRM pull | Pagination only to the starting host; errors omit bodies and tokens | `canon/ingest/pull.py`, `tests/test_pull.py` |
| SOQL injection | Field names validated | `tests/test_pull.py` |
| Destructive operations | `purge` dry-runs by default and refuses non-Canon folders and the home directory | `tests/test_purge.py` |

## Design controls

- Ingest runs with `--network none`; the container runs as a non-root user; the export is mounted read-only.
- The HTTP server binds to 127.0.0.1 by default; TLS is expected from the client's reverse proxy.
- `/health` returns no customer data and needs no token.

## Accepted risks (documented, not fixed)

| Risk | Why accepted for pilots | Mitigation |
|---|---|---|
| Permissions are as configured (`identities.json`, ACL settings), not read live from every system | Live ACL sync needs per-system APIs | Show the permission map in the audit; client confirms roles before `serve` |
| No rate limiting in the app | Served on localhost behind the client's proxy | Rate-limit at the proxy; document in `DEPLOYMENT.md` |
| No encryption at rest of `out/` | Short engagements on client machines | Client disk encryption; `canon purge` at the end |
| The audit log stores queries (customer names) and record ids | Needed for accountability | Log stays in `out/`; deleted by `purge` |
| OIDC verified only against locally made keys | No identity provider available | Test with the client's IdP before relying on SSO |
| `eval` with a hosted model sends questions and retrieved text off-network | It is opt-in | Written consent or a client-hosted model (`docs/DEPLOY.md`) |
| No image signing or SBOM | Client builds from source | Add if procurement asks |

## No compliance claims

Nothing here certifies compliance with GDPR, CCPA/CPRA, SOC 2, ISO 27001 or any standard. There is no SOC 2 report. See `MARKET_RESEARCH.md` for the regulatory notes.
