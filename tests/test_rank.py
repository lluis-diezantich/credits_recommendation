"""core/rank.py and policy's strategies: features, order, and the shown-log.

Three layers, tested where each one lives. The features and the ordering are
pure (`core.rank`), the strategies are judgement (`policy`), and the SQL and
the log are the stage. docs/adr/D29 has the decision, including the part that
matters most here: not one strategy weight is measured, so what these tests
pin is that each strategy makes the claim it says it makes -- not that the
claim is right.
"""

from __future__ import annotations

import datetime as dt

import pytest

import policy
from core import rank

TODAY = dt.date(2026, 10, 22)


def feat(**over) -> dict:
    """A feature row with everything at nothing, so a test sets only its axis."""
    row = {"person_key": over.get("person_key", "p"), "name": "P", "seeds": 1,
           "seed_names": "Jorge Drexler", "on_seeds": 0, "on_theirs": 0,
           "records": 0, "roles": [], "role_weight": 0.0, "first_seen": None,
           "last_seen": None, "recency": 0.0, "span": 0.0, "seed_plays": 0,
           "plays": 0}
    row.update(over)
    row["records"] = row["on_seeds"] + row["on_theirs"]
    return row


# ---- features -----------------------------------------------------------


def test_a_record_out_today_is_fully_recent_and_a_decade_ago_is_not():
    assert rank.recency("2026-10-22", TODAY) == 1.0
    assert rank.recency("2016-10-22", TODAY) == pytest.approx(0.0, abs=0.01)
    assert 0.4 < rank.recency("2021-10-22", TODAY) < 0.6


def test_an_undated_record_scores_no_recency_rather_than_maximum():
    """"No date on the record" and "released today" are different facts, and
    treating the first as the second ranks an undated row top of the list."""
    assert rank.recency(None, TODAY) == 0.0
    assert rank.recency("", TODAY) == 0.0
    assert rank.recency("not-a-date", TODAY) == 0.0
    assert rank.year_fraction(None, TODAY) is None


def test_recency_is_clamped_at_both_ends():
    """A release date in the future is a thing Qobuz ships -- Taracá is dated
    2026 -- and it must not score above a record out today."""
    assert rank.recency("2027-01-01", TODAY) == 1.0
    assert rank.recency("1950-01-01", TODAY) == 0.0


def test_span_is_the_years_the_collaboration_ran():
    """Four records over eight years is a different relationship from four in
    one afternoon, and only these two dates say which."""
    assert rank.span_years("2016-01-01", "2026-01-01", TODAY) == pytest.approx(10, abs=0.1)
    assert rank.span_years("2026-01-01", "2026-01-01", TODAY) == 0.0
    assert rank.span_years(None, "2026-01-01", TODAY) == 0.0


# ---- the order ----------------------------------------------------------


def test_the_score_the_ordering_used_is_written_onto_the_row():
    """So whatever prints or logs it reports that number rather than
    recomputing and risking a different one."""
    rows = rank.ranked([feat(on_theirs=1)], lambda r: 7.5)
    assert rows[0]["score"] == 7.5


def test_ties_break_on_the_key_so_two_runs_agree():
    """`top_role` already taught this project what an order-dependent field
    costs: a rebuild on another day flips it and the field stops being a fact."""
    rows = [feat(person_key="b"), feat(person_key="a"), feat(person_key="c")]
    assert [r["person_key"] for r in rank.ranked(rows, lambda r: 1.0)] == [
        "a", "b", "c"]


def test_the_strategy_arrives_as_an_argument():
    """core/ never imports policy (D2). A test's own callable has to work."""
    rows = [feat(person_key="a", seeds=1), feat(person_key="b", seeds=3)]
    assert rank.ranked(rows, lambda r: r["seeds"])[0]["person_key"] == "b"


def test_a_limit_cuts_after_the_sort_not_before():
    rows = [feat(person_key=k, on_theirs=n)
            for k, n in (("a", 1), ("b", 5), ("c", 3))]
    top = rank.ranked(rows, lambda r: r["on_theirs"], limit=2)
    assert [r["person_key"] for r in top] == ["b", "c"]


# ---- comparing two strategies -------------------------------------------


def test_the_delta_says_which_way_a_candidate_moved():
    left = [feat(person_key="a"), feat(person_key="b")]
    right = [feat(person_key="b"), feat(person_key="a")]
    moved = {r["person_key"]: r["moved"] for r in rank.rank_delta(left, right)}
    assert moved == {"a": -1, "b": 1}


def test_the_delta_is_ordered_by_how_far_things_moved():
    left = [feat(person_key=k) for k in "abc"]
    right = [feat(person_key=k) for k in "cba"]
    assert [r["person_key"] for r in rank.rank_delta(left, right)][0] in {"a", "c"}


def test_a_candidate_missing_from_one_side_is_skipped_not_guessed():
    left = [feat(person_key="a"), feat(person_key="gone")]
    right = [feat(person_key="a")]
    assert [r["person_key"] for r in rank.rank_delta(left, right)] == ["a"]


# ---- what each strategy claims ------------------------------------------


