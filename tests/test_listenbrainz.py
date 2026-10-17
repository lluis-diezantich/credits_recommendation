"""radars/listenbrainz.py: the one that reads a window, not a catalogue.

itunes.py and qobuz.py ask per artist and read a discography; this makes ONE
request for every release MusicBrainz knows about in a window around today and
intersects it locally. Three settings in core/radar.py exist to say so, and
each of them is a decision that looks like a bug until you know why:

  record_scanned = False      a release that matched nobody is NOT recorded.
                              Recording it would hide it for good if you later
                              started watching that artist.
  guard_empty_run = False     a feed answering with zero rows is a legitimate
                              quiet window, and nothing distinguishes it from
                              an outage -- so unlike the other two radars, an
                              empty run here is not an error.
  cutoff() -> ""              the server already applied the window, and --days
                              is a HALF-WIDTH; filtering again locally would
                              halve it.

Those three, plus the state file that keeps its pre-convention name, are what
these tests are mostly about. The rest of the run is core/radar.py's and is
tested there.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

import radars.listenbrainz as mod
from core.radar import Release

WATCHING = {"mbid-drexler": "Jorge Drexler"}


# ---- dedup_key: the identity of a feed row ------------------------------


def test_the_release_mbid_is_the_identity():
    assert mod.dedup_key({"release_mbid": "rel-1"}) == "rel-1"


def test_the_release_group_is_the_fallback():
    assert mod.dedup_key({"release_group_mbid": "rg-1"}) == "rg-1"


def test_a_row_with_neither_gets_a_synthetic_key_rather_than_none():
    """A row with no id would otherwise be reported every single run, because
    nothing in the state file could ever match it."""
    key = mod.dedup_key({"artist_credit_name": "A", "release_name": "B",
                         "release_date": "2026-10-14"})
    assert key == "A|B|2026-10-14"


def test_the_synthetic_key_is_stable_across_runs():
    row = {"artist_credit_name": "A", "release_name": "B", "release_date": "C"}
    assert mod.dedup_key(dict(row)) == mod.dedup_key(dict(row))


def test_an_empty_mbid_does_not_win_over_the_fallback():
    """`or` chaining, so "" falls through rather than becoming the key."""
    assert mod.dedup_key({"release_mbid": "", "release_group_mbid": "rg-1"}) == "rg-1"


# ---- normalize ----------------------------------------------------------


def test_a_row_becomes_a_release(feed_row):
    release = mod.normalize(feed_row(mbid="rel-1", name="Tinta Y Tiempo",
                                     date="2026-10-14", kind="Album"),
                            ["Jorge Drexler"])
    assert isinstance(release, Release)
    assert (release.id, release.date, release.kind, release.title) == (
        "rel-1", "2026-10-14", "Album", "Tinta Y Tiempo")
    assert release.source == "listenbrainz"


def test_the_watched_name_is_shown_when_the_credit_matches_it(feed_row):
    release = mod.normalize(feed_row(credit="Jorge Drexler"), ["Jorge Drexler"])
    assert release.artist == "Jorge Drexler"


def test_the_full_credit_is_shown_when_it_differs(feed_row):
    """So a collaboration or a compilation appearance is obvious, rather than
    looking like a record you did not know they made."""
    release = mod.normalize(feed_row(credit="Jorge Drexler & Natalia Lafourcade"),
                            ["Jorge Drexler"])
    assert release.artist == "Jorge Drexler & Natalia Lafourcade"


def test_two_watched_artists_on_one_release_are_both_named(feed_row):
    release = mod.normalize(feed_row(credit="Jorge Drexler, Ana Prada"),
                            ["Jorge Drexler", "Ana Prada"])
    assert release.artist == "Jorge Drexler, Ana Prada"


def test_an_untyped_row_is_called_release_not_left_blank(feed_row):
    """The feed carries None for untyped entries. "Release" is what keep_types
    then filters out, which is the intent -- an untyped row is noise here."""
    row = feed_row()
    row["release_group_primary_type"] = None
    assert mod.normalize(row, ["A"]).kind == "Release"
    keep = mod.ListenbrainzRadar.keep_types
    assert keep is not None                  # None would mean "keep everything"
    assert "Release" not in keep


def test_a_row_with_no_name_or_date_says_so(feed_row):
    row = feed_row()
    row["release_name"] = None
    row["release_date"] = None
    release = mod.normalize(row, ["A"])
    assert (release.title, release.date) == ("(untitled)", "????-??-??")


# ---- fetch_feed ---------------------------------------------------------


def test_the_feed_is_asked_for_a_window_around_today(listenbrainz, feed_row):
    """--days is a half-width, and it goes to the server as `days`."""
    listenbrainz.feed = [feed_row()]
    listenbrainz.run(["--days", "21"], watching=WATCHING)
    url = listenbrainz.urls[0]
    assert f"release_date={dt.date.today().isoformat()}" in url
    assert "days=21" in url


def test_exactly_one_request_is_made_however_many_artists_are_watched(listenbrainz,
                                                                      feed_row):
    """The whole shape of this radar: one global request filtered locally."""
    listenbrainz.feed = [feed_row()]
    listenbrainz.run(["--days", "7"],
                     watching={f"mbid-{i}": f"Artist {i}" for i in range(50)})
    assert len(listenbrainz.urls) == 1


def test_a_failed_feed_exits_rather_than_reporting_an_empty_week(listenbrainz):
    """There is exactly one call here, so a failure leaves nothing to salvage.
    The per-artist radars can lose one lookup of ninety and still be useful."""
    listenbrainz.feed = 503
    with pytest.raises(SystemExit, match="HTTP 503"):
        listenbrainz.run(["--days", "7"], watching=WATCHING)


def test_a_body_that_is_not_json_also_exits(listenbrainz):
    listenbrainz.feed = "<html>gateway timeout</html>"
    with pytest.raises(SystemExit, match="not JSON"):
        listenbrainz.run(["--days", "7"], watching=WATCHING)


# ---- the intersection ---------------------------------------------------


def test_only_releases_crediting_a_watched_mbid_are_reported(listenbrainz, feed_row,
                                                              capsys):
    listenbrainz.feed = [
        feed_row(mbid="rel-1", name="Mine", artist_mbids=["mbid-drexler"]),
        feed_row(mbid="rel-2", name="Somebody Elses", artist_mbids=["mbid-other"]),
    ]
    code = listenbrainz.run(["--days", "7"], watching=WATCHING)
    out = capsys.readouterr().out

    assert code == 0
    assert "Mine" in out and "Somebody Elses" not in out


def test_matching_is_on_the_mbid_so_a_collaboration_is_caught(listenbrainz,
                                                              feed_row, capsys):
    """A release credited "X & Y" carries both MBIDs in artist_mbids, which is
    why matching on the id rather than the name finds it."""
    listenbrainz.feed = [feed_row(mbid="rel-1", name="Juntos",
                                  credit="Someone Else & Jorge Drexler",
                                  artist_mbids=["mbid-other", "mbid-drexler"])]
    code = listenbrainz.run(["--days", "7"], watching=WATCHING)
    out = capsys.readouterr().out

    assert code == 0
    assert "Juntos" in out
    assert "Someone Else & Jorge Drexler" in out


def test_a_row_with_no_artist_mbids_matches_nobody(listenbrainz, feed_row, capsys):
    listenbrainz.feed = [feed_row(mbid="rel-1", name="Unattributed",
                                  artist_mbids=[])]
    assert listenbrainz.run(["--days", "7"], watching=WATCHING) == 0
    assert "Nothing new." in capsys.readouterr().out


def test_scanned_counts_the_whole_feed_not_the_matches(listenbrainz, feed_row,
                                                        capsys):
    """"Scanned 1 release" would describe the intersection and not the work,
    and the run log reads `scanned` to tell a quiet week from a broken one."""
    listenbrainz.feed = [feed_row(mbid=f"rel-{i}", artist_mbids=["mbid-other"])
                         for i in range(20)]
    listenbrainz.feed.append(feed_row(mbid="mine", artist_mbids=["mbid-drexler"]))
    listenbrainz.run(["--days", "7"], watching=WATCHING)
    assert "Scanned 21 releases" in capsys.readouterr().out


# ---- the three settings that make this radar different ------------------


def test_a_release_that_matched_nobody_is_not_recorded_as_seen(listenbrainz,
                                                                feed_row):
    """record_scanned = False, and this is the reason: recording a release that
    matched nobody would hide it for good if you later started watching that
    artist. The other two radars record everything they scan on purpose."""
    listenbrainz.feed = [
        feed_row(mbid="mine", artist_mbids=["mbid-drexler"]),
        feed_row(mbid="theirs", artist_mbids=["mbid-other"]),
    ]
    listenbrainz.run(["--days", "7"], watching=WATCHING)
    assert listenbrainz.saved == {"mine"}


def test_an_empty_feed_is_a_quiet_window_not_a_broken_run(listenbrainz, capsys):
    """guard_empty_run = False. A feed answering with zero rows is legitimate
    and nothing distinguishes it from an outage, so unlike itunes.py this must
    exit 0 rather than claim the run broke."""
    listenbrainz.feed = []
    code = listenbrainz.run(["--days", "7"], watching=WATCHING)
    out = capsys.readouterr()

    assert code == 0
    assert "Nothing new." in out.out
    assert "broken run" not in out.err


def test_the_server_window_is_not_filtered_again_locally(listenbrainz, feed_row,
                                                          capsys):
    """cutoff() returns "" on purpose. --days is a half-width, so applying it as
    a lookback would halve the window and drop everything in the future half --
    which is most of what a fresh-releases feed is for."""
    future = (dt.date.today() + dt.timedelta(days=5)).isoformat()
    old = (dt.date.today() - dt.timedelta(days=5)).isoformat()
    listenbrainz.feed = [
        feed_row(mbid="ahead", name="Coming Soon", date=future),
        feed_row(mbid="behind", name="Just Out", date=old),
    ]
    code = listenbrainz.run(["--days", "7"], watching=WATCHING)
    out = capsys.readouterr().out

    assert code == 0
    assert "Coming Soon" in out and "Just Out" in out


def test_the_state_file_keeps_its_pre_convention_name():
    """data/seen.json, not data/listenbrainz_seen.json: this radar was the
    project's first and renaming it would silently re-report the whole window
    once. core/radar.py's --state overrides it for a runner."""
    assert mod.ListenbrainzRadar().state_file.name == "seen.json"


