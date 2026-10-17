"""stages/resolve_discogs.py: the gates, which used to exist in two copies.

This stage spends the scarcest thing in the project -- Discogs requests at 25 a
minute -- so every decision in it is about who is worth one. There are two
gates and they cost different amounts:

  --min-role-weight   read off the person's top role, so it costs NOTHING. It
                      is applied BEFORE --top on purpose: the budget should buy
                      N viable people, not N rows of which a third are
                      masterers.
  --min-signal        needs the Discogs total, which arrives with page 1, so it
                      costs ONE request instead of max_pages plus the whole
                      Qobuz fan-out the credits would have caused.

Both lived twice before the extraction: once in main()'s live path and once in
--explain-gate, which exists to predict what the live path will do. Two copies
of a prediction and the thing it predicts is the one arrangement where drift is
invisible -- the explain output would have been wrong, and confidently. They
are one function now, and these are its tests.
"""

from __future__ import annotations

import pytest

import stages.resolve_discogs as mod


def person(albums=5, roles=("Producer",)):
    return {"names": ["Someone"], "albums": albums, "roles": list(roles)}


# ---- parse_role_selection -----------------------------------------------


def test_a_class_name_is_recognised_as_a_class():
    assert mod.parse_role_selection("production") == ({"production"}, set())


def test_a_specific_role_is_folded_to_its_key():
    """So "Mixed by" and "MixedBy" both match what resolve_qobuz wrote."""
    assert mod.parse_role_selection("Mixed by") == (set(), {"mixedby"})


def test_classes_and_roles_can_be_mixed():
    classes, roles = mod.parse_role_selection("production,Bass,engineering")
    assert classes == {"production", "engineering"}
    assert roles == {"bass"}


def test_blanks_and_padding_are_ignored():
    assert mod.parse_role_selection(" , production , ") == ({"production"}, set())
    assert mod.parse_role_selection("") == (set(), set())


def test_a_class_name_is_matched_case_insensitively():
    assert mod.parse_role_selection("PRODUCTION") == ({"production"}, set())


# ---- wanted -------------------------------------------------------------


def test_no_selection_keeps_everyone():
    assert mod.wanted(person(), set(), set(), False) is True


def test_a_person_with_no_roles_is_dropped_by_any_selection():
    """Nothing to match on, and guessing would spend a request on no evidence."""
    assert mod.wanted({"roles": []}, {"production"}, set(), False) is False


def test_only_the_top_role_is_matched_by_default():
    """What they MAINLY are. An engineer who once played guitar is an engineer."""
    engineer = person(roles=("Mastered by", "Guitar"))
    assert mod.wanted(engineer, {"performance"}, set(), False) is False
    assert mod.wanted(engineer, {"engineering"}, set(), False) is True


def test_roles_any_lets_in_anyone_credited_with_it():
    """Opt-in, because it lets in an engineer who once played guitar."""
    engineer = person(roles=("Mastered by", "Guitar"))
    assert mod.wanted(engineer, {"performance"}, set(), True) is True


def test_a_specific_role_matches_as_well_as_a_class():
    assert mod.wanted(person(roles=("Producer",)), set(), {"producer"}, False) is True


# ---- signal_of ----------------------------------------------------------


def test_the_signal_is_the_weight_times_the_selectivity():
    sig, score, band = mod.signal_of(1.0, 45)
    assert (sig, score, band) == (1.0, 1.0, "selective")


def test_a_prolific_person_scores_lower_on_the_same_role():
    """Fred Kevorkian has mastered 1,070 releases across every genre; one more
    credit from him says almost nothing."""
    selective, _, _ = mod.signal_of(1.0, 45)
    service, _, band = mod.signal_of(1.0, 1070)
    assert service < selective
    assert band == "service"


# ---- gate_verdict: the one copy -----------------------------------------


def test_a_weak_top_role_is_gated_before_any_request_is_made():
    """A mastering engineer scores 0.15 against a 0.2 floor, and this costs
    nothing to decide -- which is the whole point of having two gates."""
    assert mod.gate_verdict(0.15, None, 0.2, 0.2) == ("gated_free", None, None)
    assert mod.gate_verdict(0.15, 1070, 0.2, 0.2)[0] == "gated_free"


