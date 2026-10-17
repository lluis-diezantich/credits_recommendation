"""radars/itunes.py: what Apple's shape costs, and the outage that looked fine.

The pure functions here exist because Apple's API has no usable type field --
`collectionType` is literally "Album" for a one-track single -- so the release
kind is INFERRED from the title suffix. That inference is the whole reason this
radar has its own normalise step rather than handing rows straight to
core/radar.py, and it is what most of these tests are about.

The other half is the failure behaviour the module docstring records: before
this radar moved onto the shared run, an Apple outage reported "Nothing new."
and looked correct. core/radar.py's broken-run guard is what fixed it, and
`guard_empty_run` being left ON here (unlike listenbrainz.py) is the decision
being tested.
"""

from __future__ import annotations

import json

import pytest

import radars.itunes as mod
from core.radar import Release

# ---- classify: the type Apple does not tell you -------------------------


@pytest.mark.parametrize("name,tracks,expected", [
    ("Tinta Y Tiempo - Single", 1, "Single"),
    ("Tinta Y Tiempo - EP", 4, "EP"),
    ("Tinta Y Tiempo", 12, "Album"),
    ("Tinta Y Tiempo", 1, "Single"),        # untagged, trackCount decides
    ("Tinta Y Tiempo", 0, "Album"),         # absent count is not a single
])
def test_the_kind_is_inferred_from_the_suffix_then_the_track_count(name, tracks,
                                                                   expected):
    assert mod.classify({"collectionName": name, "trackCount": tracks}) == expected


def test_a_row_with_no_name_at_all_is_an_album():
    """Not a crash and not a Single: nothing was said, so the common case wins."""
    assert mod.classify({}) == "Album"


def test_the_suffix_must_be_at_the_end_to_count():
    """"Single" inside a title is a word, not a type. "- EP" mid-title likewise."""
    assert mod.classify({"collectionName": "Single Ladies", "trackCount": 9}
                           ) == "Album"
    assert mod.classify({"collectionName": "The EP Years", "trackCount": 9}
                           ) == "Album"


# ---- clean_title --------------------------------------------------------


def test_the_type_suffix_comes_out_of_the_title():
    """It is shown in its own column, so leaving it in the title prints it twice."""
    assert mod.clean_title({"collectionName": "Salvavidas De Hielo - Single"}
                              ) == "Salvavidas De Hielo"
    assert mod.clean_title({"collectionName": "Bailar En La Cueva - EP"}
                              ) == "Bailar En La Cueva"


def test_a_title_with_no_suffix_is_left_alone():
    assert mod.clean_title({"collectionName": "Eco"}) == "Eco"


def test_a_missing_title_says_so_rather_than_being_blank():
    """An empty cell in the weekly issue reads as a formatting bug; "(untitled)"
    reads as Apple not having said."""
    assert mod.clean_title({}) == "(untitled)"


# ---- normalize ----------------------------------------------------------


def test_a_row_becomes_a_release(apple_release):
    row = apple_release(1, "Tinta Y Tiempo", date="2026-10-14", tracks=12)
    release = mod.normalize(row, "label")
    assert isinstance(release, Release)
    assert (release.id, release.date, release.kind, release.title, release.tracks
            ) == ("1", "2026-10-14", "Album", "Tinta Y Tiempo", 12)
    assert release.source == "itunes"


def test_the_timestamp_is_cut_back_to_a_date(apple_release):
    """Apple sends "2026-10-14T07:00:00Z" and every other radar sends a date;
    the report sorts on this column, so the shapes have to match."""
    assert mod.normalize(apple_release(1, "X", date="2026-01-02"), "l"
                            ).date == "2026-01-02"


def test_a_row_with_no_release_date_is_marked_unknown_not_empty(apple_release):
    row = apple_release(1, "X")
    del row["releaseDate"]
    assert mod.normalize(row, "l").date == "????-??-??"


def test_what_apple_does_not_say_is_left_unset_rather_than_false(apple_release):
    """Apple reports neither hi-res nor streamability. `None` and `False` are
    different claims, and the report renders a badge for one and nothing for
    the other -- false would assert "this is not hi-res"."""
    release = mod.normalize(apple_release(1, "X"), "l")
    assert release.hires is None
    assert release.streamable is None
    assert "hires" not in release.row()


def test_the_watched_label_is_the_fallback_when_apple_names_nobody(apple_release):
    row = apple_release(1, "X")
    del row["artistName"]
    assert mod.normalize(row, "Jorge Drexler").artist == "Jorge Drexler"


