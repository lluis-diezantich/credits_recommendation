"""Which seeds are one scene, and what the floor is holding back.

The measurement these encode: 2 of 380 candidates connect to more than one
scene, so `breadth`'s seed count is almost always a count WITHIN one scene,
and the scenes hand out co-signs at wildly different rates. docs/adr/D37.
"""

from __future__ import annotations

import policy
from core import scenes


def seeds(**by_seed):
    """Seed -> co-artist set, from short name lists."""
    return {name: set(people) for name, people in by_seed.items()}


# ---- grouping -----------------------------------------------------------


def test_seeds_sharing_enough_co_artists_are_one_scene():
    by_seed = seeds(a=["p", "q", "r", "s"], b=["p", "q", "r", "s"], c=["z"])
    labels = scenes.group(by_seed, floor=4)
    assert labels["a"] == labels["b"]
    assert labels["c"] != labels["a"]


def test_a_seed_sharing_less_than_the_floor_stays_its_own_scene():
    by_seed = seeds(a=["p", "q", "r"], b=["p", "q", "r"])
    assert scenes.group(by_seed, floor=4) == {"a": "a", "b": "b"}


def test_the_scene_is_named_after_its_best_connected_member():
    """A member, not a number: `scene 1` is stable and meaningless, and the
    scenes are derived, so a number would move under the reader."""
    by_seed = seeds(small=["p", "q", "r", "s"],
                    big=["p", "q", "r", "s", "t", "u", "v"])
    assert set(scenes.group(by_seed, floor=4).values()) == {"big"}


def test_the_label_does_not_depend_on_dict_order():
    """It is what --scene matches and what a logged run would record."""
    forward = scenes.group(seeds(a=["p", "q"], b=["p", "q"]), floor=2)
    backward = scenes.group(seeds(b=["p", "q"], a=["p", "q"]), floor=2)
    assert forward == backward


def test_linkage_is_transitive_which_is_the_trap_the_floor_guards():
    """At a floor of 2 the real data put Bjork in Bad Bunny's scene through
    ROSALIA, on the strength of one remix. a-b and b-c make one scene of three
    even though a and c share nobody."""
    by_seed = seeds(a=["p", "q"], b=["p", "q", "y", "z"], c=["y", "z"])
    labels = scenes.group(by_seed, floor=2)
    assert labels["a"] == labels["c"]
    assert not by_seed["a"] & by_seed["c"]


def test_raising_the_floor_breaks_a_chain():
    by_seed = seeds(a=["p", "q"], b=["p", "q", "y", "z"], c=["y", "z"])
    labels = scenes.group(by_seed, floor=3)
    assert len(set(labels.values())) == 3


def test_a_seed_with_no_co_artists_is_still_a_scene():
    """It has no candidates to rank, and dropping it would make the scene
    count disagree with the seed count for no visible reason."""
    assert scenes.group(seeds(lonely=[]), floor=4) == {"lonely": "lonely"}


# ---- assigning candidates ----------------------------------------------


def test_a_candidate_reaches_every_scene_its_seeds_are_in():
    labels = {"a": "a", "b": "a", "c": "c"}
    assert scenes.of_candidate(["a", "b"], labels) == ["a"]
    assert scenes.of_candidate(["a", "c"], labels) == ["a", "c"]


def test_an_unknown_seed_name_is_ignored_rather_than_invented():
    """`seed_names` comes from GROUP_CONCAT; a name the grouping never saw is
    a bug upstream and must not create a scene of its own."""
    assert scenes.of_candidate(["a", "ghost"], {"a": "a"}) == ["a"]


def test_a_cross_scene_candidate_appears_in_both_lists():
    """Papo Lucca reaches Sonora Ponceña and Celia Cruz, and he is a real
    recommendation in both. Dropping him from one would make the per-scene
    lists disagree with the global one invisibly."""
    rows = [{"name": "Papo Lucca", "seeds": ["a", "c"]},
            {"name": "Only A", "seeds": ["a"]}]
    grouped = scenes.split(rows, {"a": "a", "c": "c"}, lambda r: r["seeds"])
    assert [r["name"] for r in grouped["a"]] == ["Papo Lucca", "Only A"]
    assert [r["name"] for r in grouped["c"]] == ["Papo Lucca"]