def test_the_window_is_described_as_a_half_width_in_the_report(listenbrainz,
                                                               feed_row, tmp_path):
    out = tmp_path / "releases.json"
    listenbrainz.feed = [feed_row()]
    listenbrainz.run(["--days", "14", "--json", str(out)], watching=WATCHING)
    report = json.loads(out.read_text())

    assert report["source"] == "listenbrainz"
    assert report["window"] == f"+/-14 days around {dt.date.today().isoformat()}"


# ---- the rest of the run ------------------------------------------------


def test_an_unwanted_kind_is_dropped(listenbrainz, feed_row, capsys):
    """The feed carries Broadcast and Other, which are noise here."""
    listenbrainz.feed = [
        feed_row(mbid="rel-1", name="An Album", kind="Album"),
        feed_row(mbid="rel-2", name="A Broadcast", kind="Broadcast"),
    ]
    code = listenbrainz.run(["--days", "7"], watching=WATCHING)
    out = capsys.readouterr().out

    assert code == 0
    assert "An Album" in out and "A Broadcast" not in out


def test_what_was_already_reported_is_not_reported_again(listenbrainz, feed_row,
                                                          capsys):
    listenbrainz.feed = [feed_row(mbid="old", name="Old"),
                         feed_row(mbid="new", name="New")]
    code = listenbrainz.run(["--days", "7"], watching=WATCHING, seen={"old"})
    out = capsys.readouterr().out

    assert code == 0
    assert "New" in out and "Old" not in out
    assert listenbrainz.saved == {"old", "new"}