# ---- fetch_artist_releases ----------------------------------------------


def test_the_artist_row_apple_puts_first_is_not_a_release(itunes_fetch):
    """results[0] is the artist itself, with wrapperType "artist". Taking the
    whole list would report the artist as a record every single run."""
    rows = itunes_fetch({"results": [
        {"wrapperType": "artist", "artistId": 1, "artistName": "Jorge Drexler"},
        {"wrapperType": "collection", "collectionId": 9, "collectionName": "Eco"}]})
    assert [r["collectionId"] for r in rows] == [9]


def test_an_unknown_artist_id_is_an_empty_list_not_an_error(itunes_fetch):
    assert itunes_fetch({"results": []}) == []
    assert itunes_fetch({}) == []


def test_a_non_200_is_raised_so_the_run_can_count_it_as_a_failure(itunes_fetch):
    with pytest.raises(RuntimeError, match="HTTP 503"):
        itunes_fetch(503)


@pytest.fixture
def itunes_fetch(monkeypatch):
    """fetch_artist_releases against one canned response."""
    def call(payload):
        def fake(url, headers=None, timeout=30, user_agent=None, service=""):
            if isinstance(payload, int):
                return payload, "", {}
            return 200, json.dumps(payload), {}
        monkeypatch.setattr(mod, "http_get", fake)
        return mod.fetch_artist_releases(1)
    return call


# ---- the run ------------------------------------------------------------


def test_a_new_release_is_reported_and_recorded(itunes, apple_release, capsys):
    itunes.catalogue = {1: [apple_release(900, "Tinta Y Tiempo")]}
    code = itunes.run(["--days", "0"], watching={1: "Jorge Drexler"})
    out = capsys.readouterr().out

    assert code == 0
    assert "Tinta Y Tiempo" in out
    assert "1 new release." in out
    assert itunes.saved == {"900"}


def test_what_was_already_reported_is_not_reported_again(itunes, apple_release,
                                                         capsys):
    itunes.catalogue = {1: [apple_release(900, "Old"), apple_release(901, "New")]}
    code = itunes.run(["--days", "0"], watching={1: "A"}, seen={"900"})
    out = capsys.readouterr().out

    assert code == 0
    assert "New" in out and "Old" not in out
    assert itunes.saved == {"900", "901"}


def test_everything_scanned_is_recorded_even_when_it_is_too_old_to_report(
        itunes, apple_release, capsys):
    """record_scanned is ON for this radar, which is what stops an old release
    resurfacing as news the week it falls out of the date window."""
    itunes.catalogue = {1: [apple_release(900, "Ancient", date="1999-01-01")]}
    code = itunes.run(["--days", "30"], watching={1: "A"})

    assert code == 0
    assert "Nothing new." in capsys.readouterr().out
    assert itunes.saved == {"900"}            # recorded without being reported


def test_one_artist_failing_does_not_lose_the_others(itunes, apple_release, capsys):
    """Ninety artists in a run and an intermittent 5xx is expected rather than
    unlucky, so a failure is one batch, not the run."""
    itunes.catalogue = {1: 503, 2: [apple_release(901, "Fine")]}
    code = itunes.run(["--days", "0"], watching={1: "Broken", 2: "Working"})
    captured = capsys.readouterr()

    assert code == 0
    assert "Fine" in captured.out
    assert "Broken (1) lookup failed" in captured.err
    assert "1 lookup could not be fetched" in captured.out


def test_a_failed_artists_releases_are_not_recorded_as_seen(itunes, apple_release):
    """So a later run reports them. The state file must never claim to have
    reported something that was never fetched."""
    itunes.catalogue = {1: 503, 2: [apple_release(901, "Fine")]}
    itunes.run(["--days", "0"], watching={1: "Broken", 2: "Working"})
    assert itunes.saved == {"901"}


def test_a_body_that_is_not_json_is_a_failed_batch_not_a_crash(itunes, capsys):
    """Apple serving an HTML error page with a 200 is the shape this catches."""
    itunes.catalogue = {1: "<html>down for maintenance</html>",
                        2: 200}
    code = itunes.run(["--days", "0"], watching={1: "A", 2: "B"})
    assert code == 1                           # both failed -> broken run
    assert "lookup failed" in capsys.readouterr().err


def test_an_apple_outage_is_a_broken_run_not_a_quiet_week(itunes, capsys):
    """The bug the module docstring records: before the shared run, this
    reported "Nothing new." and looked correct. Every call failing is now a
    non-zero exit, which the workflow turns into a visible red run."""
    itunes.catalogue = {1: 503, 2: 503}
    code = itunes.run(["--days", "0"], watching={1: "A", 2: "B"})
    assert code == 1
    assert "treating this as a broken run" in capsys.readouterr().err


