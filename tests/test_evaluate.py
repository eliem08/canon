from canon.resolve.evaluate import bcubed, blocking_quality, pairwise

TRUTH = {"a": "E1", "b": "E1", "c": "E1", "d": "E2"}


def test_perfect_clustering():
    m = pairwise([["a", "b", "c"], ["d"]], TRUTH)
    assert (m.precision, m.recall, m.f1) == (1.0, 1.0, 1.0)


def test_split_and_merge():
    split = pairwise([["a", "b"], ["c"], ["d"]], TRUTH)  # 1 of 3 true pairs
    assert split.precision == 1.0 and round(split.recall, 3) == 0.333
    merged = pairwise([["a", "b", "c", "d"]], TRUTH)  # 3 true of 6 predicted
    assert merged.recall == 1.0 and merged.precision == 0.5


def test_bcubed_perfect():
    assert bcubed([["a", "b", "c"], ["d"]], TRUTH).f1 == 1.0


def test_blocking_quality():
    q = blocking_quality({("a", "b"), ("a", "c")}, TRUTH)
    assert q["all_pairs"] == 6 and round(q["pair_completeness"], 3) == 0.667
