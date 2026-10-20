"""policy.py: the numbers every stage asks before spending a request.

Zero coverage until now, on the one file the project is laid out to make
arguable. These tests are not here to prove the numbers are *right* -- they are
judgement calls, and a test cannot settle them. They are here to pin the two
things that are not judgement:

  the fallback          an unlisted role scores INSTRUMENT_WEIGHT (0.8), which
                        is the silent-upward-drift bug the file's own docstring
                        was written about. Every table entry that exists to be
                        BELOW that fallback is asserted to still be below it.
  the vocabularies      three of them, deliberately disagreeing. todo.md calls
                        unifying them a decision that rewrites existing data,
                        so the disagreement is pinned here on purpose: if one
                        drifts into another, a test fails rather than a column
                        of discovery_*.json quietly changing meaning.
"""

from __future__ import annotations

import pytest

import policy

# ---- role_key: the folding every table lookup goes through ---------------


@pytest.mark.parametrize("spelling", [
    "Co-Producer", "Co- Producer", "co-producer", "CoProducer", "CO  PRODUCER",
])
def test_every_spelling_of_one_role_folds_to_one_key(spelling):
    """Qobuz spells the same role three ways and Discogs a fourth. role_key is
    what lets one table entry answer for all of them."""
    assert policy.role_key(spelling) == "coproducer"


def test_folding_keeps_digits_because_some_roles_have_them():
    assert policy.role_key("8-Bit") == "8bit"


# ---- role_weight: the fallback, and everything that must sit under it ----


def test_an_unlisted_role_is_assumed_to_be_an_instrument():
    """65 of the 124 role tokens in the Drexler corpus are in no table here,
    and nearly all are genuine instruments. The fallback is the design."""
    assert policy.role_weight("Berimbau") == policy.INSTRUMENT_WEIGHT
    assert policy.role_weight("Theremin") == policy.INSTRUMENT_WEIGHT


def test_no_role_at_all_also_falls_back():
    assert policy.role_weight(None) == policy.INSTRUMENT_WEIGHT
    assert policy.role_weight("") == policy.INSTRUMENT_WEIGHT


@pytest.mark.parametrize("role", [
    "Mastered by", "MasteringEngineer", "Masterer",      # 0.15, an industry service
    "Written-by", "Composer", "Lyricist",                # 0.30, a song not a session
    "Executive Producer",                                # 0.40, money not sound
    "MainArtist", "FeaturedArtist", "AssociatedPerformer",  # 0.25, a billing line
    "Assistant Engineer", "StudioPersonnel",             # 0.20
    "Performer",                                         # 0.40
])
def test_the_roles_the_union_exists_to_hold_down_stay_held_down(role):
    """The file's docstring: nine spellings diverged between the two old copies,
    "always upward, always for the credits that deserve the least weight". A
    regression here is a key going missing, which looks like nothing and scores
    0.8 -- so the assertion is against the fallback, not against a literal."""
    assert policy.role_weight(role) < policy.INSTRUMENT_WEIGHT


def test_a_producer_outscores_an_instrument_and_mastering_scores_least():
    assert policy.role_weight("Producer") == 1.0
    assert policy.role_weight("Producer") > policy.INSTRUMENT_WEIGHT
    assert policy.role_weight("Mastered by") == min(
        policy.role_weight(r) for r in policy.ROLE_WEIGHTS)


def test_the_extra_table_wins_where_it_overlaps_and_adds_where_it_does_not():
    """EXTRA_WEIGHTS was added after --list-roles showed StudioPersonnel
    scoring as an instrument. Its keys are pre-folded, so a non-folded key added
    there would silently never match -- hence asserting through role_weight."""
    assert policy.role_weight("StudioPersonnel") == 0.2
    assert policy.role_weight("Orchestra") == 0.7
    assert policy.role_weight("Choir") == 0.6


