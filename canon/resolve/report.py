"""Markdown report for an entity-resolution run evaluated against ground truth."""

from __future__ import annotations

import tempfile
from collections import Counter
from pathlib import Path

from canon.models import SourceRecord
from canon.resolve.evaluate import bcubed, blocking_quality, field_accuracy, pairwise
from canon.resolve.normalize import normalize_name
from canon.resolve.pipeline import Resolution, ResolverConfig, resolve
from canon.score.evaluate import fact_report


def exact_name_baseline(records: list[SourceRecord]) -> list[list[str]]:
    """Naive baseline: merge records whose normalized names are identical."""
    parent = {r.record_id: r.record_id for r in records}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    seen: dict[str, str] = {}
    for r in records:
        for n in r.all_names():
            key = normalize_name(n)
            if key in seen:
                parent[find(r.record_id)] = find(seen[key])
            elif key:
                seen[key] = r.record_id
    groups: dict[str, list[str]] = {}
    for rid in parent:
        groups.setdefault(find(rid), []).append(rid)
    return list(groups.values())


def seed_sweep(
    seeds: range, config: ResolverConfig | None = None
) -> list[tuple[int, float, float]]:
    """Regenerate the dataset with other seeds (held-out check).

    Returns (seed, pairwise F1, overall fact accuracy) per seed."""
    from canon.ingest import load_all
    from canon.synth import generate

    out = []
    for seed in seeds:
        with tempfile.TemporaryDirectory() as d:
            truth = generate(Path(d), seed=seed)
            res = resolve(load_all(Path(d)), config)
            records = load_all(Path(d))
            facts = fact_report(res.golden, records, truth["records"], truth["entities"])
            out.append(
                (seed, pairwise(res.clusters, truth["records"]).f1, facts["overall"]["canon"])
            )
    return out


def _fact_section(rep: dict) -> list[str]:
    lines = [
        "",
        "## Fact scoring (freshness x authority)",
        "",
        "Accuracy of the winning value per field against ground-truth *current* values, "
        "compared with two naive resolvers over the same clusters. `truth kept` = the true "
        "value is the winner or one of the retained alternatives.",
        "",
        "| Field | Canon | Latest wins | Authority wins | Truth kept | Conflicts |",
        "|---|---|---|---|---|---|",
    ]
    for name, row in rep["per_field"].items():
        lines.append(
            f"| {name} | **{row['canon']:.3f}** | {row['latest']:.3f} | "
            f"{row['authority']:.3f} | {row['truth_retained']:.3f} | "
            f"{row['conflicts']}/{row['n']} |"
        )
    o = rep["overall"]
    lines += [
        f"| **overall** | **{o['canon']:.3f}** | {o['latest']:.3f} | {o['authority']:.3f} | | |",
        "",
        f"Mean confidence: {rep['mean_confidence_correct']} when correct, "
        f"{rep['mean_confidence_wrong']} when wrong.",
        "",
        "| Confidence | Facts | Accuracy |",
        "|---|---|---|",
        *[
            f"| {c['bucket']} | {c['n']} | "
            f"{'' if c['accuracy'] is None else format(c['accuracy'], '.3f')} |"
            for c in rep["calibration"]
        ],
        "",
        "### Fact failures",
        "",
    ]
    lines += [
        f"- {f['entity']} `{f['field']}`: expected `{f['expected']}`, got `{f['got']}` "
        f"({f['explanation']})"
        for f in rep["failures"]
    ] or ["None."]
    return lines


def _row(name: str, m) -> str:
    return f"| {name} | {m.precision:.3f} | {m.recall:.3f} | **{m.f1:.3f}** |"


def render_report(
    records: list[SourceRecord],
    res: Resolution,
    truth: dict,
    sweep: list[tuple[int, float, float]] | None = None,
) -> str:
    t = truth["records"]
    pw, b3 = pairwise(res.clusters, t), bcubed(res.clusters, t)
    base = exact_name_baseline(records)
    blk = blocking_quality(res.candidates, t)
    fields = field_accuracy(res.golden, t, truth["entities"])
    by_id = {r.record_id: r for r in records}
    lines = [
        "# Entity resolution and fact scoring report",
        "",
        f"Dataset: {len(records)} records, {len(set(t.values()))} true entities, "
        f"{len(res.clusters)} predicted clusters.",
        "",
        "## Clustering quality",
        "",
        "| Method | Precision | Recall | F1 |",
        "|---|---|---|---|",
        _row("Canon — pairwise", pw),
        _row("Canon — B-cubed", b3),
        _row("Baseline (exact normalized name) — pairwise", pairwise(base, t)),
        "",
        "## Blocking",
        "",
        f"- candidate pairs: {blk['candidate_pairs']} of {blk['all_pairs']} "
        f"(reduction ratio {blk['reduction_ratio']:.3f})",
        f"- pair completeness (true pairs kept): {blk['pair_completeness']:.3f}",
        "",
        "## Golden-record field accuracy (survivorship vs. ground truth current values)",
        "",
        "| Field | Accuracy |",
        "|---|---|",
        *[f"| {k} | {v:.3f} |" for k, v in fields.items()],
    ]
    if sweep:
        f1s = [f for _, f, _ in sweep]
        facc = [a for _, _, a in sweep]
        lines += [
            "",
            "## Robustness: held-out seeds",
            "",
            f"Regenerated the dataset with seeds {sweep[0][0]}–{sweep[-1][0]} "
            f"(same generator, different randomness) — pairwise F1 mean "
            f"**{sum(f1s) / len(f1s):.3f}**, min **{min(f1s):.3f}**, "
            f"{sum(f >= 0.9 for f in f1s)}/{len(f1s)} seeds ≥ 0.90. "
            f"Fact accuracy mean **{sum(facc) / len(facc):.3f}**, min **{min(facc):.3f}**.",
        ]
    errors = []
    for c in res.clusters:
        ents = Counter(t[r] for r in c)
        if len(ents) > 1:
            names = ", ".join(f"`{by_id[r].name}` ({t[r]})" for r in c)
            errors.append(f"- **false merge**: {names}")
    for eid in sorted(set(t.values())):
        parts = [c for c in res.clusters if any(t[r] == eid for r in c)]
        if len(parts) > 1:
            small = min(parts, key=len)
            names = ", ".join(f"`{by_id[r].name}` [{r}]" for r in small)
            errors.append(f"- **missed link** ({eid}, split into {len(parts)}): {names}")
    lines += ["", "## Errors", "", *(errors or ["None."])]
    lines += _fact_section(fact_report(res.golden, records, t, truth["entities"]))
    return "\n".join(lines) + "\n"
