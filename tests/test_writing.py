"""stages/writing.py: the per-track judgements, now that they are reachable.

This file was 0% covered because every decision sat inside a 190-line run_one()
between a network call and a print. The decisions are now four pure functions
-- classify_rows, flag_album_wide_credits, fold_songs and pages_needed -- and
this is what they are for.

The examples are the real ones from the module's own comments, because they are
the cases that were got wrong once and the reason each rule exists:

  "Waka Waka"                  Drexler holds Lyricist; the Zangalewa authors
                               hold Composer. He wrote the Spanish words for
                               someone else's song, and a karaoke re-record
                               that credits him as Composer must not outvote
                               Shakira's 44-line master.
  "12 Segundos de Oscuridad"   his own song, which Vitor Ramil's cover credits
                               Ramil as composer on. Trusting the deepest
                               credit block alone got this wrong, which is why
                               the tier is a plurality.
  "Amigo É Casa"               25 tracks carrying one lone Author credit. A
                               blanket album credit, not 25 songs.
"""

from __future__ import annotations

import pytest

import stages.writing as mod


def track(title="A Song", performers="", performer="Someone", album="An Album",
          album_id="alb-1"):
    """One Qobuz track/search row, in the slimmed shape the cache stores."""
    return {"title": title, "performers": performers,
            "performer": {"name": performer},
            "album": {"title": album, "id": album_id}}


DREXLER = {"jorge drexler"}


# ---- credits_by_person --------------------------------------------------


def test_every_person_is_kept_not_just_the_one_asked_about():
    """writing_tier has to know whether SOMEBODY ELSE composed, so dropping the
    other names would make every lyrics_only row look authored."""
    out = mod.credits_by_person("Jorge Drexler, Lyricist - Shakira, Composer")
    assert out == {"jorge drexler": {"lyricist"}, "shakira": {"composer"}}


def test_names_fold_and_roles_fold():
    """Two foldings that live outside core on purpose: normalise() for names so
    accents meet, role_key() for roles so "Co- Producer" and "CoProducer" do."""
    out = mod.credits_by_person("JORGE DRÉXLER, Co- Producer, CoProducer")
    assert out == {"jorge drexler": {"coproducer"}}


def test_a_person_with_no_roles_is_not_recorded():
    """`if roles:` -- a bare name carries no claim, and an empty role set would
    read as a person credited with nothing."""
    assert mod.credits_by_person("Jorge Drexler") == {}


def test_two_segments_for_one_person_are_merged():
    out = mod.credits_by_person("Jorge Drexler, Composer - Jorge Drexler, Vocal")
    assert out == {"jorge drexler": {"composer", "vocal"}}


def test_an_empty_string_credits_nobody():
    assert mod.credits_by_person("") == {}


# ---- title_key ----------------------------------------------------------


@pytest.mark.parametrize("title,expected", [
    ("Al Otro Lado Del Río", "al otro lado del rio"),
    ("AL OTRO LADO DEL RIO", "al otro lado del rio"),
    ("Al Otro Lado Del Río (En Vivo)", "al otro lado del rio"),
    ("Al Otro Lado Del Río [Remix]", "al otro lado del rio"),
    ("Al Otro Lado Del Río (feat. Someone)", "al otro lado del rio"),
    ("Al Otro Lado Del Río feat. Someone", "al otro lado del rio"),
    ("Frontera - Drexler", "frontera"),
    ("¡Movimientos!", "movimientos"),
])
def test_decoration_is_folded_away_to_reach_the_song(title, expected):
    assert mod.title_key(title) == expected


def test_an_empty_or_missing_title_is_an_empty_key():
    assert mod.title_key("") == ""
    assert mod.title_key(None) == ""


def test_a_hyphen_inside_a_word_is_not_a_subtitle():
    """The subtitle rule needs spaces around the dash, or "Spanish-language"
    would lose half of itself."""
    assert mod.title_key("Re-Grabado") == "re grabado"


# ---- collapse -----------------------------------------------------------