def test_the_gate_sits_between_mastering_and_an_assistant_engineer():
    """MIN_ROLE_WEIGHT's whole calibration, as one assertion: it drops the
    masterers for free and keeps an assistant engineer on the boundary."""
    assert policy.role_weight("Mastered by") < policy.MIN_ROLE_WEIGHT
    assert policy.role_weight("Assistant Engineer") == policy.MIN_ROLE_WEIGHT


# ---- role_class: the collaboration question ------------------------------


@pytest.mark.parametrize("role,expected", [
    ("Producer", "production"),
    ("Co- Producer", "production"),
    ("Mixed by", "engineering"),          # Discogs' spelling
    ("MixingEngineer", "engineering"),    # Qobuz's
    ("MasteringEngineer", "engineering"),
    ("Composer", "writing"),
    ("Arranger", "writing"),              # arrangement files under writing HERE
    ("MainArtist", "billing"),
    ("Performer", "billing"),             # a billing line, not a session
])
def test_role_class_folds_both_vocabularies_onto_one_class(role, expected):
    assert policy.role_class(role) == expected


def test_an_unrecognised_role_is_a_performance_credit():
    assert policy.role_class("Bandoneon") == "performance"
    assert policy.role_class("Timpani") == "performance"


def test_performance_is_the_default_and_never_an_entry():
    """CLASS_NAMES advertises five classes but ROLE_CLASS maps to four: nothing
    is classed `performance` by the table, only by falling off it. Worth pinning
    because --roles accepts `performance` and it has to keep meaning something."""
    assert "performance" in policy.CLASS_NAMES
    assert "performance" not in set(policy.ROLE_CLASS.values())
    assert set(policy.ROLE_CLASS.values()) | {"performance"} == policy.CLASS_NAMES


def test_the_weak_classes_are_the_referral_ones_not_the_quiet_ones():
    """45% of the Drexler pool was dropped by this set. Engineers are weak under
    neither vocabulary -- a mastering engineer is a weak SIGNAL, handled by
    role_weight, which is a different axis from being a non-relationship."""
    assert policy.WEAK_CLASSES == {"writing", "billing"}
    assert policy.role_class("MasteringEngineer") not in policy.WEAK_CLASSES


# ---- selectivity: the bands ----------------------------------------------


@pytest.mark.parametrize("total,score,band", [
    (0, 0.5, "unknown"),        # not "selective": absence is not a small number
    (-1, 0.5, "unknown"),
    (1, 1.0, "selective"),
    (45, 1.0, "selective"),     # Carles Campi Campon
    (60, 1.0, "selective"),
    (61, 0.6, "moderate"),
    (200, 0.6, "moderate"),
    (201, 0.3, "prolific"),
    (600, 0.3, "prolific"),
    (601, 0.1, "service"),
    (1070, 0.1, "service"),     # Fred Kevorkian, every genre there is
])
def test_the_selectivity_bands_and_their_edges(total, score, band):
    assert policy.selectivity(total) == (score, band)


def test_an_unknown_count_is_not_scored_as_the_best_case():
    """The trap in the band table: 0 releases means Discogs did not say, and
    scoring that as `selective` would reward every person the lookup failed on."""
    unknown, _ = policy.selectivity(0)
    best, _ = policy.selectivity(1)
    assert unknown < best


def test_selectivity_never_rises_with_the_release_count():
    counts = [0, 1, 60, 61, 200, 201, 600, 601, 5000]
    scores = [policy.selectivity(n)[0] for n in counts[1:]]
    assert scores == sorted(scores, reverse=True)


# ---- person_role_weight: what gates before a request is spent ------------


def test_a_person_is_what_their_top_role_says_they_are():
    """resolve_qobuz writes roles most-frequent-first, so [0] is "what they
    mainly are". Someone who mastered ten albums and once played guitar is a
    mastering engineer."""
    assert policy.person_role_weight({"roles": ["MasteringEngineer", "Guitar"]}) == 0.15
    assert policy.person_role_weight({"roles": ["Guitar", "MasteringEngineer"]}) == 0.8


