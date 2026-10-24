"""Command-line entry point: `canon <command>`."""

from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path


def _data_dir() -> Path:
    return Path(os.environ.get("CANON_DATA_DIR", "data/synthetic"))


def cmd_generate(args: argparse.Namespace) -> None:
    from canon.synth import generate

    truth = generate(Path(args.out), seed=args.seed)
    print(
        f"wrote {len(truth['records'])} records for {len(truth['entities'])} entities to {args.out}"
    )


def cmd_resolve(args: argparse.Namespace) -> None:
    import json

    from canon.resolve.pipeline import ResolverConfig
    from canon.score import FactScoringConfig

    data, out = Path(args.data), Path(args.out)
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    overrides = Path(args.overrides) if args.overrides else None
    records, res, unreadable = build_store(data, out, as_of, overrides)
    print(f"{len(records)} records -> {len(res.golden)} golden records in {out}")
    print(
        f"review queue: {len(res.review)} pair decisions to confirm ({out / 'review_queue.json'})"
    )
    issues = [i for r in records for i in r.issues]
    held = sum(i.severity == "quarantined" for i in issues)
    print(
        f"parse issues: {held} values quarantined, {len(issues) - held} read under an "
        f"assumption, {len(unreadable)} documents unreadable (details: {out / 'quarantine.json'})"
    )
    truth_path = data / "ground_truth" / "ground_truth.json"
    if args.report and truth_path.exists():
        from canon.resolve.report import render_report, seed_sweep

        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        cfg = ResolverConfig(facts=FactScoringConfig(as_of=as_of))
        sweep = seed_sweep(range(1, args.seeds + 1), cfg) if args.seeds else None
        report = render_report(records, res, truth, sweep)
        (out / "er_report.md").write_text(report, encoding="utf-8")
        print(report)


