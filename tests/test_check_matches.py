"""stages/favourites.py --check-matches: catching a confidently wrong id.

The case this exists for: "ZOO" resolved `exact` to a Qobuz id holding several
unrelated acts, and --review never re-asks an exact match, so the Friday radar
reported someone else's releases until a human got suspicious.
"""

from __future__ import annotations

import policy
from core import musicbrainz


def doc(begin):
    return {"name": "X", "life-span": {"begin": begin, "ended": False}}


# ---- the two pure halves ------------------------------------------------


def test_only_the_year_of_a_begin_date_is_trusted():
    assert musicbrainz.began_year(doc("2014")) == 2014
    assert musicbrainz.began_year(doc("2008-05")) == 2008
    assert musicbrainz.began_year(doc("1996-07-04")) == 1996


def test_an_unknown_begin_is_none_not_zero():
    """18 of 154 cached artists have no begin date, and "no idea" must not
    read as "year zero" and flag their whole catalogue."""
    assert musicbrainz.began_year(doc("")) is None
    assert musicbrainz.began_year(doc(None)) is None
    assert musicbrainz.began_year({"name": "X"}) is None
    assert musicbrainz.began_year(None) is None
    assert musicbrainz.began_year(doc("unknown")) is None


def test_a_catalogue_starting_before_the_artist_is_a_contradiction():
    assert musicbrainz.predates("1996-07-04", 2008) is True
    assert musicbrainz.predates("2019-08-14", 2020) is True   # CHUWI, one year


def test_the_founding_year_itself_is_fine():
    """`begin` is often a bare year, so a debut released that year must pass."""
    assert musicbrainz.predates("2014-11-10", 2014) is False
    assert musicbrainz.predates("2026-01-01", 2014) is False


def test_unknowable_is_not_suspicious():
    assert musicbrainz.predates("1996-07-04", None) is False
    assert musicbrainz.predates("", 2008) is False
    assert musicbrainz.predates("????-??-??", 2008) is False


def test_slack_widens_the_tolerance():
    assert musicbrainz.predates("2019-01-01", 2020, 1) is False
    assert musicbrainz.predates("2018-01-01", 2020, 1) is True


def test_the_threshold_lives_in_policy():
    """D1, and zero is measured: 109 of 111 clean, and both flags genuine."""
    assert policy.MATCH_SPAN_SLACK_YEARS == 0


# ---- the stage ----------------------------------------------------------


def run(favourites_file, monkeypatch, entries, catalogues, begins, dry_run=False):
    stage = favourites_file.install()
    favourites_file.entries = entries
    monkeypatch.setattr(stage, "store_cookies", lambda store: "c=1")
    monkeypatch.setattr(stage, "artist_releases",
                        lambda aid, store, cookies: catalogues[aid])
    monkeypatch.setattr(stage.musicbrainz, "artist",
                        lambda mbid, **kw: doc(begins.get(mbid)))
    monkeypatch.setattr(stage.time, "sleep", lambda s: None)
    return stage.check_matches("gb-en", dry_run)


def album(date, title="A"):
    return {"release_date_original": date, "title": title}


def test_a_polluted_catalogue_is_flagged_without_touching_the_match(
        favourites_file, monkeypatch, capsys):
    """D5: flag rather than reclassify. The resolver was not wrong about what
    it did, so `qobuz_match` stays and the doubt goes somewhere else."""
    entries = [{"name": "Y La Bamba", "mbid": "m1", "qobuz_id": 737125,
                "qobuz_match": "exact"}]
    code = run(favourites_file, monkeypatch, entries,
               {737125: ("Y La Bamba", [album("1996-07-04", "Navidad Negra"),
                                        album("2008-12-02", "Alida St")], True)},
               {"m1": "2008"})
    out = capsys.readouterr().out

    assert code == 0
    assert entries[0]["qobuz_match"] == "exact"
    assert "catalogue starts 1996" in str(entries[0]["suspect"])
    assert "began 2008" in str(entries[0]["suspect"])
    assert "SUSPECT" in out and "Navidad Negra" in out
    assert favourites_file.saved is not None