def test_a_person_with_no_roles_scores_zero_not_the_instrument_fallback():
    """The asymmetry worth knowing: role_weight(None) is 0.8, because an unnamed
    role is probably an instrument. person_role_weight({}) is 0.0, because no
    roles at all is no evidence -- and 0.8 would sail through MIN_ROLE_WEIGHT."""
    assert policy.person_role_weight({}) == 0.0
    assert policy.person_role_weight({"roles": []}) == 0.0
    assert policy.person_role_weight({"roles": None}) == 0.0
    assert policy.person_role_weight({}) < policy.MIN_ROLE_WEIGHT


def test_person_roles_copies_rather_than_aliasing_the_caller():
    """It is read on every person in a 7,860-row pool; returning the stored list
    would let a caller's sort reorder the data underneath it."""
    person = {"roles": ["Producer", "Guitar"]}
    got = policy.person_roles(person)
    got.append("Bass")
    assert person["roles"] == ["Producer", "Guitar"]


def test_a_missing_roles_key_is_an_empty_list_not_a_crash():
    assert policy.person_roles({}) == []
    assert policy.person_roles({"roles": None}) == []


# ---- classify_roles: the COARSER discovery vocabulary -------------------


def test_discovery_folds_engineering_into_production():
    """This is the disagreement todo.md records: discovery_*.json and
    watchlist.json carry no `engineering` class at all. Unifying the two
    vocabularies rewrites that written data, so it must be a decision rather
    than a tidy-up -- and until it is made, this test is what notices."""
    assert policy.classify_roles(["Mixing Engineer"]) == ["production"]
    assert policy.classify_roles(["Mastering Engineer"]) == ["production"]
    assert policy.role_class("Mixing Engineer") == "engineering"
    assert "engineering" not in set(policy.DISCOVERY_ROLE_CLASSES.values())


def test_discovery_does_not_fold_spellings_the_way_role_class_does():
    """Lowercase lookup only, no role_key(). "CoProducer" therefore misses the
    table and lands on `performance`. Documented in policy.py as preserving the
    existing output exactly -- so it is a known defect, pinned, not endorsed."""
    assert policy.classify_roles(["Co- Producer"]) == ["production"]
    assert policy.classify_roles(["CoProducer"]) == ["performance"]
    assert policy.role_class("CoProducer") == "production"


def test_classify_returns_each_class_once_in_a_stable_order():
    assert policy.classify_roles(
        ["Producer", "Guitar", "Composer", "MainArtist", "Producer"]
    ) == ["billing", "performance", "production", "writing"]


def test_classifying_nothing_yields_nothing():
    assert policy.classify_roles([]) == []


def test_every_discovery_class_is_a_class_the_rest_of_the_project_knows():
    """The vocabularies may disagree about which role goes where; they may not
    disagree about what the class names ARE, or load.py's person_classes table
    holds two incompatible sets of strings."""
    assert set(policy.DISCOVERY_ROLE_CLASSES.values()) <= policy.CLASS_NAMES


# ---- writing_tier: three outcomes, not two ------------------------------


def test_a_composer_credit_is_unambiguous_authorship():
    assert policy.writing_tier({"composer"}, others_compose=True) == "authored"
    assert policy.writing_tier({"writtenby"}, others_compose=True) == "authored"


def test_lyrics_against_someone_elses_music_is_flagged_never_dropped():
    """Shakira's "Waka Waka": Drexler holds Lyricist, three others hold Composer.
    He wrote the Spanish words for someone else's song. Credits alone cannot
    tell that from a real words-and-music co-write, so it gets its own tier."""
    assert policy.writing_tier({"lyricist"}, others_compose=True) == "lyrics_only"


