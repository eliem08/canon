"""Cross-model eval summary from the per-model JSON reports in docs/reports.

uv run python scripts/eval_summary.py > docs/reports/eval_summary.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from canon.evals.stats import mcnemar_exact

REPORTS = Path(__file__).resolve().parents[1] / "docs" / "reports"
MODELS = [
    "moonshotai_Kimi-K3",
    "deepseek-ai_DeepSeek-V4-Pro-0813",
    "nvidia_NVIDIA-Nemotron-3-Ultra-550B-A55B",
    "zai-org_GLM-5.3",
]
VIEWS = [
    ("eval_{m}.json", "40 synthetic questions, full-access caller (`revops.admin`)"),
    ("eval_paraphrase_{m}.json", "30 hand-written questions, full-access caller"),
    ("eval_sales_{m}.json", "40 synthetic questions, sales rep (`salma.el.idrissi`)"),
]
AGENTS = ["baseline", "hybrid", "oracle", "canon"]


def _acc(run: dict, agent: str) -> tuple[float, int]:
    rows = run["results"]
    ok = sum(r["outcomes"][agent]["correct"] for r in rows)
    leak = sum(r["outcomes"][agent].get("restricted", 0) > 0 for r in rows)
    return ok / len(rows), leak


def _p(run: dict, other: str) -> float:
    rows = run["results"]
    a = sum(r["outcomes"]["canon"]["correct"] and not r["outcomes"][other]["correct"] for r in rows)
    b = sum(r["outcomes"][other]["correct"] and not r["outcomes"]["canon"]["correct"] for r in rows)
    return mcnemar_exact(a, b)


def main() -> None:
    out = ["# Eval summary: four models, three views", ""]
    for pattern, title in VIEWS:
        out += [
            f"## {title}",
            "",
            "| Model | Baseline (BM25) | Strong RAG | Oracle | **Canon** | Canon vs RAG (p) "
            "| Reads restricted text: RAG / Canon |",
            "|---|---|---|---|---|---|---|",
        ]
        for m in MODELS:
            path = REPORTS / pattern.format(m=m)
            if not path.exists():
                out.append(f"| `{m}` | (missing) | | | | | |")
                continue
            run = json.loads(path.read_text(encoding="utf-8"))
            if "hybrid" not in run.get("agents", []):
                out.append(f"| `{m}` | (older report without the strong baseline) | | | | | |")
                continue
            acc = {a: _acc(run, a) for a in AGENTS}
            n = len(run["results"])
            gap = (acc["canon"][0] - acc["hybrid"][0]) * 100
            out.append(
                f"| `{m.split('_', 1)[1]}` | {acc['baseline'][0]:.1%} | {acc['hybrid'][0]:.1%} | "
                f"{acc['oracle'][0]:.1%} | **{acc['canon'][0]:.1%}** | {gap:+.1f} pts "
                f"({_p(run, 'hybrid'):.2g}) | {acc['hybrid'][1]}/{n} / {acc['canon'][1]}/{n} |"
            )
        out.append("")
    sys.stdout.write("\n".join(out))


if __name__ == "__main__":
    main()