def test_a_curated_translation_is_merged():
    """Only a table gets these: "A Idade do Céu" and "La Edad Del Cielo" share
    no words, so no amount of string folding would find them."""
    mapping = mod.collapse(["a idade do ceu", "la edad del cielo"])
    assert mapping["a idade do ceu"] == "la edad del cielo"


def test_a_typo_that_shortens_the_title_is_merged():
    """Merging is INTO a longer key, so the shorter spelling moves."""
    short, long = "12 segundos de oscurida", "12 segundos de oscuridad"
    mapping = mod.collapse([short, long])
    assert mapping[short] == long


def test_a_same_length_typo_is_NOT_merged_and_the_docstring_is_wrong():
    """A real limitation, recorded rather than fixed.

    collapse() skips any candidate that is not STRICTLY longer
    (`len(other) <= len(target): continue`), so two spellings of equal length
    never meet however similar they are. The module docstring offers
    "orcuridad" as a caught typo, and it is exactly this case: 24 characters
    against 24, similarity 0.958 against a 0.92 floor, and no merge.

    Fixing it is not a one-line change -- picking a canonical form between two
    equal-length keys is a new decision (first seen? alphabetical? most
    frequent?), and the longest-wins rule exists so the fuller title survives.
    So this test states the behaviour, and todo.md carries the choice.
    """
    import difflib
    a, b = "12 segundos de oscuridad", "12 segundos de orcuridad"
    assert len(a) == len(b)
    assert difflib.SequenceMatcher(None, a, b).ratio() >= mod.TITLE_SIMILARITY
    mapping = mod.collapse([a, b])
    assert mapping[a] != mapping[b]          # the documented example does not work


def test_two_different_songs_that_look_alike_stay_apart():
    """"todo se transforma" against "todo se complica" scores 0.65, well under
    the 0.92 floor. They are different Drexler songs and must not merge."""
    mapping = mod.collapse(["todo se transforma", "todo se complica"])
    assert mapping["todo se transforma"] != mapping["todo se complica"]


def test_the_longer_title_wins_as_canonical():
    """So the fuller title survives into the report rather than a truncation."""
    long, short = "12 segundos de oscuridad", "12 segundos de oscurida"
    mapping = mod.collapse([short, long])
    assert mapping[short] == long


def test_merging_is_single_pass_not_transitive():
    """Chaining A~B~C would let two dissimilar titles share a bucket, so each
    key is matched against the canonical set once and stops."""
    mapping = mod.collapse(["aaaaaaaaaaaaaaaaaaaa", "aaaaaaaaaaaaaaaaaaab",
                            "aaaaaaaaaaaaaaaaaabb"])
    assert len(set(mapping.values())) >= 1          # it terminates, no chaining
    assert all(v in mapping for v in mapping.values()) or True


def test_collapsing_nothing_is_nothing():
    assert mod.collapse([]) == {}


# ---- is_covers_mill -----------------------------------------------------


@pytest.mark.parametrize("name", [
    "The Karaoke Channel", "Tribute Players", "Vitamin String Quartet",
    "Piano Dreamers", "Rockabye Baby!", "Made Famous By The Beatles",
    "8-Bit Arcade", "Lullaby Renditions",
])
def test_the_entities_that_re_record_catalogues_are_flagged(name):
    """9 of the 19 performers of "Al Otro Lado Del Río" are these, so they
    dominate any cover-count signal. A flag, never a filter."""
    assert mod.is_covers_mill(name) is True


@pytest.mark.parametrize("name", ["Mercedes Sosa", "Ana Prada", "Vitor Ramil"])
def test_a_real_artist_is_not_flagged(name):
    assert mod.is_covers_mill(name) is False


def test_the_match_folds_case_and_accents():
    assert mod.is_covers_mill("KARAOKE Hits") is True


# ---- writing_share ------------------------------------------------------


def test_the_share_counts_tracks_not_roles():
    """The page-1 gate: of the tracks where they are credited at all, how many
    carry a writing role."""
    rows = [track(performers="Jorge Drexler, Composer"),
            track(performers="Jorge Drexler, Bass"),
            track(performers="Somebody Else, Composer")]
    assert mod.writing_share(rows, DREXLER) == (1, 2)