def test_lyrics_with_nobody_else_composing_is_authorship():
    """Nobody else is credited with the music, so the lyricist is the author of
    the song as registered -- there is no other claim to be second to."""
    assert policy.writing_tier({"lyricist"}, others_compose=False) == "authored"


def test_an_explicit_adapter_credit_admits_the_song_came_from_elsewhere():
    assert policy.writing_tier({"adapter"}, others_compose=False) == "adaptation"
    assert policy.writing_tier({"translator"}, others_compose=True) == "adaptation"


def test_composing_outranks_adapting_when_someone_holds_both():
    """Order matters in the function: the adaptation test excludes composers, so
    someone who adapted one song and composed this one is not demoted."""
    assert policy.writing_tier({"adapter", "composer"}, others_compose=True) == "authored"


def test_composerlyricist_is_read_as_composing_not_as_lyrics_only():
    """It sits in both COMPOSER_ROLES and LYRIC_ROLES, so which branch runs
    first decides the answer. Composer first is correct, and silently fragile."""
    assert "composerlyricist" in policy.COMPOSER_ROLES & policy.LYRIC_ROLES
    assert policy.writing_tier({"composerlyricist"}, others_compose=True) == "authored"


@pytest.mark.parametrize("mine", [set(), {"performer"}, {"vocals"}, {"guitar"}])
def test_no_writing_role_is_no_claim_at_all(mine):
    assert policy.writing_tier(mine, others_compose=True) == "none"


def test_every_tier_is_reachable_and_they_are_the_only_four():
    """A fifth string appearing here would land in song_tier_votes as a silent
    new category, which no reader of the store would be expecting."""
    tiers = {
        policy.writing_tier({"composer"}, True),
        policy.writing_tier({"lyricist"}, True),
        policy.writing_tier({"adapter"}, True),
        policy.writing_tier(set(), True),
    }
    assert tiers == {"authored", "lyrics_only", "adaptation", "none"}


def test_the_writing_vocabulary_is_the_union_of_its_three_parts():
    assert policy.WRITING_ROLES == (
        policy.COMPOSER_ROLES | policy.LYRIC_ROLES | policy.ADAPTATION_ROLES)


def test_the_writing_roles_are_folded_keys_because_that_is_how_they_are_queried():
    """writing.py looks these up with role_key() output. An entry with a space or
    a capital in it could never match, and would fail silently as a tier of
    `none` -- so the table is asserted to be in the form it is read in."""
    for role in policy.WRITING_ROLES | policy.PERFORMANCE_ROLES:
        assert role == policy.role_key(role), role


def test_a_writing_role_is_never_also_a_performance_role():
    """writing.py asks both questions of one credit set. An overlap would make a
    song simultaneously theirs-to-have-written and theirs-to-have-played."""
    assert not policy.WRITING_ROLES & policy.PERFORMANCE_ROLES


# ---- the remaining constants, pinned where a reader depends on them ------


def test_the_title_similarity_floor_stays_above_the_pair_it_was_set_for():
    """At 0.92, "todo se transforma" and "todo se complica" (0.65) stay apart,
    which they must -- they are different Drexler songs."""
    import difflib
    pair = difflib.SequenceMatcher(
        None, "todo se transforma", "todo se complica").ratio()
    assert pair < policy.TITLE_SIMILARITY
    typo = difflib.SequenceMatcher(
        None, "12 segundos de oscuridad", "12 segundos de orcuridad").ratio()
    assert typo >= policy.TITLE_SIMILARITY


def test_the_title_aliases_are_stored_as_folded_keys_on_both_sides():
    """Both keys and values are title_key() output -- accent-stripped,
    punctuation-free, lowercase. An accented value would never match the folded
    title it is meant to merge into, and the alias would do nothing."""
    for source, target in policy.TITLE_ALIASES.items():
        assert source == source.lower().strip(), source
        assert target == target.lower().strip(), target
        assert not any(ch in source for ch in ".,'´"), source
        assert source != target, source