def test_a_consistent_catalogue_is_left_alone(favourites_file, monkeypatch):
    entries = [{"name": "Fine", "mbid": "m1", "qobuz_id": 1, "qobuz_match": "exact"}]
    run(favourites_file, monkeypatch, entries,
        {1: ("Fine", [album("2015-01-01")], True)}, {"m1": "2014"})
    assert "suspect" not in entries[0]
    assert favourites_file.saved is None       # nothing changed, nothing written


def test_a_fixed_id_clears_its_old_flag(favourites_file, monkeypatch, capsys):
    """The same stance --check-active takes when MusicBrainz corrects itself."""
    entries = [{"name": "ZOO", "mbid": "m1", "qobuz_id": 31249576,
                "qobuz_match": "manual", "suspect": "catalogue starts 1969"}]
    run(favourites_file, monkeypatch, entries,
        {31249576: ("ZOO", [album("2014-11-10")], True)}, {"m1": "2014"})
    assert "suspect" not in entries[0]
    assert "cleared" in capsys.readouterr().out


def test_an_artist_with_no_begin_date_is_unknowable_not_clean(
        favourites_file, monkeypatch, capsys):
    entries = [{"name": "Mystery", "mbid": "m1", "qobuz_id": 1, "qobuz_match": "exact"}]
    run(favourites_file, monkeypatch, entries,
        {1: ("Mystery", [album("1950-01-01")], True)}, {"m1": None})
    out = capsys.readouterr().out
    assert "suspect" not in entries[0]
    assert "no begin" in out and "1 with no begin date" in out


def test_a_failed_lookup_flags_nothing(favourites_file, monkeypatch, capsys):
    """An unanswerable check must not read as a pass, in either direction."""
    entries = [{"name": "Down", "mbid": "m1", "qobuz_id": 1, "qobuz_match": "exact"}]
    run(favourites_file, monkeypatch, entries,
        {1: (None, [], False)}, {"m1": "2014"})
    assert "suspect" not in entries[0]
    assert "1 unanswered" in capsys.readouterr().out


def test_dry_run_reports_and_writes_nothing(favourites_file, monkeypatch, capsys):
    entries = [{"name": "Y La Bamba", "mbid": "m1", "qobuz_id": 1,
                "qobuz_match": "exact"}]
    run(favourites_file, monkeypatch, entries,
        {1: ("Y La Bamba", [album("1996-01-01")], True)}, {"m1": "2008"}, dry_run=True)
    assert favourites_file.saved is None
    assert "--dry-run" in capsys.readouterr().out


def test_an_artist_with_no_mbid_is_reported_as_unchecked(
        favourites_file, monkeypatch, capsys):
    entries = [{"name": "No MBID", "qobuz_id": 1, "qobuz_match": "exact"}]
    run(favourites_file, monkeypatch, entries, {}, {})
    assert "watched with no MBID" in capsys.readouterr().out


# ---- and the point of the flag ------------------------------------------


def test_review_asks_about_a_suspect_even_when_the_match_was_exact(
        favourites_file, monkeypatch, capsys):
    """Otherwise the flag is inert: --check-matches only flags a row BECAUSE
    the confident answer looks wrong."""
    stage = favourites_file.install()
    favourites_file.entries = [
        {"name": "Fine", "qobuz_id": 9, "qobuz_match": "exact"},
        {"name": "Y La Bamba", "qobuz_id": 8, "qobuz_match": "exact",
         "suspect": "catalogue starts 1996, but MusicBrainz says 2008"},
        {"name": "Hushed", "qobuz_id": 7, "qobuz_match": "exact",
         "suspect": "something", "watch": False},
    ]
    monkeypatch.setattr(stage, "search_artists", lambda name, store: [])
    favourites_file.answers(["q"])
    stage.review("gb-en", False)
    assert "1 artists to review" in capsys.readouterr().out
