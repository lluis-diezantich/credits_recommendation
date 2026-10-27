"""core/favourites.py: who a radar watches, who it does not, and why not.

The filter itself is covered from the radars' side in test_mute.py and
test_check_active.py. What is here is the part those cannot see: the reason
each entry was excluded, and the counts an issue reports.
"""

from __future__ import annotations

import json

import radars.report as rep
from core import favourites


def write(tmp_path, *artists):
    path = tmp_path / "favourites.json"
    path.write_text(json.dumps({"artists": list(artists)}))
    return path


# ---- one entry, one reason ----------------------------------------------


def test_each_reason():
    verdict = favourites.watch_verdict
    assert verdict({"name": "A", "qobuz_id": 1}, "qobuz_id") == "watched"
    assert verdict({"name": "A", "qobuz_id": 1, "watch": False}, "qobuz_id") == "muted"
    assert verdict({"name": "A", "qobuz_id": 1, "ended": True}, "qobuz_id") == "ended"
    assert verdict({"name": "A", "qobuz_id": None}, "qobuz_id") == "unresolved"
    assert verdict({"name": "A"}, "qobuz_id") == "unresolved"


def test_a_mute_outranks_every_other_reason():
    """A muted artist must not also land in the number you act on.

    `unresolved` is the --review backlog. An artist you muted does not belong
    in it, because you are never going to use the id.
    """
    verdict = favourites.watch_verdict
    both = {"name": "A", "qobuz_id": 1, "watch": False, "ended": True}
    assert verdict(both, "qobuz_id") == "muted"
    assert verdict({"name": "A", "watch": False}, "qobuz_id") == "muted"


def test_ended_outranks_a_missing_id():
    """A dead artist needs no id either, so they are not review backlog."""
    assert favourites.watch_verdict({"name": "A", "ended": "1997-08-02"},
                                    "qobuz_id") == "ended"


# ---- the whole list -----------------------------------------------------


def test_the_counts_account_for_every_entry(tmp_path):
    path = write(
        tmp_path,
        {"name": "Watched", "qobuz_id": 1},
        {"name": "Also watched", "qobuz_id": 2},
        {"name": "Muted", "qobuz_id": 3, "watch": False},
        {"name": "Ended", "qobuz_id": 4, "ended": True},
        {"name": "No id", "qobuz_id": None},
    )
    found = favourites.watchlist("qobuz_id", {0: "fallback"}, path)

    assert found.ids == {1: "Watched", 2: "Also watched"}
    assert found.counts == {"watched": 2, "muted": 1, "ended": 1, "unresolved": 1}
    assert found.excluded == 3
    assert sum(found.counts.values()) == 5
    assert found.collapsed == 0
    assert found.fallback is False


def test_two_entries_on_one_id_collapse_and_are_counted(tmp_path):
    """Two spellings of one artist: two watched entries, one artist watched."""
    path = write(
        tmp_path,
        {"name": "Rosalia", "qobuz_id": 7},
        {"name": "ROSALÍA", "qobuz_id": 7},
    )
    found = favourites.watchlist("qobuz_id", {}, path)
    assert found.ids == {7: "ROSALÍA"}            # last spelling wins, as before
    assert found.counts["watched"] == 2
    assert found.collapsed == 1
    assert found.report()["entries"] - found.report()["ids"] == 1


def test_the_fallback_is_flagged_so_nothing_reports_counts_for_it(tmp_path):
    """The counts describe a list the run did not use, so the radar skips them."""
    path = write(tmp_path, {"name": "Drexler", "qobuz_id": 1})
    found = favourites.watchlist("itunes_id", {999: "built-in"}, path)
    assert found.ids == {999: "built-in"}
    assert found.fallback is True
    assert found.counts["unresolved"] == 1


def test_no_file_at_all_is_a_quiet_fallback(tmp_path, capsys):
    found = favourites.watchlist("qobuz_id", {0: "fallback"}, tmp_path / "nope.json")
    assert found.ids == {0: "fallback"}
    assert found.fallback is True
    assert capsys.readouterr().err == ""


def test_report_is_flat_and_keeps_the_zeros(tmp_path):
    path = write(tmp_path, {"name": "Watched", "qobuz_id": 1})
    assert favourites.watchlist("qobuz_id", {}, path).report() == {
        "entries": 1, "ids": 1, "collapsed": 0,
        "watched": 1, "muted": 0, "ended": 0, "unresolved": 0}


# ---- how it reads in the issue ------------------------------------------


def test_the_line_names_only_what_happened():
    line = rep.watchlist_line({"entries": 172, "ids": 146, "collapsed": 2,
                               "watched": 148, "muted": 15, "ended": 6,
                               "unresolved": 3})
    assert line == ("Watching 146 of 172 on the list: 15 muted by hand, "
                    "6 ended or split up, 3 with no id yet, 2 sharing an id.")