def test_breadth_puts_one_extra_seed_above_any_amount_of_records():
    """The project's own thesis (D22): a person several of your artists chose
    is better evidence than one your favourite chose repeatedly."""
    two_seeds = feat(seeds=2, on_theirs=1)
    one_seed_many = feat(seeds=1, on_theirs=4, on_seeds=4)
    assert policy.rank_breadth(two_seeds) > policy.rank_breadth(one_seed_many)


def test_direction_prefers_your_artist_turning_up_on_their_record():
    """A guest on your artist's record was chosen by them or their label. Your
    artist appearing on somebody else's is a deliberate act."""
    theirs = feat(on_theirs=1)
    ours = feat(on_seeds=1)
    assert policy.rank_direction(theirs) > policy.rank_direction(ours)


def test_direction_ignores_the_seed_count_and_breadth_does_not():
    """Two strategies that agree about everything would not be two."""
    one, two = feat(seeds=1, on_theirs=2), feat(seeds=2, on_theirs=2)
    assert policy.rank_direction(one) == policy.rank_direction(two)
    assert policy.rank_breadth(one) < policy.rank_breadth(two)


def test_depth_multiplies_by_the_years_rather_than_adding_them():
    """Four records over eight years is a different claim from four in one
    week, and adding the terms would score them the same."""
    long_run = feat(on_theirs=4, span=8.0)
    one_week = feat(on_theirs=4, span=0.0)
    assert policy.rank_depth(long_run) > policy.rank_depth(one_week)
    assert policy.rank_depth(feat(on_theirs=0, span=20.0)) == 0.0


def test_taste_weights_a_co_appearance_by_how_much_you_play_the_seed():
    """6,988 Drexler plays is not the same evidence as 327 Kali Uchis plays,
    and the other three strategies treat them alike."""
    heavy = feat(on_theirs=1, seed_plays=6988)
    light = feat(on_theirs=1, seed_plays=327)
    assert policy.rank_taste(heavy) > policy.rank_taste(light)
    assert policy.rank_breadth(heavy) == policy.rank_breadth(light)


def test_every_strategy_scores_an_empty_candidate_at_zero():
    """No records either way is no evidence, whatever else the row says."""
    nothing = feat(recency=1.0, span=10.0, seed_plays=9999)
    assert policy.rank_depth(nothing) == 0.0
    assert policy.rank_taste(nothing) == 0.0


# ---- the registry -------------------------------------------------------


def test_the_registry_and_the_default_agree():
    assert policy.DEFAULT_STRATEGY in policy.RANKING_STRATEGIES
    assert policy.strategy(None) is policy.RANKING_STRATEGIES[
        policy.DEFAULT_STRATEGY]


def test_every_strategy_is_callable_on_a_feature_row():
    """A strategy that cannot read the row core.rank produces is not one.

    Either shape is allowed -- a float for a weighted sum, a tuple for a
    lexicographic rule -- and core.rank.ranked takes both."""
    row = feat(seeds=2, on_seeds=1, on_theirs=1, recency=0.5, span=2.0,
               seed_plays=1000)
    for name in policy.RANKING_STRATEGIES:
        value = policy.strategy(name)(row)
        assert isinstance(value, (float, tuple)), name
        assert rank.ranked([row], policy.strategy(name))[0]["sort_key"]


def test_an_unknown_strategy_raises_rather_than_falling_back():
    """A typo that silently returned the default would make two runs look like
    they used different strategies and produce the same order, which is the
    one thing the log must never record wrongly."""
    with pytest.raises(KeyError, match="unknown ranking strategy"):
        policy.strategy("breath")


def test_each_strategy_documents_the_claim_it_makes():
    """--list prints the first docstring line, so a strategy without one is
    unexplainable from the command line."""
    for name, fn in policy.RANKING_STRATEGIES.items():
        assert (fn.__doc__ or "").strip(), name


# ---- a lexicographic strategy -------------------------------------------


def test_a_tuple_strategy_orders_on_its_first_element_first():
    rows = [feat(person_key="a", seeds=1), feat(person_key="b", seeds=2)]
    out = rank.ranked(rows, lambda r: (float(r["seeds"]), 99.0 if r["seeds"] == 1 else 0.0))
    assert [r["person_key"] for r in out] == ["b", "a"]


def test_the_second_element_breaks_a_first_element_tie():
    rows = [feat(person_key="a", seeds=2, on_theirs=1),
            feat(person_key="b", seeds=2, on_theirs=5)]
    out = rank.ranked(rows, policy.rank_breadth)
    assert [r["person_key"] for r in out] == ["b", "a"]


def test_the_displayed_score_is_the_leading_number_of_the_key():
    """A tuple strategy still has one number to print, and it is never
    recomputed from the row."""
    out = rank.ranked([feat(seeds=3, on_theirs=2)], policy.rank_breadth)
    assert out[0]["score"] == 3.0
    assert out[0]["sort_key"][0] == 3.0
    assert out[0]["sort_key"][1] > 0


def test_breadth_has_no_seed_constant_left_to_get_wrong():
    """It was a weighted sum with SEED_BREADTH at 10.0, and eight records tied
    with one extra seed -- the opposite of the claim in its name."""
    assert not hasattr(policy, "SEED_BREADTH")
    eight_records = feat(seeds=1, on_theirs=4, on_seeds=4)
    one_more_seed = feat(seeds=2, on_theirs=1)
    assert policy.rank_breadth(one_more_seed) > policy.rank_breadth(eight_records)
