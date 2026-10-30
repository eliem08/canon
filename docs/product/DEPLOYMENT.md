# Deployment

*Part of the product document set (`docs/product/`). Code claims cite repository paths. Written by the agent that built most of the code: a self-assessment, not independent review. Updated 2026-10-30.*

The detailed, verified runbook is `docs/DEPLOY.md` (build, export layout, offline run, serving, eval). This page
is the production summary.

## Topology (pilot)

One Linux machine at the client (VM or laptop) with Docker. Ingest and audit run with `--network none`. Optional:
`canon serve --http` on 127.0.0.1 behind the client's reverse proxy (TLS, rate limits). No cloud account, domain or
recurring infrastructure cost is needed; nothing is deployed by Canon's team.

## Steps

```bash
docker build -t canon .                                                    # from source; no published image
docker run --rm --network none -v "$PWD/export:/data:ro" -v "$PWD/out:/out" canon check
docker run --rm --network none -v "$PWD/export:/data:ro" -v "$PWD/out:/out" canon pilot
# optional agent trial
docker run --rm --network none -v "$PWD/out:/out" canon token add --caller <id> --tokens /out/tokens.json
docker run -d -p 127.0.0.1:8765:8765 -v "$PWD/export:/data:ro" -v "$PWD/out:/out" \
  canon serve --http --host 0.0.0.0 --tokens /out/tokens.json --audit-log /out/audit.jsonl
curl -fsS http://127.0.0.1:8765/health                                     # {"status": "ok", ...}
# end of engagement
docker run --rm -v "$PWD/out:/out" canon purge --out /out              # dry run, lists files
docker run --rm -v "$PWD/out:/out" -v "$PWD:/receipt" canon purge --out /out --yes --receipt /receipt/deletion.json
```

## Configuration

Environment variables: see `.env.example`. Per-client settings: `<export>/canon.json` (`docs/DEPLOY.md`).

## HTTPS and domains

Canon does not terminate TLS. Put it behind the client's reverse proxy (nginx, Traefik, an API gateway) with TLS and
rate limiting, or keep it on localhost for a single-machine trial.

## Rollback

Canon never writes to client systems. Rolling back is stopping the container and deleting `out/` (or rebuilding the
previous image tag and rerunning from the same export).

## Not done

No published or signed image, no SBOM, no managed hosting. If a client wants a hosted service, that is a new project
with its own security review.