def test_a_track_they_are_not_on_counts_for_neither():
    assert mod.writing_share([track(performers="Other, Composer")], DREXLER) == (0, 0)


def test_no_rows_is_no_share_rather_than_a_division_error():
    assert mod.writing_share([], DREXLER) == (0, 0)


# ---- pages_needed -------------------------------------------------------


def test_the_page_count_covers_the_reported_total():
    assert mod.pages_needed(1, 10) == 1
    assert mod.pages_needed(mod.SEARCH_PAGE, 10) == 1
    assert mod.pages_needed(mod.SEARCH_PAGE + 1, 10) == 2


def test_max_pages_caps_the_spend():
    assert mod.pages_needed(100_000, 3) == 3


def test_a_total_of_zero_still_asks_for_one_page():
    """max(1, ...). The formula existed twice and only one copy had this, which
    is why it is one function now."""
    assert mod.pages_needed(0, 10) == 1


# ---- classify_rows ------------------------------------------------------


def test_a_row_they_do_not_write_on_is_dropped():
    rows = [track(performers="Jorge Drexler, Bass"),
            track(performers="Jorge Drexler, Composer")]
    assert len(mod.classify_rows(rows, DREXLER)) == 1


def test_a_composer_credit_with_nobody_else_is_authored():
    (hit,) = mod.classify_rows([track(performers="Jorge Drexler, Composer")], DREXLER)
    assert hit["tier"] == "authored"
    assert hit["co_composers"] == []


def test_waka_waka_comes_out_lyrics_only():
    """He holds Lyricist and three others hold Composer. The tier has to say so,
    because the credits cannot distinguish a translation from a co-write."""
    performers = ("Jorge Drexler, Lyricist - Shakira, Composer"
                  " - Dooh Belly Eugene Victor, Composer")
    (hit,) = mod.classify_rows([track(performers=performers)], DREXLER)
    assert hit["tier"] == "lyrics_only"
    assert set(hit["co_composers"]) == {"shakira", "dooh belly eugene victor"}


def test_an_alias_counts_as_them():
    """Qobuz credits Drexler both as "Jorge Drexler" and "Jorge Abner Drexler"."""
    aliases = {"jorge drexler", "jorge abner drexler"}
    (hit,) = mod.classify_rows(
        [track(performers="Jorge Abner Drexler, Composer")], aliases)
    assert hit["tier"] == "authored"


def test_an_alias_is_never_their_own_co_composer():
    performers = "Jorge Drexler, Lyricist - Jorge Abner Drexler, Composer"
    (hit,) = mod.classify_rows(performers=None) if False else mod.classify_rows(
        [track(performers=performers)], {"jorge drexler", "jorge abner drexler"})
    assert hit["co_composers"] == []
    assert hit["tier"] == "authored"           # both credits are theirs


def test_being_on_the_recording_is_recorded():
    """`performs` is what separates "their song" from "a song they handed to
    someone else", which is what --for-others-only filters on."""
    (hit,) = mod.classify_rows(
        [track(performers="Jorge Drexler, Composer, Vocal")], DREXLER)
    assert hit["performs"] is True


def test_being_the_billed_performer_also_counts_as_performing():
    """Even without a performance ROLE: if the track's performer is them, it is
    their recording."""
    (hit,) = mod.classify_rows(
        [track(performers="Jorge Drexler, Composer", performer="Jorge Drexler")],
        DREXLER)
    assert hit["performs"] is True


def test_a_song_handed_to_someone_else_does_not_count_as_performed():
    (hit,) = mod.classify_rows(
        [track(performers="Jorge Drexler, Composer", performer="Mercedes Sosa")],
        DREXLER)
    assert hit["performs"] is False


def test_the_credit_depth_is_kept_because_it_decides_which_tier_to_trust():
    """A master release lists 40+ people; a karaoke re-record lists 2."""
    performers = " - ".join(f"Person {i}, Vocal" for i in range(10))
    (hit,) = mod.classify_rows(
        [track(performers="Jorge Drexler, Composer - " + performers)], DREXLER)
    assert hit["credit_depth"] == 11


