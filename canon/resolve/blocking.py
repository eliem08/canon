"""Blocking: only compare records that share at least one cheap key.

Keys: 3-char prefixes of name-token skeletons, the whole-name skeleton
prefix, acronyms (and single short tokens that may be acronyms), business
domain, phone number and tax id. Over-populated keys (common words) are
dropped so blocking stays sub-quadratic on real volumes.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations

from canon.resolve.features import RecordFeatures


def blocking_keys(f: RecordFeatures) -> set[str]:
    keys: set[str] = set()
    for sk in f.skeletons:
        for token in sk.split():
            if len(token) >= 2:
                keys.add(f"sk:{token[:3]}")
        joined = sk.replace(" ", "")
        if len(joined) >= 4:
            keys.add(f"skj:{joined[:4]}")
    for ac in f.acronyms:
        keys.add(f"ac:{ac}")
    for name in f.names:
        tokens = name.split()
        if 2 <= len(tokens[0]) <= 6 and (len(tokens) == 1 or len(tokens[0]) <= 4):
            keys.add(f"ac:{tokens[0]}")  # a short first token may itself be an acronym
    for name in f.names:  # "association sportive karting soissons": initials before the last word
        tokens = name.split()
        if len(tokens) >= 3:
            keys.add(f"ac:{''.join(t[0] for t in tokens[:-1])}")
    if f.address[:1].isdigit() and f.city:  # a street number makes an address specific
        keys.add(f"adr:{f.address}|{f.city}")
    if f.domain:
        keys.add(f"dom:{f.domain}")
    if f.phone:
        keys.add(f"tel:{f.phone}")
    if f.tax_id:
        keys.add(f"tax:{f.tax_id}")
    return keys


def candidate_pairs(feats: list[RecordFeatures], max_block_size: int = 40) -> set[tuple[str, str]]:
    index: dict[str, list[str]] = defaultdict(list)
    for f in feats:
        for key in blocking_keys(f):
            index[key].append(f.record_id)
    pairs: set[tuple[str, str]] = set()
    for members in index.values():
        if len(members) > max_block_size:
            continue
        for a, b in combinations(sorted(set(members)), 2):
            pairs.add((a, b))
    return pairs
