import filecmp
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from canon.synth import generate

DATA = Path(__file__).resolve().parents[1] / "data" / "synthetic"


@pytest.fixture(scope="module")
def truth():
    return json.loads((DATA / "ground_truth" / "ground_truth.json").read_text(encoding="utf-8"))


def _raw_record_ids(root: Path) -> set[str]:
    crm = json.loads((root / "crm" / "accounts.json").read_text(encoding="utf-8"))
    channels = json.loads((root / "slack" / "channels.json").read_text(encoding="utf-8"))
    ids = {f"crm:{a['Id']}" for a in crm}
    ids |= {f"slack:{c['id']}" for c in channels}
    ids |= {f"contract:{p.stem}" for p in (root / "contracts").glob("*.txt")}
    return ids


def test_generation_is_deterministic_and_matches_committed_data(tmp_path):
    generate(tmp_path)
    cmp = filecmp.dircmp(DATA, tmp_path)

    def assert_same(c: filecmp.dircmp) -> None:
        assert not c.left_only and not c.right_only, (c.left_only, c.right_only)
        _, mismatch, errors = filecmp.cmpfiles(c.left, c.right, c.common_files, shallow=False)
        assert not mismatch and not errors, mismatch
        for sub in c.subdirs.values():
            assert_same(sub)

    assert_same(cmp)


def test_25_entities_each_appearing_3_to_6_times(truth):
    assert len(truth["entities"]) == 25
    counts = Counter(truth["records"].values())
    assert set(counts) == set(truth["entities"])
    assert all(3 <= n <= 6 for n in counts.values()), counts


def test_ground_truth_maps_every_raw_record(truth):
    assert _raw_record_ids(DATA) == set(truth["records"])


def test_every_contract_has_a_superseded_version():
    stems = sorted(p.stem for p in (DATA / "contracts").glob("*.txt"))
    numbers = Counter(s.rsplit("_v", 1)[0] for s in stems)
    assert len(numbers) == 25 and set(numbers.values()) == {2}
    for number in numbers:
        v2 = (DATA / "contracts" / f"{number}_v2.txt").read_text(encoding="utf-8")
        assert re.search(r"annule et remplace|supersedes and replaces", v2)


def test_messiness_is_present(truth):
    crm = json.loads((DATA / "crm" / "accounts.json").read_text(encoding="utf-8"))
    names = [a["Account Name"] for a in crm]
    assert any(re.search(r"[؀-ۿ]", n) for n in names), "Arabic-script CRM names"
    assert any(n.startswith("Chrikat") for n in names), "Darija-in-Latin CRM names"
    suffixes = {"SARL", "S.A.R.L.", "S.A.R.L", "Sarl", "SA", "S.A.", "Ltd", "LTD", "Limited"}
    seen = {tok for n in names for tok in n.split() if tok in suffixes}
    assert len(seen) >= 5, seen  # several spellings of the same legal forms
    channels = json.loads((DATA / "slack" / "channels.json").read_text(encoding="utf-8"))
    assert any(c["is_archived"] for c in channels)
    slack_text = " ".join(
        m["text"] for p in (DATA / "slack").glob("*/*.json") for m in json.loads(p.read_text())
    )
    for word in ("dyal", "3la", "chrika", "howa"):
        assert word in slack_text
    notes = [n for ns in truth["record_notes"].values() for n in ns]
    assert any(n.startswith("stale:") for n in notes)
    assert any(n == "name:typo" for n in notes)


def test_current_facts_are_present_for_every_entity(truth):
    for entity in truth["entities"].values():
        for key in ("owner", "contract_value", "renewal_date", "domain", "phone", "tax_id"):
            assert entity[key], key
        assert entity["renewal_date"] > truth["reference_date"]