def test_every_artist_answering_with_nothing_is_also_a_broken_run(itunes, capsys):
    """The dangerous half: every call "succeeds" and returns an empty
    discography. Wrong IDs look exactly like this, and so does an outage that
    answers 200."""
    itunes.catalogue = {1: [], 2: []}
    code = itunes.run(["--days", "0"], watching={1: "A", 2: "B"})
    assert code == 1
    assert "returned no releases" in capsys.readouterr().err


def test_an_artist_with_no_releases_says_which_storefront_was_asked(itunes,
                                                                    apple_release,
                                                                    capsys):
    """Apple's catalogue is territory-specific -- 69 releases in US, 66 in ES --
    so "nothing found" without the store named is not actionable."""
    itunes.catalogue = {1: [], 2: [apple_release(901, "Fine")]}
    itunes.run(["--days", "0"], watching={1: "Missing", 2: "Fine"})
    assert f"in the {mod.STOREFRONT} store" in capsys.readouterr().err


def test_a_release_credited_to_two_watched_artists_is_reported_once(itunes,
                                                                    apple_release,
                                                                    capsys):
    shared = apple_release(900, "Juntos")
    itunes.catalogue = {1: [shared], 2: [shared]}
    code = itunes.run(["--days", "0"], watching={1: "A", 2: "B"})
    out = capsys.readouterr().out

    assert code == 0
    assert out.count("Juntos") == 1
    assert "1 were credited to more than one artist you watch" in out


def test_classify_can_only_return_a_kind_the_radar_keeps():
    """keep_types drops anything outside Album/EP/Single, and classify() is the
    only thing that sets `kind` here. So a fourth return value added there
    would be filtered out silently, reported as nothing, and look like a quiet
    week. This is the test that makes that loud instead."""
    kinds = {mod.classify({"collectionName": name, "trackCount": n})
             for name in ("X", "X - Single", "X - EP", "")
             for n in (0, 1, 2, 12)}
    keep = mod.ItunesRadar.keep_types
    assert keep is not None                  # None would mean "keep everything"
    assert kinds <= keep


def test_dry_run_reports_without_recording(itunes, apple_release, capsys):
    itunes.catalogue = {1: [apple_release(900, "Tinta Y Tiempo")]}
    code = itunes.run(["--days", "0", "--dry-run"], watching={1: "A"})
    assert code == 0
    assert "Tinta Y Tiempo" in capsys.readouterr().out
    assert itunes.saved is None


def test_all_ignores_the_state_file_and_writes_nothing(itunes, apple_release,
                                                       capsys):
    itunes.catalogue = {1: [apple_release(900, "Known")]}
    code = itunes.run(["--days", "0", "--all"], watching={1: "A"}, seen={"900"})
    assert code == 0
    assert "Known" in capsys.readouterr().out      # reported despite being seen
    assert itunes.saved is None


def test_an_empty_watchlist_exits_with_something_actionable(itunes):
    with pytest.raises(SystemExit, match="WATCHED_ARTISTS is empty"):
        itunes.run(["--days", "0"], watching={})


def test_the_json_report_carries_the_storefront(itunes, apple_release, tmp_path):
    """The report has to say which catalogue it read: the same query against ES
    and US are different answers, not different views of one."""
    out = tmp_path / "releases.json"
    itunes.catalogue = {1: [apple_release(900, "X")]}
    itunes.run(["--days", "0", "--json", str(out)], watching={1: "A"})
    report = json.loads(out.read_text())

    assert report["source"] == "itunes"
    assert report["store"] == mod.STOREFRONT
    assert [r["title"] for r in report["releases"]] == ["X"]


def test_the_summary_counts_artists_fetched_against_artists_watched(itunes,
                                                                    apple_release,
                                                                    capsys):
    itunes.catalogue = {1: 503, 2: [apple_release(901, "A")]}
    itunes.run(["--days", "0"], watching={1: "A", 2: "B"})
    assert "from 1 of 2 artists" in capsys.readouterr().out


def test_one_request_per_watched_artist(itunes, apple_release):
    itunes.catalogue = dict.fromkeys((1, 2, 3), [])
    itunes.catalogue[3] = [apple_release(900, "X")]
    itunes.run(["--days", "0"], watching={1: "A", 2: "B", 3: "C"})
    assert itunes.asked == [1, 2, 3]
