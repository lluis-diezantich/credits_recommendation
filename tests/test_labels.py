"""core/labels.py: the judgement the label radar rests on, without a network.

The funnel order is what most of this is about. Each verdict is the reason a
row stopped, and the radar prints those counts as the measurement behind
`--credit`, so a reordering that looks harmless silently moves rows between
categories -- which is exactly what D42's `appearance`/`duplicate` double-count
was.
"""

from __future__ import annotations

import json

import pytest

from core.labels import (
    MAJOR_CATALOGUE,
    Credit,
    credits_by,
    earned,
    family_of,
    fold_editions,
    is_reissue,
    is_remix,
    labels,
    people,
    person_verdict,
    role_key,
    verdict,
    watch_verdict,
)


def test_role_key_folds_the_spellings_qobuz_actually_sends():
    # The three spellings of one role, which is why this function exists:
    # `data/appearances-backfill.md` records `Sampled Artist` and `Beat maker`
    # reaching a printed row because normalise() does not collapse spaces.
    assert role_key("Co- Producer") == role_key("CoProducer") == "coproducer"
    assert role_key("Executive Producer") == role_key("ExecutiveProducer")
    assert role_key("Mixing  Engineer") == "mixingengineer"


@pytest.mark.parametrize(("role", "expected"), [
    ("Producer", "production"),
    ("Co- Producer", "production"),
    ("Executive Producer", "production"),
    ("Mixing Engineer", "engineering"),
    ("Mastering Engineer", "engineering"),
    ("ComposerLyricist", "writing"),
    ("Sampled Artist", "writing"),
    ("FeaturedArtist", "billing"),
    # Not in any table, and genuinely an instrument: core/credits.py measured
    # 65 of 124 tokens in that position, nearly all real.
    ("Berimbau", "performance"),
    ("Spanish Guitar", "performance"),
])
def test_family_of(role, expected):
    assert family_of(role) == expected


def test_credits_by_folds_two_spellings_of_one_person():
    tracks = [
        ("Uno", "Jorge Drexler, MainArtist - Carles Campi Campón, Producer"),
        ("Dos", "Jorge Drexler, MainArtist - Carles Campón, Mixer, Producer"),
        ("Tres", "Somebody Else, Drums"),
    ]
    wanted = {"carles campi campon": "Carles Campi Campón",
              "carles campon": "Carles Campi Campón"}
    found = credits_by(tracks, wanted)
    assert len(found) == 1
    assert found[0].name == "Carles Campi Campón"
    assert found[0].tracks == 2
    assert set(found[0].roles) == {"Producer", "Mixer"}
    assert found[0].families() == {"production", "engineering"}


def test_credits_by_orders_by_tracks_so_the_report_names_the_right_person():
    tracks = [
        ("Uno", "Big Name, Executive Producer - Small Name, Producer"),
        ("Dos", "Small Name, Producer"),
    ]
    wanted = {"big name": "Big Name", "small name": "Small Name"}
    assert [c.name for c in credits_by(tracks, wanted)] == ["Small Name", "Big Name"]


def test_credits_by_is_empty_when_nobody_watched_is_on_it():
    assert credits_by([("Uno", "Nobody, Producer")], {"someone": "Someone"}) == []


def test_credits_by_survives_an_empty_performers_string():
    # Qobuz ships tracks with no credits at all, and a label catalogue is full
    # of them -- this must be an absence, not a crash. core.qobuz.album_tracks
    # is what turns a missing `performers` into "", so "" is the only shape
    # that can reach here and None is not worth typing around.
    assert credits_by([("Uno", ""), ("Dos", "")], {"a": "A"}) == []


PRODUCTION = {"production"}


def test_verdict_prefers_yours_over_every_credit_test():
    # A record billed to an artist you watch is the Friday radar's, whatever
    # the credits say -- otherwise one release prints under two sources.
    credit = Credit(name="A", roles=("Producer",), tracks=3)
    assert verdict({"41620"}, {"41620"}, [credit], PRODUCTION) == "yours"


def test_verdict_absent_when_nobody_is_credited():
    assert verdict({"99"}, {"41620"}, [], PRODUCTION) == "absent"


def test_verdict_writing_is_a_cover_not_a_record_they_made():
    credit = Credit(name="A", roles=("ComposerLyricist",), tracks=1)
    assert verdict({"99"}, {"41620"}, [credit], PRODUCTION) == "writing"


def test_verdict_sideline_is_a_family_this_run_did_not_ask_for():
    credit = Credit(name="A", roles=("Mixing Engineer",), tracks=9)
    assert verdict({"99"}, {"41620"}, [credit], PRODUCTION) == "sideline"
    # ...and the same row is news when the run asks for it.
    assert verdict({"99"}, {"41620"}, [credit], {"engineering"}) == "credit"


def test_verdict_credit_when_one_role_of_several_is_wanted():
    # A producer who also played on it still counts: the families are a set,
    # and requiring every role to match would drop the strongest rows.
    credit = Credit(name="A", roles=("Berimbau", "Producer"), tracks=2)
    assert verdict({"99"}, {"41620"}, [credit], PRODUCTION) == "credit"


