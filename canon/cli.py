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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="canon")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="generate the seeded synthetic dataset")
    g.add_argument("--out", default=str(_data_dir()))
    g.add_argument("--seed", type=int, default=None)
    g.set_defaults(func=cmd_generate)

    args = parser.parse_args(argv)
    if getattr(args, "seed", 0) is None:
        from canon.synth import DEFAULT_SEED

        args.seed = DEFAULT_SEED
    args.func(args)


if __name__ == "__main__":
    main()