def test_no_alias_points_at_another_alias():
    """One hop only: resolution is a single dict lookup, so a chain would leave
    half the titles unmerged depending on which spelling arrived first."""
    for target in policy.TITLE_ALIASES.values():
        assert target not in policy.TITLE_ALIASES, target


def test_the_writing_share_floor_clears_the_mislabelling_noise_band():
    """Not zero, because Qobuz prints "Stephen Marcussen, Composer" on 15 of his
    first 100 tracks. 0.35 sits in the gap between his 0.15 and Drexler's 0.97."""
    assert 0.15 < policy.MIN_WRITING_SHARE < 0.97


def test_the_covers_mill_hints_are_lowercase_substrings():
    """Matched as substrings against a normalised name, so an upper-case or
    padded hint would never fire."""
    for hint in policy.COVERS_MILL_HINTS:
        assert hint == hint.lower().strip(), hint


# ---- the watchlist bands ------------------------------------------------


def test_the_measured_artists_land_where_they_were_judged_to():
    """The calibration set, confirmed by hand on the 2026-05 export."""
    assert policy.band(66, 23, 3267) == "core"       # Drexler
    assert policy.band(60, 16, 52) == "core"         # Sparklehorse, on few plays
    assert policy.band(73, 3, 22) == "lapsed"        # Radiohead
    assert policy.band(58, 3, 7) == "lapsed"         # Mogwai
    assert policy.band(47, 7, 80) == "lapsed"        # Interpol
    assert policy.band(3, 3, 335) == "emerging"      # Milo j
    assert policy.band(1, 1, 2) == "thin"            # Camilo, two plays


def test_the_floor_sits_in_the_measured_gap():
    """Nothing judged current was below 12 recent months; nothing cooled was above 7."""
    assert 7 < policy.M24_FLOOR <= 12


def test_a_short_history_is_judged_against_itself():
    """An artist found four months ago cannot have ten recent months, so the
    currency test scales -- otherwise every new artist is thin forever."""
    assert policy.band(4, 4, 500) == "emerging"
    assert policy.band(4, 1, 500) == "thin"


def test_a_short_history_still_has_to_clear_the_plays_floor():
    """What the scaling let in: 2,006 artists were emerging, Camilo among them
    on two plays. The floor is what makes the candidate list reviewable."""
    assert policy.band(3, 3, policy.EMERGING_PLAYS) == "emerging"
    assert policy.band(3, 3, policy.EMERGING_PLAYS - 1) == "thin"


def test_the_plays_floor_does_not_apply_to_a_deep_history():
    """Sparklehorse: 60 lifetime months, 52 recent plays. Months carry it, and
    a second constraint would demote him on no evidence."""
    assert policy.band(60, 16, 1) == "core"
    assert policy.band(60, 2, 1) == "lapsed"


def test_depth_alone_never_makes_an_artist_core():
    """The whole point: 2,542 Radiohead plays over 73 months do not outvote
    three active months in two years."""
    assert policy.band(100, 0, 9999) == "lapsed"


def test_recency_alone_never_makes_an_artist_core():
    """Below DEEP_FLOOR it is emerging, which is watched but not established."""
    assert policy.band(policy.DEEP_FLOOR - 1, 20, 500) == "emerging"
    assert policy.band(policy.DEEP_FLOOR, 20, 500) == "core"


def test_every_band_is_one_of_the_four_names():
    for months in range(0, 60, 7):
        for recent in range(0, months + 1, 3):
            for plays in (0, 50, 5000):
                assert policy.band(months, recent, plays) in {
                    "core", "lapsed", "emerging", "thin"}


def test_an_intense_lapse_is_flagged_but_still_lapsed():
    """Omar: 5 active months, 163 plays inside them, 33 a month. The flag says
    look again; it does not change the verdict."""
    assert policy.band(50, 5, 163) == "lapsed"
    assert policy.burst(5, 163) is True


