"""Command-line entry point: `canon <command>`."""

from __future__ import annotations

import argparse
import os
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

    from canon.ingest import load_all
    from canon.resolve.pipeline import resolve
    from canon.store import write_store

    data, out = Path(args.data), Path(args.out)
    records = load_all(data)
    res = resolve(records)
    out.mkdir(parents=True, exist_ok=True)
    (out / "golden_records.json").write_text(
        json.dumps([g.model_dump(mode="json") for g in res.golden], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_store(out / "canon.sqlite", records, res.golden)
    print(f"{len(records)} records -> {len(res.golden)} golden records in {out}")
    truth_path = data / "ground_truth" / "ground_truth.json"
    if args.report and truth_path.exists():
        from canon.resolve.report import render_report, seed_sweep

        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        sweep = seed_sweep(range(1, args.seeds + 1)) if args.seeds else None
        report = render_report(records, res, truth, sweep)
        (out / "er_report.md").write_text(report, encoding="utf-8")
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
    r.set_defaults(func=cmd_resolve)

    args = parser.parse_args(argv)
    if getattr(args, "seed", 0) is None:
        from canon.synth import DEFAULT_SEED

        args.seed = DEFAULT_SEED
    args.func(args)


if __name__ == "__main__":
    main()