def test_one_release_credited_to_two_watched_artists_is_reported_once(listenbrainz,
                                                                      feed_row,
                                                                      capsys):
    listenbrainz.feed = [feed_row(mbid="rel-1", name="Juntos",
                                  credit="A & B",
                                  artist_mbids=["mbid-a", "mbid-b"])]
    code = listenbrainz.run(["--days", "7"],
                            watching={"mbid-a": "A", "mbid-b": "B"})
    out = capsys.readouterr().out

    assert code == 0
    assert out.count("Juntos") == 1


def test_dry_run_reports_without_recording(listenbrainz, feed_row, capsys):
    listenbrainz.feed = [feed_row(mbid="rel-1", name="Tinta Y Tiempo")]
    code = listenbrainz.run(["--days", "7", "--dry-run"], watching=WATCHING)
    assert code == 0
    assert "Tinta Y Tiempo" in capsys.readouterr().out
    assert listenbrainz.saved is None


def test_all_ignores_the_state_file_and_writes_nothing(listenbrainz, feed_row,
                                                        capsys):
    listenbrainz.feed = [feed_row(mbid="known", name="Known")]
    code = listenbrainz.run(["--days", "7", "--all"], watching=WATCHING,
                            seen={"known"})
    assert code == 0
    assert "Known" in capsys.readouterr().out
    assert listenbrainz.saved is None


def test_an_empty_watchlist_exits_with_something_actionable(listenbrainz):
    with pytest.raises(SystemExit, match="WATCHED_ARTISTS is empty"):
        listenbrainz.run(["--days", "7"], watching={})