def test_fold_editions_keeps_the_earliest_of_two_editions():
    rows = [
        {"id": "hires", "title": "Before The World Blows",
         "release_date_original": "2026-08-28"},
        {"id": "plain", "title": "before the world blows",
         "release_date_original": "2026-08-20"},
        {"id": "other", "title": "Something Else",
         "release_date_original": "2026-08-25"},
    ]
    folded = fold_editions(rows)
    assert {r["id"] for r in folded} == {"plain", "other"}


@pytest.mark.parametrize(("entry", "expected"), [
    ({"id": 1, "name": "Napa", "artists": ["Sílvia Pérez Cruz"], "catalogue": 11}, "watched"),
    ({"id": 2, "name": "Sony", "artists": ["A"], "catalogue": 10000}, "major"),
    ({"id": 3, "name": "Young", "artists": ["A"], "catalogue": 271, "watch": False}, "muted"),
    ({"id": 4, "name": "Jose Gonzalez", "artists": ["José González"], "catalogue": 12,
      "self_release": True}, "self"),
    ({"id": 5, "name": "Mystery", "artists": [], "catalogue": 50}, "thin"),
])
def test_watch_verdict(entry, expected):
    assert watch_verdict(entry) == expected


def test_watch_verdict_puts_the_mute_ahead_of_the_catalogue_size():
    # A mute is yours and a catalogue size is a fact, and the report counts the
    # two separately: a muted major must count as muted, or lifting the mute
    # looks like it would change something.
    entry = {"id": 1, "name": "Sony", "artists": ["A"],
             "catalogue": MAJOR_CATALOGUE + 1, "watch": False}
    assert watch_verdict(entry) == "muted"


def test_labels_counts_what_it_left_out(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({"labels": [
        {"id": 1, "name": "Napa", "artists": ["A"], "catalogue": 11},
        {"id": 2, "name": "Sony", "artists": ["A"], "catalogue": 99999},
        {"id": 3, "name": "Muted", "artists": ["A"], "catalogue": 10, "watch": False},
        {"name": "No id", "artists": ["A"], "catalogue": 10},
    ]}))
    watchlist = labels(path)
    assert watchlist.ids == {1: "Napa"}
    assert watchlist.excluded == {"major": 1, "muted": 1}
    assert watchlist.total == 3
    assert watchlist.report() == {"ids": 1, "entries": 3, "major": 1, "muted": 1}


def test_labels_is_empty_without_a_file(tmp_path):
    assert labels(tmp_path / "nothing.json").ids == {}


def test_labels_degrades_on_an_unreadable_file(tmp_path, capsys):
    path = tmp_path / "labels.json"
    path.write_text("{not json")
    assert labels(path).ids == {}
    assert "ignoring unreadable" in capsys.readouterr().err


def test_people_maps_every_spelling_to_the_one_you_print(tmp_path):
    path = tmp_path / "producers.json"
    path.write_text(json.dumps({"people": [
        {"name": "Carles Campi Campón", "names": ["Campi", "Carles Campón"],
         "albums": 25},
        {"name": "Muted Person", "names": ["Muted"], "albums": 9, "watch": False},
    ]}))
    found = people(path)
    assert found.names["campi"] == "Carles Campi Campón"
    assert found.names["carles campon"] == "Carles Campi Campón"
    assert "muted person" not in found.names
    assert found.excluded == {"muted": 1}
    # One person, three spellings: the report is about people, not spellings.
    assert found.report() == {"kept": 1, "entries": 2, "muted": 1}


@pytest.mark.parametrize(("entry", "expected"), [
    ({"name": "Carles Campi Campón", "albums": 25}, "watched"),
    ({"name": "Carles Campi Campón", "albums": 25, "watch": False}, "muted"),
    # The two that actually sit in the file, and the reason this test exists:
    # either one reports a release whenever a label leaves its credits blank.
    ({"name": "Not Documented", "albums": 7}, "junk"),
    ({"name": "Unknown", "albums": 10}, "junk"),
    # A suffix and a set of initials that came off a split name.
    ({"name": "Jr", "albums": 9}, "junk"),
    ({"name": "KJ", "albums": 2}, "junk"),
    ({"name": "ROSALÍA", "albums": 9}, "yourself"),
    ({"name": "Somebody", "albums": 1}, "thin"),
    ({"name": "Somebody", "albums": 0}, "thin"),
])
def test_person_verdict(entry, expected):
    assert person_verdict(entry, frozenset({"rosalia"})) == expected


def test_person_verdict_finds_yourself_under_any_spelling():
    entry = {"name": "Anthony Gonzalez", "names": ["M83"], "albums": 4}
    assert person_verdict(entry, frozenset({"m83"})) == "yourself"


