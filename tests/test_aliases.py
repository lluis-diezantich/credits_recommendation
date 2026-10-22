"""core/aliases.py and the report that feeds it.

The file is hand-edited, so what is worth testing is not its contents but the
three things the code around it must get right: a missing file is the old
behaviour and not a crash, the canonical name is the one that gets displayed,
and nothing merges itself. docs/adr/D25 has the decision; test_discover.py
covers what the merge does to a walk's counts.
"""

from __future__ import annotations

import difflib
import json

import pytest

import policy
from core import aliases

# Bjork's graph, in the shape the file writes it.
FILE = {"people": [
    {"name": "Sjón",
     "also": ["Sigurjón Birgir Sigurðsson", "Sigurjon Sigurdsson"],
     "why": "pen name"},
    {"name": "Arca", "also": ["Alejandro Ghersi"]},
]}


@pytest.fixture
def written(tmp_path):
    (tmp_path / aliases.FILE).write_text(json.dumps(FILE, ensure_ascii=False))
    return tmp_path


def ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


# ---- the map ------------------------------------------------------------


def test_every_spelling_maps_to_the_performing_name(written):
    """Not to the legal one. It is the key listens.artist_key carries, so the
    59% hit-rate measurement still joins after a merge."""
    found = aliases.load(written)
    assert found["sigurjon sigurdsson"] == "sjon"
    assert found["sigurjon birgir sigursson"] == "sjon"
    assert found["alejandro ghersi"] == "arca"


def test_the_canonical_name_maps_to_itself(written):
    """So a caller can look up any spelling, including the one it is keyed
    under, without checking which it has."""
    assert aliases.load(written)["sjon"] == "sjon"


def test_a_name_not_in_the_file_is_left_alone(written):
    found = aliases.load(written)
    assert aliases.person_key("Nellee Hooper", found) == "nellee hooper"


def test_no_file_means_the_behaviour_this_project_had_until_now(tmp_path):
    """Every count here was computed without an alias map, so the answer to a
    missing file is the old numbers and not a stop."""
    assert aliases.load(tmp_path) == {}
    assert aliases.person_key("Alejandro Ghersi", {}) == "alejandro ghersi"
    assert aliases.person_key("Alejandro Ghersi", None) == "alejandro ghersi"


def test_an_unreadable_file_is_also_just_an_empty_map(tmp_path):
    """A half-written file during an edit must not take the pipeline down."""
    (tmp_path / aliases.FILE).write_text("{ not json")
    assert aliases.load(tmp_path) == {}
    assert aliases.display_names(tmp_path) == {}


def test_an_entry_with_no_name_is_skipped_rather_than_keyed_empty(tmp_path):
    (tmp_path / aliases.FILE).write_text(json.dumps(
        {"people": [{"name": "", "also": ["X"]}, {"also": ["Y"]}]}))
    assert aliases.load(tmp_path) == {}


def test_the_display_name_is_the_file_s_own_spelling(written):
    """Bjork's merged composer was printed as "Sigurjon Birgir Sigurdsson" --
    whichever spelling sorted first, which is the legal name, which is the
    half of the split nobody recognises."""
    assert aliases.display_names(written)["sjon"] == "Sjón"
    assert aliases.display_names(written)["arca"] == "Arca"


# ---- the report ---------------------------------------------------------


def test_two_names_one_inside_the_other_are_worth_a_look():
    assert policy.alias_candidate("sampha", "sampha sisay", ratio) == "bare"
    assert policy.alias_candidate(
        "michael kiwanuka", "michael samuel kiwanuka", ratio) == "subset"


def test_a_single_surname_is_reported_apart_from_the_rest():
    """"Massey", "Glennie", "Reisfeld" -- right often enough to read, wrong
    often enough that nothing may act on it. It is the single_token_name
    class, which is 47% of the candidate pool."""
    assert policy.alias_candidate("graham massey", "massey", ratio) == "bare"


def test_a_typo_or_a_diacritic_is_a_spelling_candidate():
    assert policy.alias_candidate(
        "jakobina sigurdardotti", "jakobina sigurdardottir", ratio) == "spelling"
    assert policy.alias_candidate(
        "alejandra ghersi", "alejandro ghersi", ratio) == "spelling"


def test_a_person_and_their_band_are_not_two_spellings():
    """Both are billable acts, and merging them would delete one of them.
    "Calequi" / "Calequi y Las Panteras" and "Javier Colina" / "Javier Colina
    Trio" are the two in the corpus."""
    assert policy.alias_candidate("calequi", "calequi y las panteras", ratio) is None
    assert policy.alias_candidate("javier colina", "javier colina trio", ratio) is None


def test_two_unrelated_people_are_not_reported():
    assert policy.alias_candidate("nellee hooper", "mark bell", ratio) is None


def test_the_similarity_floor_is_the_one_the_titles_already_use():
    """Same question asked of two strings a label typed, so it is reused
    rather than re-derived."""
    assert policy.NAME_SIMILARITY == policy.TITLE_SIMILARITY