def test_a_strong_role_with_no_total_yet_is_unknown_not_a_pass():
    """Only --explain-gate sees this, replaying offline against totals a
    previous run happened to write. "Unknown" is honest; "keep" would be a
    prediction the data does not support."""
    assert mod.gate_verdict(1.0, None, 0.2, 0.2) == ("unknown", None, None)


def test_a_prolific_person_is_gated_after_one_page():
    """The total arrives with page 1, so this costs one request rather than
    max_pages plus every Qobuz release fetch the credits would have caused."""
    verdict, select, signal = mod.gate_verdict(0.45, 1070, 0.2, 0.2)
    assert verdict == "gated_after_page_1"
    assert (select, signal) == (0.1, pytest.approx(0.045))


def test_a_selective_collaborator_is_kept():
    verdict, select, signal = mod.gate_verdict(1.0, 45, 0.2, 0.2)
    assert verdict == "keep"
    assert (select, signal) == (1.0, 1.0)


def test_the_role_weight_floor_is_inclusive():
    """MIN_ROLE_WEIGHT is calibrated to keep an assistant engineer exactly on
    the boundary, so `>=` rather than `>` is load-bearing."""
    assert mod.gate_verdict(0.2, 45, 0.2, 0.2)[0] == "keep"
    assert mod.gate_verdict(0.19, 45, 0.2, 0.2)[0] == "gated_free"


def test_the_signal_floor_is_inclusive_too():
    weight = 0.4
    on_the_line = mod.signal_of(weight, 45)[0]
    assert mod.gate_verdict(weight, 45, 0.2, on_the_line)[0] == "keep"
    assert mod.gate_verdict(weight, 45, 0.2, on_the_line + 0.01)[0] == (
        "gated_after_page_1")


def test_a_zero_floor_gates_nothing():
    assert mod.gate_verdict(0.0, 0, 0.0, 0.0)[0] == "keep"


def test_every_verdict_is_reachable_and_they_are_the_only_four():
    """A fifth would land in --explain-gate's label table as a KeyError, which
    is the right failure but only if somebody notices the set changed."""
    verdicts = {
        mod.gate_verdict(0.15, 45, 0.2, 0.2)[0],
        mod.gate_verdict(1.0, None, 0.2, 0.2)[0],
        mod.gate_verdict(0.45, 1070, 0.2, 0.2)[0],
        mod.gate_verdict(1.0, 45, 0.2, 0.2)[0],
    }
    assert verdicts == {"gated_free", "unknown", "gated_after_page_1", "keep"}


# ---- select_targets -----------------------------------------------------


def test_the_people_with_most_seed_albums_come_first():
    """The rate limit means a run may not reach the end of the list, so the
    order decides who actually gets looked up."""
    people = [person(albums=1), person(albums=21), person(albums=7)]
    targets, _, _ = mod.select_targets(people, set(), set(), False, 0.0, 10)
    assert [p["albums"] for p in targets] == [21, 7, 1]


def test_a_missing_album_count_sorts_last_rather_than_raising():
    people = [{"names": ["A"], "roles": ["Producer"]}, person(albums=3)]
    targets, _, _ = mod.select_targets(people, set(), set(), False, 0.0, 10)
    assert [p.get("albums") for p in targets] == [3, None]


def test_top_caps_the_spend():
    people = [person(albums=n) for n in range(10)]
    targets, _, _ = mod.select_targets(people, set(), set(), False, 0.0, 3)
    assert len(targets) == 3


def test_the_weight_filter_runs_before_top_not_after():
    """"the budget should buy N viable people, not N rows of which a third are
    masterers". Three masterers ahead of three producers, --top 3: the old
    order would have spent the whole budget on the masterers and returned
    nothing usable."""
    masterers = [person(albums=100 - i, roles=("Mastered by",)) for i in range(3)]
    producers = [person(albums=10 - i, roles=("Producer",)) for i in range(3)]
    targets, _, _ = mod.select_targets(masterers + producers, set(), set(),
                                       False, 0.2, 3)
    assert len(targets) == 3
    assert all(p["roles"] == ["Producer"] for p in targets)