def test_person_verdict_puts_the_mute_first():
    """A mute is yours and must stay visible as one: "1 junk" beside a name you
    muted deliberately reads as the file being dirty."""
    assert person_verdict({"name": "Unknown", "albums": 7, "watch": False},
                          frozenset()) == "muted"


def test_person_verdict_does_not_test_yourself_without_a_watchlist():
    # The default is an empty set, and `entry & empty` must not drop everybody.
    assert person_verdict({"name": "ROSALÍA", "albums": 9}) == "watched"


def test_earned_names_the_person_the_row_is_there_for():
    """The first full run printed three rows against the wrong person: the
    release was kept for a Producer credit and attributed to whoever held the
    most tracks, who was a Music Director."""
    director = Credit(name="Cachorro López", roles=("Music Director",), tracks=13)
    producer = Credit(name="Someone Else", roles=("Producer",), tracks=2)
    assert earned([director, producer], {"production"}).name == "Someone Else"


def test_earned_is_none_when_nobody_holds_a_wanted_role():
    director = Credit(name="A", roles=("Music Director",), tracks=3)
    assert earned([director], {"production"}) is None


def test_earned_prefers_the_most_tracks_among_those_who_qualify():
    # credits_by already sorts by tracks, so taking the first match is the
    # whole rule -- this pins it against a future reordering.
    small = Credit(name="Small", roles=("Producer",), tracks=1)
    big = Credit(name="Big", roles=("Co- Producer",), tracks=9)
    assert earned([big, small], {"production"}).name == "Big"


@pytest.mark.parametrize("title", [
    "La Quiniela del Día (Remastered 2026)",
    "Some Record (20th Anniversary Edition)",
    "Algo (Edición Especial)",
    # core.appearances' own patterns, through is_reissue: one list, not two.
    "Lo Mejor de Alguien",
    "Greatest Hits",
])
def test_is_reissue_catches_both_lists(title):
    assert is_reissue(title) is True


@pytest.mark.parametrize("title", [
    "Semitrópico",
    "MudaH",
    # Deliberately not caught: a long album is just a long album, and "En
    # Vivo" can be new material -- core/appearances.py measured both.
    "LIVE AT MONTREUX",
])
def test_is_reissue_leaves_a_real_release_alone(title):
    assert is_reissue(title) is False


def test_verdict_calls_a_remaster_a_reissue_not_news():
    credit = Credit(name="Pancho Cristal", roles=("Producer",), tracks=10)
    assert verdict({"99"}, {"41620"}, [credit], {"production"},
                   "La Quiniela del Día (Remastered 2026)") == "reissue"
    # The same credit on a record that is not a repackage.
    assert verdict({"99"}, {"41620"}, [credit], {"production"},
                   "La Quiniela del Día") == "credit"


def test_verdict_tests_the_credits_before_guessing_from_the_title():
    """A reissue nobody you follow worked on is `absent`, not `reissue`: the
    funnel has to count the cheap factual test first or the categories stop
    meaning what they say."""
    assert verdict({"99"}, {"41620"}, [], {"production"},
                   "Greatest Hits") == "absent"


def test_person_verdict_keeps_somebody_who_only_mixes_for_your_artists():
    """Marta Salogni holds 9 credits on these artists' records and none of them
    is `Producer` -- she mixes for them and produces for other people, which is
    exactly who this radar should find. Counting production credits here
    dropped her, and with her the best row in the 90-day backfill."""
    mixer = {"name": "Marta Salogni", "albums": 9, "production": 0}
    assert person_verdict(mixer) == "watched"


def test_person_verdict_still_drops_a_one_off():
    # Ani Sumiati, 1 credit: the five-row self-release that motivated the cap.
    assert person_verdict({"name": "Ani Sumiati", "albums": 1,
                           "production": 1}) == "thin"
    assert person_verdict({"name": "Somebody", "albums": 4}) == "watched"


@pytest.mark.parametrize(("title", "expected"), [
    ("The Boy (Louie Vega & 2SoulFusion Dub Remix)", True),
    ("Everything Everywhere All At Once (Cosmodelica Remix)", True),
    ("Some Track (RMX)", True),
    ("Semitrópico", False),
    # Measured and deliberately left out: three titles is not enough to decide
    # whether a re-recording is news.
    ("Te Odio Y Te Quiero (Salsa Version)", False),
    ("Baby Wow (EDIT)", False),
    ("yellow (afrohouse mix)", False),
])
def test_is_remix(title, expected):
    assert is_remix(title) is expected


def test_verdict_puts_the_credit_tests_before_the_remix_guess():
    assert verdict({"99"}, {"41620"}, [], {"production"},
                   "Something (Remix)") == "absent"


def test_people_records_who_each_person_has_worked_for(tmp_path):
    path = tmp_path / "producers.json"
    path.write_text(json.dumps({"people": [
        {"name": "James Ford", "albums": 9, "production": 9,
         "for": ["Björk", "Little Simz"]},
    ]}))
    found = people(path)
    assert found.worked_for["James Ford"] == ["Björk", "Little Simz"]