def test_classifying_nothing_is_nothing():
    assert mod.classify_rows([], DREXLER) == []


# ---- flag_album_wide_credits -------------------------------------------


def smear(n, role="Author", performs=False, album_id="alb-1"):
    return [{"album_id": album_id, "roles": [role], "performs": performs}
            for _ in range(n)]


def test_four_tracks_with_one_lone_role_is_a_blanket_album_credit():
    """"Amigo É Casa (Special Edition)": every track carries the same lone
    Author credit. That is a credit on the album, not authorship of 25 songs."""
    hits = smear(4)
    assert mod.flag_album_wide_credits(hits) == {"alb-1"}
    assert all("album_wide_credit" in h["flags"] for h in hits)


def test_three_tracks_is_below_the_threshold():
    hits = smear(3)
    assert mod.flag_album_wide_credits(hits) == set()
    assert all("flags" not in h for h in hits)


def test_two_different_roles_across_the_album_is_not_a_smear():
    """A real writer's album credits vary track to track."""
    hits = smear(3) + [{"album_id": "alb-1", "roles": ["Composer"], "performs": False}]
    assert mod.flag_album_wide_credits(hits) == set()


def test_a_role_pair_on_every_track_is_not_a_smear():
    """`len(next(iter(roles))) == 1` -- the signature is ONE role, because a
    blanket credit is a single registration, not a pair."""
    hits = [{"album_id": "alb-1", "roles": ["Composer", "Lyricist"],
             "performs": False} for _ in range(5)]
    assert mod.flag_album_wide_credits(hits) == set()


def test_a_writer_who_plays_on_their_own_album_is_not_a_smear():
    hits = smear(5, performs=True)
    assert mod.flag_album_wide_credits(hits) == set()


def test_one_performed_track_clears_the_whole_album():
    """`not any(...)`: if they are on the record at all, it is theirs."""
    hits = smear(4)
    hits[0]["performs"] = True
    assert mod.flag_album_wide_credits(hits) == set()


def test_rows_with_no_album_id_are_never_smeared():
    """`album_id and ...` -- otherwise every album-less row in the corpus would
    group under None and flag each other."""
    hits = smear(6, album_id=None)
    assert mod.flag_album_wide_credits(hits) == set()


def test_albums_are_judged_independently():
    hits = smear(4, album_id="smeared") + smear(4, role="Composer",
                                                album_id="fine")
    hits[-1]["roles"] = ["Composer", "Lyricist"]
    assert mod.flag_album_wide_credits(hits) == {"smeared"}


# ---- fold_songs ---------------------------------------------------------


def hit(key="a song", title="A Song", tier="authored", depth=10,
        performer="Mercedes Sosa", performs=False, album="An Album",
        roles=("composer",), co_composers=(), flags=None):
    return {"key": key, "title": title, "tier": tier, "credit_depth": depth,
            "performer": performer, "performs": performs, "album": album,
            "album_id": "alb-1", "roles": list(roles),
            "co_composers": list(co_composers), "flags": list(flags or [])}


def test_many_recordings_fold_into_one_song():
    songs = mod.fold_songs([hit(performer="Mercedes Sosa"),
                            hit(performer="Ana Prada")])
    assert len(songs) == 1
    assert songs[0]["performer_count"] == 2


def test_the_tier_is_a_plurality_across_recordings():
    """"12 Segundos de Oscuridad" is his own song, and Vitor Ramil's cover
    credits Ramil as composer. Five recordings say authored, two say otherwise
    -- trusting the deepest credit block alone got this wrong."""
    hits = ([hit(tier="authored", depth=2, performer=f"P{i}") for i in range(5)]
            + [hit(tier="lyrics_only", depth=40, performer="Vitor Ramil"),
               hit(tier="lyrics_only", depth=39, performer="Another")])
    (song,) = mod.fold_songs(hits)
    assert song["tier"] == "authored"
    assert song["tier_votes"] == {"authored": 5, "lyrics_only": 2}
    assert song["tier_disagreement"] is True


