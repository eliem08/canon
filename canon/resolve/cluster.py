"""Average-linkage agglomerative clustering with cannot-link constraints.

Start from singletons and repeatedly merge the two clusters with the highest
average match probability over their *scored* cross pairs (pairs that blocking
never compared carry no evidence either way). Merging stops when the best
average falls below `threshold`. Clusters containing a hard conflict
(cannot-link pair) are never merged, which prevents transitive chaining
through a single weak link.
"""

from __future__ import annotations

import heapq


def cluster(
    record_ids: list[str],
    probabilities: dict[tuple[str, str], float],
    cannot_link: set[tuple[str, str]],
    threshold: float = 0.5,
) -> list[list[str]]:
    def key(a: str, b: str) -> tuple[str, str]:
        return (a, b) if a < b else (b, a)

    members: dict[int, list[str]] = {i: [r] for i, r in enumerate(sorted(record_ids))}
    owner = {r: i for i, ms in members.items() for r in ms}
    # cluster-pair -> [sum of probabilities, number of scored pairs, has conflict]
    links: dict[tuple[int, int], list] = {}
    for (a, b), p in probabilities.items():
        ca, cb = sorted((owner[a], owner[b]))
        links[(ca, cb)] = [p, 1, False]
    for a, b in cannot_link:
        ca, cb = sorted((owner[a], owner[b]))
        links.setdefault((ca, cb), [0.0, 0, False])[2] = True

    def avg(stats: list) -> float:
        return stats[0] / stats[1] if stats[1] and not stats[2] else 0.0

    heap = [(-avg(st), pair) for pair, st in links.items() if avg(st) >= threshold]
    heapq.heapify(heap)
    next_id = len(members)
    while heap:
        neg, (ca, cb) = heapq.heappop(heap)
        if ca not in members or cb not in members:
            continue
        stats = links.get((ca, cb))
        if stats is None or abs(avg(stats) + neg) > 1e-12 or avg(stats) < threshold:
            continue
        merged = members.pop(ca) + members.pop(cb)
        new = next_id
        next_id += 1
        members[new] = merged
        # combine link statistics of ca and cb towards every other cluster
        combined: dict[int, list] = {}
        for (x, y), st in list(links.items()):
            if x in (ca, cb) or y in (ca, cb):
                del links[(x, y)]
                other = y if x in (ca, cb) else x
                if other in (ca, cb):
                    continue
                agg = combined.setdefault(other, [0.0, 0, False])
                agg[0] += st[0]
                agg[1] += st[1]
                agg[2] = agg[2] or st[2]
        for other, st in combined.items():
            pair = (other, new)  # new id is always the largest
            links[pair] = st
            if avg(st) >= threshold:
                heapq.heappush(heap, (-avg(st), pair))
    return sorted((sorted(ms) for ms in members.values()), key=lambda ms: ms[0])
