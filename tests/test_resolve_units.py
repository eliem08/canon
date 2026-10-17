from canon.models import SourceRecord
from canon.resolve.blocking import candidate_pairs
from canon.resolve.cluster import cluster
from canon.resolve.features import features
from canon.resolve.scoring import ScoringConfig, is_cannot_link, score_pair


def rec(rid, name, **kw):
    return SourceRecord(record_id=rid, source=kw.pop("source", "crm"), locator="t", name=name, **kw)


def prob(a, b):
    return score_pair(features(a), features(b), ScoringConfig()).probability


def test_blocking_pairs_share_a_key_only():
    recs = [
        rec("a", "Atlas Logistique SARL"),
        rec("b", "أطلس لوجيستيك"),
        rec("c", "Zitoun Cosmetics"),
        rec("d", "Totally Different", domain="zitoun.ma"),
        rec("e", "Other", domain="zitoun.ma"),
    ]
    pairs = candidate_pairs([features(r) for r in recs])
    assert ("a", "b") in pairs and ("d", "e") in pairs
    assert ("a", "c") not in pairs


def test_oversized_blocks_are_skipped():
    recs = [rec(f"r{i}", "Atlas") for i in range(5)]  # one shared key, 5 members
    assert candidate_pairs([features(r) for r in recs], max_block_size=3) == set()


def test_same_entity_variants_match():
    a = rec("a", "Atlas Logistique SARL", domain="atlaslogistique.ma", phone="+212522000001")
    b = rec("b", "Atlas Logistiqeu S.A.R.L.", phone="+212522000001")
    c = rec("c", "أطلس لوجيستيك ش.م.م", phone="+212522000001")
    d = rec("d", "atlaslog", source="slack", domain="atlaslogistique.ma")
    assert prob(a, b) > 0.95 and prob(a, c) > 0.9 and prob(a, d) > 0.9


def test_confusers_do_not_match():
    a = rec("a", "Atlas Logistique SARL", domain="atlaslogistique.ma", city="Casablanca")
    b = rec("b", "Atlas Tours SA", domain="atlastours.ma", city="Marrakech")
    assert prob(a, b) < 0.05


def test_short_skeleton_is_weak_evidence():
    # "brc" (acronym) and "baraka" share the skeleton "brk" but nothing else.
    assert prob(rec("a", "brc", source="slack"), rec("b", "Boulangerie Al Baraka")) < 0.5


def test_acronym_matches_with_corroboration():
    a = rec("a", "khg", source="slack", domain="kasbahgroup.com")
    b = rec("b", "Kasbah Hospitality Group SA", domain="kasbahgroup.com")
    assert prob(a, b) > 0.9


def test_cannot_link_on_conflicting_tax_ids():
    a = features(rec("a", "Acme", tax_id="001"))
    b = features(rec("b", "Acme", tax_id="002"))
    assert is_cannot_link(a, b)
    assert not is_cannot_link(a, features(rec("c", "Acme")))


def test_average_linkage_merges_and_respects_threshold():
    probs = {("a", "b"): 0.9, ("b", "c"): 0.8, ("a", "c"): 0.7, ("c", "d"): 0.3}
    assert cluster(["a", "b", "c", "d"], probs, set()) == [["a", "b", "c"], ["d"]]


def test_cannot_link_blocks_transitive_chaining():
    probs = {("a", "b"): 0.9, ("b", "c"): 0.9}
    assert cluster(["a", "b", "c"], probs, {("a", "c")}) == [["a", "b"], ["c"]]


def test_average_linkage_resists_one_weak_bridge():
    # c links strongly to b only; a-c are clearly different -> c stays out
    probs = {("a", "b"): 0.95, ("b", "c"): 0.6, ("a", "c"): 0.05}
    assert cluster(["a", "b", "c"], probs, set()) == [["a", "b"], ["c"]]