def build_store(data: Path, out: Path, as_of: date | None, overrides: Path | None = None):
    """Ingest + resolve + score, persist to out/; returns (records, resolution, unreadable docs).

    Entity ids are carried over from an existing out/canon.sqlite; human decisions in
    `overrides` (must_link / cannot_link) are applied; borderline decisions are written to
    out/review_queue.json and unreadable values to out/quarantine.json."""
    import json

    from canon.ingest import load_all
    from canon.resolve.pipeline import Overrides, ResolverConfig, resolve, write_review_queue
    from canon.score import FactScoringConfig
    from canon.store import read_lineage, write_store

    unreadable: list = []
    records = load_all(data, unreadable=unreadable)
    previous = read_lineage(out / "canon.sqlite")
    res = resolve(
        records,
        ResolverConfig(facts=FactScoringConfig(as_of=as_of)),
        overrides=Overrides.load(overrides),
        previous=previous,
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "golden_records.json").write_text(
        json.dumps([g.model_dump(mode="json") for g in res.golden], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_store(out / "canon.sqlite", records, res.golden)
    issues = [i.model_dump() for r in records for i in r.issues]
    issues += [i.model_dump() for i in unreadable]
    (out / "quarantine.json").write_text(
        json.dumps(issues, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_review_queue(out / "review_queue.json", res.review)
    return records, res, unreadable


def cmd_serve(args: argparse.Namespace) -> None:
    from canon.mcp_server import CallerDirectory, CanonService, ServiceConfig, build_server
    from canon.mcp_server.audit import AuditLog
    from canon.score import FactScoringConfig

    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    store = Path(args.store)
    if args.rebuild or not store.exists():
        build_store(Path(args.data), store.parent, as_of)  # never print: stdout is the MCP channel
    service = CanonService.from_store(
        store,
        CallerDirectory.from_file(Path(args.identities)),
        ServiceConfig(facts=FactScoringConfig(as_of=as_of)),
        audit=AuditLog(Path(args.audit_log)) if args.audit_log else None,
    )
    if not args.http:
        build_server(service, pinned_caller=args.caller).run()
        return
    if not args.tokens and not args.oidc_issuer:
        raise SystemExit(
            "--http requires --tokens (see `canon token add`) and/or --oidc-issuer (SSO)"
        )
    oidc = None
    if args.oidc_issuer:
        import json as _json

        from canon.mcp_server.auth import OIDCConfig, OIDCVerifier, sso_map

        if not args.oidc_audience:
            raise SystemExit(
                "--oidc-issuer needs --oidc-audience (the app id Canon is registered as)"
            )
        identities = _json.loads(Path(args.identities).read_text(encoding="utf-8"))
        config = OIDCConfig(
            issuer=args.oidc_issuer,
            audience=args.oidc_audience,
            jwks_url=args.oidc_jwks_url,
            claim=args.oidc_claim,
        )
        oidc = OIDCVerifier(config, sso_map(identities))
    url = args.public_url or f"http://{args.host}:{args.port}"
    tokens = Path(args.tokens) if args.tokens else None
    server = build_server(service, tokens=tokens, public_url=url, oidc=oidc)
    server.run("streamable-http", host=args.host, port=args.port)


def cmd_audit(args: argparse.Namespace) -> None:
    from canon.audit import build_audit, render_audit
    from canon.mcp_server import CallerDirectory

    data, out = Path(args.data), Path(args.out)
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    overrides = Path(args.overrides) if args.overrides else None
    records, res, unreadable = build_store(data, out, as_of, overrides)
    identities = Path(args.identities) if args.identities else data / "identities.json"
    directory = CallerDirectory.from_file(identities) if identities.exists() else None
    audit = build_audit(records, res, directory, unreadable, as_of)
    report = render_audit(audit)
    if args.compare:  # week 2: what the client fixed since the previous audit
        from canon.audit import Audit, compare_audits, render_delta

        previous = Audit.model_validate_json(Path(args.compare).read_text(encoding="utf-8"))
        delta = render_delta(compare_audits(previous, audit))
        report = report.replace("\n## 1. ", f"\n{delta}\n## 1. ", 1)
    (out / "audit_report.md").write_text(report, encoding="utf-8")
    (out / "audit.json").write_text(audit.model_dump_json(indent=2), encoding="utf-8")
    write_deliverables(out, report, res.review, records, overrides)
    from dataclasses import asdict

    from canon.deliver import write_fix_files, write_renewals_csv
    from canon.ingest import load_deployment

    crm_columns = asdict(load_deployment(data).crm_fields)
    write_fix_files(out, audit, records, unreadable, crm_columns)
    write_renewals_csv(out, audit)
    print(report)
    print(
        f"Client files in {out}: audit_report.html (print to PDF), review.html (merges "
        "to confirm), crm_fixes.csv (CRM bulk update), quarantine.csv (values to check)"
    )


def write_deliverables(out: Path, report: str, review, records, overrides: Path | None) -> None:
    """The HTML report and the offline review page the client fills in (see canon/deliver.py)."""
    import hashlib

    from canon.deliver import render_audit_html, render_review_html
    from canon.resolve.pipeline import Overrides

    by_id = {r.record_id: r for r in records}
    run = hashlib.sha1("".join(f"{i.left}{i.right}" for i in review).encode()).hexdigest()[:12]
    (out / "audit_report.html").write_text(render_audit_html(report), encoding="utf-8")
    (out / "review.html").write_text(
        render_review_html(review, by_id, Overrides.load(overrides), run), encoding="utf-8"
    )


def cmd_check(args: argparse.Namespace) -> None:
    import json

    from canon.intake import check_export, render_check, suggested_deployment

    report = check_export(Path(args.data))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    text = render_check(report)
    (out / "intake_check.md").write_text(text, encoding="utf-8")
    suggestion = suggested_deployment(report)
    if suggestion:
        path = out / "canon.suggested.json"
        path.write_text(json.dumps(suggestion, ensure_ascii=False, indent=2), encoding="utf-8")
        text += f"\nSuggested deployment file: {path} (review, then copy to <data>/canon.json)\n"
    print(text)
    if not report["ok"]:
        raise SystemExit(1)


def cmd_pull(args: argparse.Namespace) -> None:
    from canon.ingest.pull import PullError, pull_hubspot, pull_salesforce, write_export

    extra = dict(p.split("=", 1) for p in args.property)
    try:
        if args.crm == "hubspot":
            token = os.environ.get("HUBSPOT_TOKEN")
            if not token:
                raise SystemExit("Set HUBSPOT_TOKEN (a private-app token with read scopes)")
            rows = pull_hubspot(token, extra)
        else:
            token = os.environ.get("SALESFORCE_TOKEN")
            instance = os.environ.get("SALESFORCE_INSTANCE_URL")
            if not token or not instance:
                raise SystemExit("Set SALESFORCE_TOKEN and SALESFORCE_INSTANCE_URL")
            rows = pull_salesforce(token, instance, extra)
    except PullError as exc:
        raise SystemExit(f"{args.crm} refused the request: {exc}") from None
    path = write_export(rows, Path(args.out))
    print(f"{len(rows)} accounts from {args.crm} -> {path} (read-only; run `canon check` next)")


def cmd_token(args: argparse.Namespace) -> None:
    from canon.mcp_server.auth import issue_token, revoke_caller

    if args.action == "add":
        token = issue_token(Path(args.tokens), args.caller)
        print(f"token for {args.caller} (shown once; only its hash is stored in {args.tokens}):")
        print(token)
    else:
        print(f"revoked {revoke_caller(Path(args.tokens), args.caller)} token(s) of {args.caller}")


def cmd_eval(args: argparse.Namespace) -> None:
    from canon.evals import ClaudeModel, StubModel, render_report, run_eval
    from canon.evals.models import OpenAICompatibleModel

    if args.model == "stub":
        model = StubModel()
    elif args.model == "claude":
        model = ClaudeModel(args.model_id or "claude-opus-5-5")
    elif args.model == "openai-compatible":  # e.g. a model the client hosts: no data leaves
        if not args.model_id or not args.base_url:
            raise SystemExit("--model openai-compatible needs --model-id and --base-url")
        model = OpenAICompatibleModel(
            args.model_id,
            args.base_url,
            args.api_key_env,
            require_key=bool(os.environ.get(args.api_key_env)),
        )
    else:  # an OpenAI-compatible provider preset, e.g. baseten
        if not args.model_id:
            raise SystemExit(f"--model-id is required with --model {args.model}")
        model = OpenAICompatibleModel.preset(
            args.model, args.model_id, proxy_credentials=args.proxy_credentials
        )
        if not args.proxy_credentials and not os.environ.get(model.api_key_env):
            raise SystemExit(
                f"Set {model.api_key_env} in the environment (never in a file in the repo)"
            )
    as_of = date.fromisoformat(args.as_of)
    questions = Path(args.questions) if args.questions else None
    runs = [
        run_eval(Path(args.data), model, caller=args.caller, as_of=as_of, questions=questions)
        for _ in range(max(args.runs, 1))
    ]
    run = runs[0]
    sweep = None
    if args.seeds:
        from canon.evals.harness import seed_sweep

        sweep = seed_sweep(range(1, args.seeds + 1), model, args.caller)
    report = render_report(run, sweep, runs[1:])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    out.with_suffix(".json").write_text(run.model_dump_json(indent=2), encoding="utf-8")
    from canon.deliver import render_audit_html

    out.with_suffix(".html").write_text(
        render_audit_html(report, "Before/after evaluation"), encoding="utf-8"
    )
    print(report)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="canon")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="generate the seeded synthetic dataset")
    g.add_argument("--out", default=str(_data_dir()))
    g.add_argument("--seed", type=int, default=None)
    g.set_defaults(func=cmd_generate)

    r = sub.add_parser("resolve", help="ingest sources, resolve entities, build golden records")
    r.add_argument("--data", default=str(_data_dir()))
    r.add_argument("--out", default=os.environ.get("CANON_OUT_DIR", "out"))
    r.add_argument("--report", action="store_true", help="evaluate against ground truth")
    r.add_argument("--seeds", type=int, default=0, help="also sweep N held-out seeds")
    r.add_argument(
        "--overrides", default=None, help="JSON with must_link / cannot_link record-id pairs"
    )
    r.add_argument("--as-of", default=None, help="reference date for freshness (default: today)")
    r.set_defaults(func=cmd_resolve)

    s = sub.add_parser("serve", help="run the permission-aware MCP server (stdio or HTTP)")
    s.add_argument("--data", default=str(_data_dir()))
    s.add_argument(
        "--store", default=str(Path(os.environ.get("CANON_OUT_DIR", "out")) / "canon.sqlite")
    )
    s.add_argument("--identities", default=str(_data_dir() / "identities.json"))
    s.add_argument("--as-of", default=None, help="reference date for freshness (default: today)")
    s.add_argument("--rebuild", action="store_true", help="rebuild the store from --data first")
    s.add_argument(
        "--caller",
        default=None,
        help="pin every request to this identity (ignore the tool argument)",
    )
    s.add_argument("--audit-log", default=None, help="append one JSON line per tool call here")
    s.add_argument("--http", action="store_true", help="streamable HTTP with bearer tokens")
    s.add_argument("--tokens", default=None, help="token file (see `canon token add`)")
    s.add_argument("--oidc-issuer", default=None, help="SSO: the identity provider's issuer URL")
    s.add_argument("--oidc-audience", default=None, help="SSO: audience Canon's tokens are for")
    s.add_argument("--oidc-jwks-url", default=None, help="SSO: JWKS URL (default: discovered)")
    s.add_argument("--oidc-claim", default="email", help="SSO: claim that names the caller")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--public-url", default=None, help="URL clients use (default http://host:port)")
    s.set_defaults(func=cmd_serve)

    a = sub.add_parser("audit", help="readiness audit report: duplicates, stale facts, quarantine")
    a.add_argument("--data", default=str(_data_dir()))
    a.add_argument("--out", default=os.environ.get("CANON_OUT_DIR", "out"))
    a.add_argument("--identities", default=None, help="default: <data>/identities.json")
    a.add_argument("--overrides", default=None)
    a.add_argument("--as-of", default=None)
    a.add_argument("--compare", default=None, help="a previous audit.json: report what changed")
    a.set_defaults(func=cmd_audit)

    c = sub.add_parser("check", help="day-1 intake check of a client export (no resolution)")
    c.add_argument("--data", default=str(_data_dir()))
    c.add_argument("--out", default=os.environ.get("CANON_OUT_DIR", "out"))
    c.set_defaults(func=cmd_check)

    pl = sub.add_parser("pull", help="read-only pull of CRM accounts via the CRM's API")
    pl.add_argument("crm", choices=["hubspot", "salesforce"])
    pl.add_argument("--out", default=str(_data_dir() / "crm" / "accounts.json"))
    pl.add_argument(
        "--property",
        action="append",
        default=[],
        help="field=CRM property, e.g. contract_value=annual_contract_value (repeatable)",
    )
    pl.set_defaults(func=cmd_pull)

    t = sub.add_parser("token", help="issue or revoke HTTP bearer tokens for callers")
    t.add_argument("action", choices=["add", "revoke"])
    t.add_argument("--caller", required=True, help="caller id from the identities file")
    t.add_argument("--tokens", default="tokens.json")
    t.set_defaults(func=cmd_token)

    e = sub.add_parser("eval", help="before/after eval: raw-file RAG agent vs. Canon MCP agent")
    e.add_argument("--data", default=str(_data_dir()))
    e.add_argument(
        "--model", choices=["stub", "claude", "baseten", "openai-compatible"], default="stub"
    )
    e.add_argument(
        "--base-url", default=None, help="openai-compatible: e.g. http://llm.internal:8000/v1"
    )
    e.add_argument(
        "--api-key-env", default="OPENAI_API_KEY", help="openai-compatible: env var with the key"
    )
    e.add_argument(
        "--model-id",
        default=None,
        help="model id (claude: default claude-opus-5-5; baseten: required provider slug)",
    )
    e.add_argument(
        "--proxy-credentials",
        action="store_true",
        help="the network proxy injects the provider Authorization header (cloud secrets)",
    )
    e.add_argument("--caller", default="revops.admin", help="identity the Canon agent acts for")
    e.add_argument("--as-of", default="2026-10-01")
    e.add_argument("--seeds", type=int, default=0, help="also rerun on N held-out seeds")
    e.add_argument(
        "--questions",
        default=None,
        help="question file (JSON, CSV or XLSX, e.g. a client's); "
        "default <data>/ground_truth/eval_questions.json",
    )
    e.add_argument("--runs", type=int, default=1, help="repeat the eval N times (real models)")
    e.add_argument(
        "--out", default=str(Path(os.environ.get("CANON_OUT_DIR", "out")) / "eval_report.md")
    )
    e.set_defaults(func=cmd_eval)

    args = parser.parse_args(argv)
    if getattr(args, "seed", 0) is None:
        from canon.synth import DEFAULT_SEED

        args.seed = DEFAULT_SEED
    args.func(args)


if __name__ == "__main__":
    main()