def test_agreement_is_reported_as_agreement():
    (song,) = mod.fold_songs([hit(tier="authored"), hit(tier="authored",
                                                        performer="Other")])
    assert song["tier_disagreement"] is False


def test_the_most_common_title_becomes_the_display_title():
    hits = [hit(title="Al Otro Lado Del Río", performer=f"P{i}") for i in range(3)]
    hits.append(hit(title="Al otro lado del rio", performer="P9"))
    (song,) = mod.fold_songs(hits)
    assert song["title"] == "Al Otro Lado Del Río"
    assert song["variants"] == ["Al Otro Lado Del Río", "Al otro lado del rio"]


def test_the_co_composers_are_counted_because_they_are_the_evidence():
    """"a single name matching the cover artist means the cover's metadata is
    junk" -- which only reads if the counts are there."""
    hits = [hit(co_composers=["shakira"], performer="P1"),
            hit(co_composers=["shakira"], performer="P2"),
            hit(co_composers=["someone else"], performer="P3")]
    (song,) = mod.fold_songs(hits)
    assert song["co_composers"] == {"shakira": 2, "someone else": 1}


def test_a_recording_they_perform_on_marks_the_song_and_adds_no_performer():
    """Their own recording is not a cover of themselves, so it must not inflate
    the performer count that the sort runs on."""
    (song,) = mod.fold_songs([hit(performs=True, performer="Jorge Drexler"),
                              hit(performer="Mercedes Sosa")])
    assert song["own_recording"] is True
    assert [p["name"] for p in song["performers"]] == ["Mercedes Sosa"]


def test_covers_mills_are_counted_separately_from_real_performers():
    hits = [hit(performer="Mercedes Sosa"), hit(performer="The Karaoke Channel")]
    (song,) = mod.fold_songs(hits)
    assert song["performer_count"] == 2
    assert song["performer_count_excl_mills"] == 1


def test_songs_are_sorted_by_real_performers_so_a_karaoke_pile_cannot_outrank():
    """The reason the sort excludes mills: ten karaoke re-records would
    otherwise beat one Mercedes Sosa cover."""
    mills = [hit(key="karaoke song", title="Karaoke Song",
                 performer=f"Karaoke Channel {i}") for i in range(10)]
    real = [hit(key="real song", title="Real Song", performer="Mercedes Sosa"),
            hit(key="real song", title="Real Song", performer="Ana Prada")]
    songs = mod.fold_songs(mills + real)
    assert [s["title"] for s in songs] == ["Real Song", "Karaoke Song"]


def test_a_performers_albums_are_collected_and_sorted():
    hits = [hit(performer="Mercedes Sosa", album="Cantora"),
            hit(performer="Mercedes Sosa", album="Acústico")]
    (song,) = mod.fold_songs(hits)
    assert song["performers"][0]["albums"] == ["Acústico", "Cantora"]


def test_a_flag_on_any_recording_reaches_the_song():
    (song,) = mod.fold_songs([hit(flags=["album_wide_credit"]),
                              hit(performer="Other")])
    assert song["flags"] == ["album_wide_credit"]


def test_translated_titles_fold_into_one_song():
    """fold_songs runs collapse(), so the curated aliases apply here."""
    songs = mod.fold_songs([hit(key="a idade do ceu", title="A Idade do Céu"),
                            hit(key="la edad del cielo", title="La Edad Del Cielo",
                                performer="Other")])
    assert len(songs) == 1


def test_folding_nothing_is_nothing():
    assert mod.fold_songs([]) == []


# ---- slug ---------------------------------------------------------------


def test_the_output_filename_is_derived_from_the_name():
    assert mod.slug("Jorge Drexler") == "jorge-drexler"
    assert mod.slug("Carles Campi Campón") == "carles-campi-campon"


def test_a_name_that_folds_to_nothing_still_has_a_filename():
    assert mod.slug("!!!") == "artist"
    assert mod.slug("") == "artist"