def test_a_steady_trickle_is_not_a_burst():
    """Interpol was judged cooled by hand on 6 of the last 6 months at 11 a
    month. Every promotion rule tried also promoted him, which is why this is
    a flag on an axis of its own."""
    assert policy.burst(7, 80) is False
    assert policy.burst(3, 22) is False      # Radiohead
    assert policy.burst(3, 7) is False       # Mogwai


def test_the_burst_rate_is_per_active_month_not_per_month_of_the_window():
    """Otherwise a binge in two months reads the same as a trickle over twenty."""
    assert policy.burst(2, 2 * policy.BURST_RATE) is True
    assert policy.burst(20, 2 * policy.BURST_RATE) is False


def test_nothing_recent_cannot_burst():
    """Guards the division, and says the right thing: no recent plays, no doubt."""
    assert policy.burst(0, 0) is False
    assert policy.burst(0, 500) is False


# ---- match plausibility -------------------------------------------------


def test_a_clean_row_keeps_its_score():
    assert policy.match_confidence([]) == 1.0
    assert policy.ranked_score(0.8, []) == 0.8
    assert policy.ranked_score(0.8, None) == 0.8


def test_a_single_token_match_is_demoted_not_deleted():
    """"Morgan" carries 323 releases at 1.00 because the score comes from the
    referrer. It keeps its provenance and loses the top of the list."""
    assert policy.ranked_score(1.0, ["single_token_name"]) == 0.1


def test_the_penalty_puts_the_worst_flagged_row_below_the_best_clean_one():
    """0.80 is the highest clean score in the committed pools."""
    assert policy.ranked_score(1.0, ["single_token_name"]) < 0.80


def test_a_strong_flagged_match_still_outranks_a_weak_clean_one():
    """A penalty, not a drop: the flag is suspicion, never proof."""
    assert policy.ranked_score(1.0, ["single_token_name"]) > policy.ranked_score(0.05, [])


def test_an_unknown_flag_is_not_silently_a_penalty():
    """A flag nobody has ruled on must not change an order by accident."""
    assert policy.match_confidence(["covers_mill"]) == 1.0


def test_doubts_compound():
    assert policy.match_confidence(["single_token_name", "single_token_name"]) == 0.1 ** 2


# ---- album provenance ---------------------------------------------------


def test_the_seed_billed_throughout_owns_the_record():
    assert policy.album_provenance(11, 11) == "own"


def test_the_seed_billed_on_nothing_is_a_guest():
    """15 of Drexler's 62 albums, 3 of Perez Cruz's 44."""
    assert policy.album_provenance(0, 1) == "guest"


def test_half_the_record_is_enough_to_own_it():
    """The floor itself, stated. No album in either corpus is between 0 and 1,
    so this is the only place the value is visible."""
    assert policy.OWN_ALBUM_MAIN_SHARE == 0.5
    assert policy.album_provenance(5, 10) == "own"
    assert policy.album_provenance(4, 10) == "guest"


def test_one_track_of_twenty_is_a_compilation():
    assert policy.album_provenance(1, 20) == "guest"


def test_nobody_billed_is_unknown_not_guest():
    """Guards the division, and says the right thing: no billing, no verdict."""
    assert policy.album_provenance(0, 0) == "unknown"
    assert policy.album_provenance(3, 0) == "unknown"


# ---- pool filters -------------------------------------------------------


def test_the_three_filters_together_keep_a_side_credit_from_a_player():
    """The shape of the 291: Qobuz-native, somebody else's record, reached
    through a musician. Borja Barrueta drumming on a Juanfe Perez record."""
    assert policy.shortlisted("qobuz", False, ["Drums"]) is True


def test_the_discogs_path_is_excluded_whatever_else_is_true():
    """81% of the rows and every junk row traced to it, so this cut is widest
    and is kept separate from the other two."""
    assert policy.shortlisted("discogs", False, ["Producer"]) is False


