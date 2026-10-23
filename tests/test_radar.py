"""radars/qobuz.py: what it reports, what it skips, and when it refuses to."""

from __future__ import annotations


def test_a_release_shared_by_two_watched_artists_is_reported_once(qobuz, album, capsys):
    """`seen` holds previous runs only, so without a within-run check the same
    release is fetched once per credited artist and printed twice, identically.
    Invisible with one artist watched, routine with ninety."""
    shared = album(900, 1, "Te Odio", tracks=1, artists=[(1, "La Plazuela"), (2, "Yerai")])
    qobuz.discography = {
        1: [shared, album(901, 1, "Solo Mia")],
        2: [shared, album(902, 2, "Suyo")],
    }
    code = qobuz.run(["--days", "0"], watching={1: "La Plazuela", 2: "Yerai"})
    out = capsys.readouterr().out

    assert code == 0
    assert out.count("Te Odio") == 1
    assert "3 new releases" in out
    assert "1 were credited to more than one artist" in out
    assert qobuz.saved == {"900", "901", "902"}


def test_two_editions_of_one_album_are_still_two_rows(qobuz, album, capsys):
    """Different Qobuz ids, so merging them needs release identity, not a title
    heuristic -- "Libertad (Deluxe)" folding into "Libertad" would hide the one
    with the extra tracks."""
    qobuz.discography = {1: [album(903, 1, "Libertad", tracks=13),
                             album(904, 1, "Libertad", tracks=13, hires=False)]}
    qobuz.run(["--all", "--days", "0"], watching={1: "CHUWI"})
    assert capsys.readouterr().out.count("Libertad") == 2


def test_one_artist_failing_does_not_lose_the_run(qobuz, album, capsys):
    """This used to raise SystemExit, and because state is written at the end it
    threw away every release found before it."""
    def pages(artist):
        return (None, "error") if artist == 2 else [album(artist * 10, artist,
                                                          date="2026-10-01")]
    qobuz.discography = pages
    code = qobuz.run(["--days", "0"], watching={1: "One", 2: "Two", 3: "Three"})
    out, err = capsys.readouterr()

    assert code == 0
    assert qobuz.asked == [1, 2, 3]
    assert "Scanned 2 releases from 2 of 3 artists" in out
    assert "Two (2) lookup failed, skipped" in err
    assert qobuz.saved == {"10", "30"}          # nothing recorded for the failure


def test_nothing_from_anybody_is_a_broken_run(qobuz, capsys):
    """Qobuz answering 200 with an empty discography for everyone is the same
    outage as refusing outright, but every artist "succeeds" -- so it would
    read as a quiet week, every week, with the warnings collapsed."""
    qobuz.discography = {1: [], 2: [], 3: []}
    code = qobuz.run(["--all", "--days", "10"],
                     watching={1: "One", 2: "Two", 3: "Three"})
    err = capsys.readouterr().err

    assert code == 1
    assert "nothing came back from any of 3 artists (0 failed, 3 returned an empty" in err


def test_failures_and_empties_count_together(qobuz, capsys):
    qobuz.discography = lambda a: (None, "error") if a == 1 else []
    code = qobuz.run(["--all", "--days", "10"],
                     watching={1: "One", 2: "Two", 3: "Three"})
    assert code == 1
    assert "(1 failed, 2 returned an empty" in capsys.readouterr().err


def test_a_quiet_week_is_not_a_broken_run(qobuz, album, capsys):
    """The guard must not fire here. A quiet week still returns catalogue; it
    is the DATE FILTER that empties the list, not the fetch."""
    qobuz.discography = {1: [album(1, 1, date="1998-01-01")],
                         2: [album(2, 2, date="1999-01-01")]}
    code = qobuz.run(["--all", "--days", "10"], watching={1: "One", 2: "Two"})

    assert code == 0
    assert "Nothing new." in capsys.readouterr().out


def test_one_live_artist_keeps_the_run_healthy(qobuz, album, capsys):
    qobuz.discography = lambda a: [album(99, a, date="2026-10-15")] if a == 2 else []
    code = qobuz.run(["--all", "--days", "3650"], watching={1: "One", 2: "Two"})
    assert code == 0
    assert "1 new release" in capsys.readouterr().out


def test_guest_appearances_are_dropped(qobuz, album, capsys):
    """The discography would otherwise fill with other people's records."""
    qobuz.discography = {1: [album(5, 1, "Theirs", artists=[(99, "Someone Else")]),
                             album(6, 1, "Mine")]}
    qobuz.run(["--all", "--days", "0"], watching={1: "One"})
    out = capsys.readouterr().out
    assert "Mine" in out and "Theirs" not in out


def test_all_writes_no_state(qobuz, album):
    """--all is what makes the weekly workflow stateless."""
    qobuz.discography = {1: [album(7, 1, date="2026-10-15")]}
    qobuz.run(["--all", "--days", "30"], watching={1: "One"})
    assert qobuz.saved is None


def test_a_normal_run_records_everything_it_scanned(qobuz, album):
    """Not just what it reported: otherwise the back catalogue past --days
    resurfaces as new the first time the window widens."""
    qobuz.discography = {1: [album(8, 1, date="1998-01-01"),
                             album(9, 1, date="2026-10-15")]}
    qobuz.run(["--days", "30"], watching={1: "One"})
    assert qobuz.saved == {"8", "9"}


def test_json_report_carries_the_run_not_just_the_rows(qobuz, album, tmp_path):
    import json
    out = tmp_path / "releases.json"
    qobuz.discography = {1: [album(11, 1, date="2026-10-14")],
                         2: [album(12, 2, date="2099-01-01")]}
    qobuz.run(["--all", "--days", "0", "--json", str(out)],
              watching={1: "One", 2: "Two"})

    report = json.loads(out.read_text())
    assert report["source"] == "qobuz"
    assert report["watching"] == 2 and report["fetched"] == 2 and report["failed"] == 0
    # The 2099 pre-order is dropped rather than badged (D33), so every row this
    # radar carries is playable. The key stays in the shape for the sources
    # that do keep upcoming releases.
    assert [r["upcoming"] for r in report["releases"]] == [False]


def test_a_pre_order_is_neither_reported_nor_recorded(qobuz, album, tmp_path):
    """The dangerous half is the recording.

    Dropping it from the issue is the point, but banking the id would mean the
    album is reported in NO issue -- not now, and not in the week it is
    actually released.
    """
    import json
    log = tmp_path / "runs.jsonl"
    qobuz.discography = {1: [album(8, 1, date="2026-10-15"),
                             album(9, 1, date="2099-01-01")]}
    qobuz.run(["--days", "0", "--run-log", str(log)], watching={1: "One"})

    assert qobuz.saved == {"8"}
    row = json.loads(log.read_text().splitlines()[-1])
    assert row["reported"] == 1 and row["upcoming"] == 1


def test_a_broken_run_writes_no_report(qobuz, tmp_path):
    """Otherwise the workflow publishes an issue built from an outage."""
    out = tmp_path / "releases.json"
    qobuz.discography = {1: [], 2: []}
    code = qobuz.run(["--all", "--days", "0", "--json", str(out)],
                     watching={1: "One", 2: "Two"})
    assert code == 1 and not out.exists()