def test_nothing_excluded_is_no_line():
    assert rep.watchlist_line({"entries": 3, "ids": 3, "collapsed": 0,
                               "watched": 3, "muted": 0, "ended": 0,
                               "unresolved": 0}) == ""
    assert rep.watchlist_line({}) == ""


def test_a_radar_that_reports_no_watchlist_gets_no_line():
    """listenbrainz and itunes still call ids_for, so the key is absent."""
    body = rep.to_markdown({"generated": "x", "source": "itunes", "watching": 2,
                            "fetched": 2, "failed": 0, "shared": 0, "releases": []})
    assert "on the list" not in body


def test_the_line_lands_under_the_headline():
    body = rep.to_markdown({"generated": "x", "source": "qobuz", "store": "gb-en",
                            "window": "last 7 days", "watching": 2, "fetched": 2,
                            "failed": 0, "shared": 0, "releases": [],
                            "watchlist": {"entries": 4, "ids": 2, "collapsed": 0,
                                          "watched": 2, "muted": 2, "ended": 0,
                                          "unresolved": 0}})
    lines = [line for line in body.splitlines() if line]
    assert lines[0].startswith("**0 new releases**")
    assert lines[1] == "Watching 2 of 4 on the list: 2 muted by hand."


# --------------------------------------------------------------------------
# The `watch` and `ended` filters, from the radars' side.
#
# These five moved here when the ranking half of the project was archived onto
# the `ranking` branch (D41). They were written against the --mute/--unmute and
# --check-active flags of stages/favourites.py, which went with it, but what
# they actually assert is `core.favourites.ids_for` -- the one function all
# three radars read the watchlist through. Losing them would have left the two
# skips that decide who the Friday radar queries covered by nothing.
# --------------------------------------------------------------------------


def muted_rows():
    return [
        {"name": "Bobby Cruz", "qobuz_id": 55, "qobuz_match": "exact", "tracks": 1},
        {"name": "Jorge Drexler", "qobuz_id": 41620, "qobuz_match": "exact"},
        {"name": "Feli Colina", "qobuz_id": 77, "qobuz_match": "exact", "watch": False},
    ]


def test_the_radar_never_sees_a_muted_artist(tmp_path):
    path = tmp_path / "favourites.json"
    assert favourites.ids_for("qobuz_id", {0: "fallback"}, path) == {0: "fallback"}

    path.write_text(json.dumps({"artists": muted_rows()}))
    assert favourites.ids_for("qobuz_id", {0: "fallback"}, path) == {
        55: "Bobby Cruz", 41620: "Jorge Drexler"}       # Feli Colina is muted


def test_a_file_with_no_id_for_a_source_falls_back(tmp_path, capsys):
    """Resolving only Qobuz ids must not quietly empty the iTunes radar."""
    path = tmp_path / "favourites.json"
    path.write_text(json.dumps({"artists": muted_rows()}))
    assert favourites.ids_for("itunes_id", {16421943: "Drexler"}, path) == {
        16421943: "Drexler"}
    assert "has no itunes_id for any artist" in capsys.readouterr().err


def test_an_unreadable_file_degrades_to_the_fallback(tmp_path, capsys):
    path = tmp_path / "favourites.json"
    path.write_text("{ not json")
    assert favourites.ids_for("qobuz_id", {0: "fallback"}, path) == {0: "fallback"}
    assert "ignoring unreadable" in capsys.readouterr().err


def test_an_ended_artist_is_skipped_by_every_radar(tmp_path):
    """ids_for is the one place all three radars read, so the skip lives there."""
    path = tmp_path / "favourites.json"
    path.write_text(json.dumps({"artists": [
        {"name": "Fela Kuti", "qobuz_id": 1, "ended": "1997-08-02"},
        {"name": "Jorge Drexler", "qobuz_id": 2},
    ]}))
    assert favourites.ids_for("qobuz_id", {}, path) == {2: "Jorge Drexler"}


def test_ended_and_watch_false_are_independent_skips(tmp_path):
    """Lifting a mute must not resurrect a dead artist, and vice versa."""
    path = tmp_path / "favourites.json"
    path.write_text(json.dumps({"artists": [
        {"name": "Dead and watched", "qobuz_id": 1, "ended": True},
        {"name": "Alive and muted", "qobuz_id": 2, "watch": False},
        {"name": "Dead and muted", "qobuz_id": 3, "ended": True, "watch": False},
        {"name": "Alive and watched", "qobuz_id": 4},
    ]}))
    assert favourites.ids_for("qobuz_id", {}, path) == {4: "Alive and watched"}