def test_the_two_counts_report_what_each_filter_removed():
    """Returned rather than recomputed, so the caller's two log lines cannot
    disagree with what was actually selected."""
    people = ([person(albums=9, roles=("Producer",))] * 2
              + [person(albums=8, roles=("Mastered by",))] * 3
              + [person(albums=7, roles=("Bass",))] * 4)
    targets, after_roles, after_weight = mod.select_targets(
        people, {"production", "engineering"}, set(), False, 0.2, 100)
    assert after_roles == 5             # producers + masterers, not the bassists
    assert after_weight == 2            # masterers dropped at no request cost
    assert len(targets) == 2


def test_no_filters_at_all_keeps_everyone_in_order():
    people = [person(albums=n) for n in (3, 1, 2)]
    targets, after_roles, after_weight = mod.select_targets(
        people, set(), set(), False, 0.0, 100)
    assert [p["albums"] for p in targets] == [3, 2, 1]
    assert after_roles == after_weight == 3


def test_selecting_from_nobody_is_nobody():
    assert mod.select_targets([], set(), set(), False, 0.2, 10) == ([], 0, 0)


def test_the_weight_filter_shares_the_gate_rather_than_reimplementing_it():
    """select_targets calls gate_verdict, so the free gate and the explain mode
    cannot drift. A person gated here must be gated_free there."""
    masterer = person(roles=("Mastered by",))
    targets, _, _ = mod.select_targets([masterer], set(), set(), False, 0.2, 10)
    assert targets == []
    assert mod.gate_verdict(mod.person_role_weight(masterer), None, 0.2,
                            0.2)[0] == "gated_free"


# ---- known_totals -------------------------------------------------------


def test_totals_are_recovered_from_both_shapes_a_previous_run_wrote():
    """recovered/ uses `discogs_total_releases` and still_unresolved/ uses
    `discogs_total`. Two field names for one number, which is why this reads
    both rather than one."""
    saved = {"recovered": [{"names": ["Ana Prada"], "discogs_total_releases": 45}],
             "still_unresolved": [{"names": ["Ghost"], "discogs_total": 900}]}
    assert mod.known_totals(saved) == {"ana prada": 45, "ghost": 900}


def test_every_spelling_of_a_name_gets_the_total():
    """So an explain run matches whichever spelling the unresolved entry uses."""
    saved = {"recovered": [{"names": ["Carles Campi Campon", "Carles Campon"],
                            "discogs_total_releases": 45}]}
    assert mod.known_totals(saved) == {"carles campi campon": 45,
                                       "carles campon": 45}


def test_a_row_with_no_total_contributes_nothing():
    """Absent and zero are both skipped: a zero total would score as `unknown`
    selectivity anyway, and recording it as known would be a false claim."""
    saved = {"recovered": [{"names": ["A"]}, {"names": ["B"],
                                              "discogs_total_releases": 0}]}
    assert mod.known_totals(saved) == {}


def test_an_empty_or_unfamiliar_file_yields_nothing():
    assert mod.known_totals({}) == {}
    assert mod.known_totals({"recovered": [], "still_unresolved": []}) == {}


def test_names_are_normalised_so_accents_match():
    saved = {"recovered": [{"names": ["Carles Campi Campón"],
                            "discogs_total_releases": 45}]}
    assert mod.known_totals(saved) == {"carles campi campon": 45}


# ---- role_census --------------------------------------------------------


def test_the_census_counts_top_roles_most_common_first():
    people = ([person(roles=("Producer",))] * 3
              + [person(roles=("Mastered by",))] * 5)
    tops, _ = mod.role_census(people)
    assert tops.most_common() == [("Mastered by", 5), ("Producer", 3)]


def test_the_census_counts_only_the_top_role_not_every_role():
    """It describes what --min-role-weight will act on, and that reads [0]."""
    tops, _ = mod.role_census([person(roles=("Producer", "Bass", "Vocal"))])
    assert tops.most_common() == [("Producer", 1)]


def test_the_census_also_groups_by_class():
    people = [person(roles=("Producer",)), person(roles=("Mastered by",)),
              person(roles=("Mixed by",))]
    _, by_class = mod.role_census(people)
    assert dict(by_class) == {"production": 1, "engineering": 2}


def test_a_person_with_no_roles_is_counted_in_neither():
    tops, by_class = mod.role_census([{"roles": []}, person(roles=("Producer",))])
    assert sum(tops.values()) == 1
    assert sum(by_class.values()) == 1


def test_a_census_of_nobody_is_empty():
    tops, by_class = mod.role_census([])
    assert not tops and not by_class