def test_a_candidate_whose_seeds_are_all_unknown_lands_nowhere():
    grouped = scenes.split([{"seeds": ["ghost"]}], {"a": "a"},
                           lambda r: r["seeds"])
    assert grouped == {}


# ---- sessions and lift --------------------------------------------------


def test_a_gap_longer_than_the_window_starts_a_new_session():
    listens = [(0, "a"), (10, "b"), (10_000, "a")]
    total, together, counted = scenes.sessions(listens, 60, {"a", "b"})
    assert counted == 2
    assert total == {"a": 2, "b": 1}
    assert together == {("a", "b"): 1}


def test_a_key_heard_twice_in_one_session_counts_once():
    """Sessions, not plays: the question is what you played in one sitting."""
    total, _, counted = scenes.sessions(
        [(0, "a"), (1, "a"), (2, "a")], 60, {"a"})
    assert (total, counted) == ({"a": 1}, 1)


def test_every_session_counts_even_with_none_of_the_wanted_keys():
    """The denominator must not depend on WHICH keys are asked about. Counting
    only seed-bearing sessions took the total from 3,177 to 14,109 the moment
    11 candidates joined the question, multiplied every lift by 4.4, and moved
    which seeds were one scene."""
    _, _, counted = scenes.sessions([(0, "x"), (10_000, "y")], 60, {"a"})
    assert counted == 2


def test_the_denominator_does_not_move_when_more_keys_are_asked_about():
    listens = [(0, "a"), (10, "b"), (10_000, "c")]
    narrow = scenes.sessions(listens, 60, {"a", "b"})
    wide = scenes.sessions(listens, 60, {"a", "b", "c"})
    assert narrow[2] == wide[2] == 2
    # ... so a pair's lift is the same question either way
    assert (scenes.lift(narrow[1].get(("a", "b"), 0), narrow[0]["a"],
                        narrow[0]["b"], narrow[2])
            == scenes.lift(wide[1].get(("a", "b"), 0), wide[0]["a"],
                           wide[0]["b"], wide[2]))


def test_lift_is_one_when_two_keys_meet_exactly_as_often_as_chance():
    #  10 sessions, each key in 5, so chance predicts 2.5 shared
    assert scenes.lift(shared=5, total_a=5, total_b=5, n_sessions=10) == 2.0
    assert scenes.lift(shared=2, total_a=5, total_b=5, n_sessions=10) == 0.8
    assert scenes.lift(shared=5, total_a=5, total_b=10, n_sessions=10) == 1.0


def test_lift_corrects_for_a_seed_that_is_in_everything():
    """Bad Bunny was in 551 of 3,177 seed sessions, so a RAW count made him
    close to every seed. The pair below shares more sessions and is less
    close."""
    everywhere = scenes.lift(shared=50, total_a=500, total_b=200, n_sessions=1000)
    rare = scenes.lift(shared=20, total_a=40, total_b=40, n_sessions=1000)
    assert rare > everywhere


def test_lift_is_zero_rather_than_undefined_when_nothing_is_shared():
    assert scenes.lift(0, 10, 10, 100) == 0.0
    assert scenes.lift(5, 0, 10, 100) == 0.0
    assert scenes.lift(5, 10, 10, 0) == 0.0


# ---- asking the rule about an unwalked artist ---------------------------


def test_joins_reports_everyone_an_unwalked_artist_would_link_to():
    """The signals that need no credits -- co-listening and genre -- are
    readable from the profile, which is what makes a scene predictable before
    50 requests are spent."""
    def reason_for(_candidate, seed):
        return "together" if seed in {"a", "b"} else None

    assert scenes.joins("new", ["a", "b", "c"], reason_for) == [
        ("a", "together"), ("b", "together")]


