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
    records, res = build_store(data, out, as_of)
    print(f"{len(records)} records -> {len(res.golden)} golden records in {out}")
    truth_path = data / "ground_truth" / "ground_truth.json"
    if args.report and truth_path.exists():
        from canon.resolve.report import render_report, seed_sweep

        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        cfg = ResolverConfig(facts=FactScoringConfig(as_of=as_of))
        sweep = seed_sweep(range(1, args.seeds + 1), cfg) if args.seeds else None
        report = render_report(records, res, truth, sweep)
        (out / "er_report.md").write_text(report, encoding="utf-8")
        print(report)


def build_store(data: Path, out: Path, as_of: date | None):
    """Ingest + resolve + score, persist to out/canon.sqlite; returns (records, resolution)."""
    import json

    from canon.ingest import load_all
    from canon.resolve.pipeline import ResolverConfig, resolve
    from canon.score import FactScoringConfig
    from canon.store import write_store

    records = load_all(data)
    res = resolve(records, ResolverConfig(facts=FactScoringConfig(as_of=as_of)))
    out.mkdir(parents=True, exist_ok=True)
    (out / "golden_records.json").write_text(
        json.dumps([g.model_dump(mode="json") for g in res.golden], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_store(out / "canon.sqlite", records, res.golden)
    return records, res


def cmd_serve(args: argparse.Namespace) -> None:
    from canon.mcp_server import CallerDirectory, CanonService, ServiceConfig, build_server
    from canon.score import FactScoringConfig

    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    store = Path(args.store)
    if args.rebuild or not store.exists():
        build_store(Path(args.data), store.parent, as_of)  # never print: stdout is the MCP channel
    service = CanonService.from_store(
        store,
        CallerDirectory.from_file(Path(args.identities)),
        ServiceConfig(facts=FactScoringConfig(as_of=as_of)),
    )
    build_server(service, pinned_caller=args.caller).run()


def cmd_eval(args: argparse.Namespace) -> None:
    from canon.evals import ClaudeModel, StubModel, render_report, run_eval
    from canon.evals.models import OpenAICompatibleModel

    if args.model == "stub":
        model = StubModel()
    elif args.model == "claude":
        model = ClaudeModel(args.model_id or "claude-opus-5-5")
    else:  # an OpenAI-compatible provider preset, e.g. baseten
        if not args.model_id:
            raise SystemExit(f"--model-id is required with --model {args.model}")
        model = OpenAICompatibleModel.preset(args.model, args.model_id)
        if not os.environ.get(model.api_key_env):
            raise SystemExit(
                f"Set {model.api_key_env} in the environment (never in a file in the repo)"
            )
    run = run_eval(Path(args.data), model, caller=args.caller, as_of=date.fromisoformat(args.as_of))
    sweep = None
    if args.seeds:
        from canon.evals.harness import seed_sweep

        sweep = seed_sweep(range(1, args.seeds + 1), model, args.caller)
    report = render_report(run, sweep)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    out.with_suffix(".json").write_text(run.model_dump_json(indent=2), encoding="utf-8")
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
    r.add_argument("--as-of", default=None, help="reference date for freshness (default: today)")
    r.set_defaults(func=cmd_resolve)

    s = sub.add_parser("serve", help="run the permission-aware MCP server over stdio")
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
    s.set_defaults(func=cmd_serve)

    e = sub.add_parser("eval", help="before/after eval: raw-file RAG agent vs. Canon MCP agent")
    e.add_argument("--data", default=str(_data_dir()))
    e.add_argument("--model", choices=["stub", "claude", "baseten"], default="stub")
    e.add_argument(
        "--model-id",
        default=None,
        help="model id (claude: default claude-opus-5-5; baseten: required provider slug)",
    )
    e.add_argument("--caller", default="revops.admin", help="identity the Canon agent acts for")
    e.add_argument("--as-of", default="2026-10-01")
    e.add_argument("--seeds", type=int, default=0, help="also rerun on N held-out seeds")
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