def test_the_persons_own_record_is_not_a_credit_they_shaped():
    """5,862 of 7,860 rows. The thesis is "they made their mark on somebody
    else's record"."""
    assert policy.shortlisted("qobuz", True, ["Producer"]) is False


def test_an_engineering_referral_is_dropped():
    """73% of the Discogs pool arrives through mixing. A mixing credit is an
    industrial service, which ROLE_WEIGHTS has scored at 0.5 all along."""
    assert policy.shortlisted("qobuz", False, ["Mixed by"]) is False
    assert policy.musical_referral(["Mastering Engineer"]) is False


def test_a_writing_or_billing_referral_is_dropped_too():
    """REFERRAL_CLASSES excludes both WEAK_CLASSES, so a cover source and a
    billing line do not refer anything."""
    assert policy.musical_referral(["Composer"]) is False
    assert policy.musical_referral(["MainArtist"]) is False


def test_one_musical_role_is_enough_among_several():
    """"Any", not "all": 815 rows mix a kept class with a dropped one, and a
    producer who also engineered was still chosen for how they sound."""
    assert policy.musical_referral(["Producer", "Mixed by"]) is True


def test_an_unrecognised_role_is_an_instrument_and_so_a_musical_referral():
    """role_class's default. Berimbau and Wurlitzer are in no table, and 65 of
    the corpus's 124 role tokens are like that."""
    assert policy.musical_referral(["Berimbau"]) is True


def test_no_referring_role_at_all_refers_nothing():
    assert policy.musical_referral([]) is False
    assert policy.musical_referral(None) is False
    assert policy.shortlisted("qobuz", False, []) is False


# ---- the cap ------------------------------------------------------------


def row(via, score):
    return {"via": via, "score": score}


def test_two_per_referrer_is_the_cap():
    """The written value. 2 is where the top 20 stops being one person without
    flattening the list to one row each."""
    assert policy.MAX_PER_REFERRER == 2


def test_the_third_row_from_one_referrer_is_dropped():
    rows = [row("Campodónico", 0.7), row("Campodónico", 0.7), row("Campodónico", 0.7),
            row("Barrueta", 0.8)]
    kept = policy.cap_per_referrer(rows, lambda r: r["via"])
    assert [r["via"] for r in kept] == ["Campodónico", "Campodónico", "Barrueta"]


def test_the_order_in_is_the_order_out():
    """It thins, it never reorders: the caller has already decided what best
    means, and the score is not consulted here at all."""
    rows = [row("a", 0.1), row("b", 0.9), row("a", 0.2)]
    assert policy.cap_per_referrer(rows, lambda r: r["via"]) == rows


def test_the_rows_kept_are_the_first_ones_offered():
    """Which is why the caller sorts first -- cap_per_referrer keeps the two
    best only because the two best arrived first."""
    rows = [row("a", 0.9), row("a", 0.5), row("a", 0.1)]
    kept = policy.cap_per_referrer(rows, lambda r: r["via"])
    assert [r["score"] for r in kept] == [0.9, 0.5]


def test_a_cap_of_one_keeps_one_each():
    rows = [row("a", 1), row("a", 1), row("b", 1)]
    assert len(policy.cap_per_referrer(rows, lambda r: r["via"], limit=1)) == 2


def test_an_empty_list_caps_to_an_empty_list():
    assert policy.cap_per_referrer([], lambda r: r["via"]) == []


def test_referrers_that_are_none_are_one_group_not_many():
    """via_through is NULL on every Qobuz-path row, which is exactly why the
    store caps on via_name instead: keyed on the NULL, the whole shortlist
    would be one referrer and the cap would leave two rows in total."""
    rows = [row(None, 1), row(None, 1), row(None, 1)]
    assert len(policy.cap_per_referrer(rows, lambda r: r["via"])) == 2