def test_joins_never_links_an_artist_to_itself():
    assert scenes.joins("a", ["a"], lambda *_: "together") == []


def test_joins_is_empty_when_the_rule_says_nothing():
    assert scenes.joins("new", ["a"], lambda *_: None) == []


# ---- grouping from explicit links --------------------------------------


def test_group_links_labels_by_the_sizes_it_is_given():
    labels = scenes.group_links({"a": 1, "b": 9}, [("a", "b")])
    assert set(labels.values()) == {"b"}


def test_group_links_leaves_an_unlinked_key_as_its_own_scene():
    assert scenes.group_links({"a": 1, "b": 2}, []) == {"a": "a", "b": "b"}


# ---- the policy rule ----------------------------------------------------


def test_enough_shared_co_artists_links_whatever_the_genres_say():
    """A credit link is never vetoed: two artists who worked with the same
    people are connected, and the tags are one or two votes deep."""
    reason = policy.scene_link(policy.SCENE_SHARED_FLOOR, 0, 0.0, set())
    assert reason == f"{policy.SCENE_SHARED_FLOOR} co-artists"


def test_co_listening_links_only_when_a_genre_confirms_it():
    """The veto, and the measurement behind it: linking on a shared tag put 18
    of 20 seeds in one scene, while vetoing with one removed exactly the three
    that were shuffle adjacency -- Little Simz, Bomba Estéreo and CHUWI."""
    high = policy.SCENE_LIFT_FLOOR + 1
    assert policy.scene_link(0, policy.SCENE_MIN_SESSIONS, high, {"salsa"})
    assert policy.scene_link(0, policy.SCENE_MIN_SESSIONS, high, set()) is None


def test_a_lift_below_the_floor_is_not_a_link_even_with_a_shared_genre():
    assert policy.scene_link(0, policy.SCENE_MIN_SESSIONS,
                             policy.SCENE_LIFT_FLOOR - 0.1, {"salsa"}) is None


def test_too_few_shared_sessions_is_not_believed_however_high_the_lift():
    """A lift computed from 2 sessions is arithmetic, not evidence."""
    assert policy.scene_link(0, policy.SCENE_MIN_SESSIONS - 1, 50.0,
                             {"salsa"}) is None


def test_a_broad_genre_cannot_confirm_a_link():
    """"latin" is held by 13 of 20 seeds, so it would have made every Latin
    seed one scene. Computed as a share, not kept as a hand list, because the
    right answer moves as seeds are added."""
    by_seed = {f"s{n}": {"latin", "salsa"} if n < 6 else {"latin"}
               for n in range(20)}
    broad = policy.broad_genres(by_seed)
    assert "latin" in broad
    assert "salsa" not in broad


def test_the_threshold_sits_in_the_gap_rather_than_at_its_edge():
    """Real shares: "latin" 13/20, "salsa" 6/20, nothing between. At 1/3 the
    ceiling is 6.7 and one more salsa seed would veto the tag the salsa scene
    depends on; at 1/2 it takes eleven."""
    salsa_seeds = 7
    by_seed = {f"s{n}": {"salsa"} if n < salsa_seeds else {"other"}
               for n in range(20)}
    assert "salsa" not in policy.broad_genres(by_seed)
    assert policy.SCENE_BROAD_GENRE_SHARE == 1 / 2


def test_no_genres_at_all_means_nothing_is_broad():
    assert policy.broad_genres({}) == set()
    assert policy.broad_genres({"a": set(), "b": set()}) == set()


# ---- the floor itself ---------------------------------------------------


def test_the_floor_is_a_policy_number_and_core_does_not_import_it():
    """`core/` never imports `policy` -- the threshold arrives as an argument.
    4 is measured: at 2 everything chains into one scene, at 5 the salsa
    scene loses Celia Cruz and Ruben Blades."""
    assert policy.SCENE_SHARED_FLOOR == 4
    source = (scenes.__file__ or "")
    assert source.endswith("scenes.py")
    with open(source) as handle:
        assert "import policy" not in handle.read()
