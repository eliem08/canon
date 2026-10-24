import pytest

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


# ---------------------------------------------------------------- acronyms (French registry cases)


@pytest.mark.parametrize(
    "short, full",
    [
        ("A V E C", "Association Vie et Cancer"),  # letter by letter, keeps "et"
        ("A.E.S.", "Avenir Environnement Services"),
        ("GEGOS", "Groupe Etudes Gynecologiques Obstetricales Soissons"),  # 5 letters
        ("ADICE", "Ass Dep Interprof Conseil aux Entreprise"),  # skips "aux"
        ("ASK Soissons", "Association Sportive de Karting de Soissons"),  # acronym + place
    ],
)
def test_acronyms_match_their_full_names(short, full):
    from canon.models import SourceRecord
    from canon.resolve.features import features
    from canon.resolve.scoring import name_similarity

    fa = features(SourceRecord(record_id="a", source="crm", locator="x", name=short))
    fb = features(SourceRecord(record_id="b", source="crm", locator="x", name=full))
    assert name_similarity(fa, fb) >= 0.85


@pytest.mark.parametrize("a, b", [("LP", "Laon Primeurs"), ("J.C.E.", "J.S.E")])
def test_two_letter_acronyms_and_one_letter_differences_do_not_match(a, b):
    from canon.models import SourceRecord
    from canon.resolve.features import features
    from canon.resolve.scoring import name_similarity

    fa = features(SourceRecord(record_id="a", source="crm", locator="x", name=a))
    fb = features(SourceRecord(record_id="b", source="crm", locator="x", name=b))
    assert name_similarity(fa, fb) < 0.6


def test_two_records_alone_at_an_address_go_to_review_not_merged():
    from canon.models import SourceRecord
    from canon.resolve.pipeline import resolve

    recs = [
        SourceRecord(record_id="r1", source="crm", locator="x", name="SARL F.F.T.",
                     address="7 Rue de la Banniere", city="Soissons"),
        SourceRecord(record_id="r2", source="crm", locator="x", name="L'Art Marocain",
                     address="7 RUE DE LA BANNIERE", city="SOISSONS"),
        SourceRecord(record_id="r3", source="crm", locator="x", name="Teen Fashions",
                     address="2 Rue du College", city="Soissons"),
        SourceRecord(record_id="r4", source="crm", locator="x", name="Les Loustics",
                     address="2 RUE DU COLLEGE", city="Soissons"),
        SourceRecord(record_id="r5", source="crm", locator="x", name="Camille Albane",
                     address="2 Rue du College", city="Soissons"),
    ]  # fmt: skip
    res = resolve(recs)
    assert all(len(c) == 1 for c in res.clusters)  # names share nothing: never merged
    queued = {frozenset((i.left, i.right)) for i in res.review}
    assert frozenset(("r1", "r2")) in queued  # alone at their address: a person decides
    assert not any(p <= {"r3", "r4", "r5"} for p in queued)  # three at one address: no signal


def _addr(name, address):
    return features(SourceRecord(record_id=name + address, source="crm", locator="x", name=name,
                                 address=address, city="Soissons"))  # fmt: skip


def test_another_house_number_on_the_same_street_is_another_address():
    s = score_pair(_addr("Pas a Pas", "22 Boulevard Jeanne d'Arc"),
                   _addr("Pas a Pas", "6 Bd Jeanne d'Arc"), ScoringConfig())  # fmt: skip
    assert s.evidence["address"] < 0
    s = score_pair(_addr("Pas a Pas", "22 Boulevard Jeanne d'Arc"),
                   _addr("Pas a Pas", "22 Bd Jeanne d'Arc"), ScoringConfig())  # fmt: skip
    assert s.evidence["address"] > 0


def test_two_full_addresses_that_differ_count_more_than_a_vague_one():
    cfg = ScoringConfig()
    full = score_pair(_addr("SAP", "62 Rue Saint Martin"), _addr("SAP", "35 Bd Jeanne d'Arc"), cfg)
    vague = score_pair(_addr("SAP", "Rue Saint Martin"), _addr("SAP", "La Gare"), cfg)
    assert full.evidence["address"] == cfg.address_disagree_full < vague.evidence["address"]
