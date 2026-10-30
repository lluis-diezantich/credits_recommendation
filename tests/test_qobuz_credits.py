"""radars/qobuz.py's credit pass: what the track index adds, and what it costs.

The first pass asks each watched artist what they released. This one asks the
track index who ELSE's records credit them, which is the only way a track-level
feature is visible at all -- and because it searches a NAME, most of what comes
back has to be thrown out. These tests are about the throwing out, and about
not spending a request to do it. D42.
"""

from __future__ import annotations

ANANTA = ("Miguel Atwood-Ferguson, MainArtist, Producer, ComposerLyricist - "
          "Aja Monet, FeaturedArtist, SpokenWord")
COVER = "Wanna, MainArtist - Mon Laferte, ComposerLyricist"


def hit(album_id, date="2026-10-14", album_title="Ananta", billed=((99, "Atwood"),),
        track="a force"):
    """One `track/search` row: a track, and the album block Qobuz embeds.

    The album block's date is the DELIVERY date, which is why the pass reads
    the album itself before believing anything.
    """
    return {"id": f"t-{album_id}", "title": track,
            "album": {"id": str(album_id), "title": album_title,
                      "artist": {"id": billed[0][0], "name": billed[0][1]},
                      "artists": [{"id": i, "name": n} for i, n in billed],
                      "release_date_original": date}}


def detail(album_id, date="2026-10-14", album_title="Ananta", tracks=8,
           billed=((99, "Atwood"),), performers=ANANTA, track="a force"):
    """One `album/get` payload: the real date, and the per-track credits."""
    return {"id": str(album_id), "title": album_title, "tracks_count": tracks,
            "release_date_original": date, "hires": True, "streamable": True,
            "artists": [{"id": i, "name": n} for i, n in billed],
            "tracks": {"items": [{"title": track, "performers": performers}]}}


class TestWhatItFinds:
    def test_a_track_level_feature_is_reported(self, qobuz, capsys):
        """The case the whole pass exists for: `a force` credits aja monet as
        FeaturedArtist and does not appear in her own discography at all."""
        qobuz.discography = {1: []}
        qobuz.index = {"aja monet": [hit(500)]}
        qobuz.albums = {"500": detail(500)}
        code = qobuz.run(["--days", "0"], watching={1: "aja monet"})
        out = capsys.readouterr().out

        assert code == 0
        assert "Atwood - Ananta" in out
        assert "1 new release" in out

    def test_the_report_says_whose_credit_put_it_there(self, qobuz, capsys):
        """"Atwood - Ananta" in a report about artists you follow is a stranger
        unless the row carries the credit."""
        qobuz.discography = {1: []}
        qobuz.index = {"aja monet": [hit(500)]}
        qobuz.albums = {"500": detail(500)}
        qobuz.run(["--days", "0"], watching={1: "aja monet"})
        out = capsys.readouterr().out

        assert "aja monet - FeaturedArtist, SpokenWord" in out

    def test_the_billed_credit_is_preferred_over_the_first_track(self, qobuz, capsys):
        """A record can credit someone on several tracks; the report should name
        the billing, not whichever track came back first."""
        payload = detail(500)
        payload["tracks"]["items"] = [
            {"title": "intro", "performers": "Atwood, MainArtist - Aja Monet, Other"},
            {"title": "a force", "performers": ANANTA},
        ]
        qobuz.discography = {1: []}
        qobuz.index = {"aja monet": [hit(500)]}
        qobuz.albums = {"500": payload}
        qobuz.run(["--days", "0"], watching={1: "aja monet"})

        assert "FeaturedArtist" in capsys.readouterr().out

    def test_both_passes_report_into_one_run(self, qobuz, album, capsys):
        qobuz.discography = {1: [album(700, 1, "Her Own Record")]}
        qobuz.index = {"aja monet": [hit(500)]}
        qobuz.albums = {"500": detail(500)}
        qobuz.run(["--days", "0"], watching={1: "aja monet"})
        out = capsys.readouterr().out

        assert "Her Own Record" in out
        assert "Ananta" in out
        assert "2 new releases" in out


class TestWhatItThrowsOut:
    def test_a_cover_is_not_an_appearance(self, qobuz, capsys):
        """Every karaoke, piano and cumbia version of their songs credits them
        as ComposerLyricist. 96 of 238 credited hits in D42."""
        qobuz.discography = {1: []}
        qobuz.index = {"Mon Laferte": [hit(501, album_title="Tu Falta De Querer")]}
        qobuz.albums = {"501": detail(501, album_title="Tu Falta De Querer",
                                      performers=COVER, billed=((98, "Los Del Cajon"),))}
        qobuz.run(["--days", "0"], watching={1: "Mon Laferte"})
        out = capsys.readouterr().out

        assert "Nothing new." in out
        assert "1 writer" in out

    def test_a_name_the_index_matched_but_the_credits_do_not(self, qobuz, capsys):
        """Qobuz matched "Ajá John Arias" -- a composer -- for "aja monet"."""
        qobuz.discography = {1: []}
        qobuz.index = {"aja monet": [hit(502, album_title="Culpables")]}
        qobuz.albums = {"502": detail(502, album_title="Culpables",
                                      performers="Wanna, MainArtist")}
        qobuz.run(["--days", "0"], watching={1: "aja monet"})

        assert "1 absent" in capsys.readouterr().out

    def test_a_repackage_of_old_recordings_is_not_news(self, qobuz, capsys):
        qobuz.discography = {1: []}
        qobuz.index = {"Rauw Alejandro": [hit(503, album_title="Camilo: El Setlist 2026")]}
        qobuz.albums = {"503": detail(503, album_title="Camilo: El Setlist 2026",
                                      tracks=25,
                                      performers="Camilo, MainArtist - "
                                                 "Rauw Alejandro, MainArtist")}
        qobuz.run(["--days", "0"], watching={1: "Rauw Alejandro"})

        assert "1 retrospective" in capsys.readouterr().out

    def test_a_re_delivery_is_filtered_on_the_real_date(self, qobuz, capsys):
        """Sebastian Jantos re-delivered his 2021 album on 2026-10-25. The
        search row says 2026-10-25; the album says 2021-01-14. Believing the
        search row would report a five-year-old record as new, every week."""
        qobuz.discography = {1: []}
        qobuz.index = {"Jorge Drexler": [hit(504, date="2026-10-25",
                                             album_title="Fui Yo")]}
        qobuz.albums = {"504": detail(504, date="2021-01-14", album_title="Fui Yo",
                                      performers="Sebastian Jantos, MainArtist - "
                                                 "Jorge Drexler, FeaturedArtist")}
        qobuz.run(["--days", "30"], watching={1: "Jorge Drexler"})
        out = capsys.readouterr().out

        assert "Fui Yo" not in out
        assert "Nothing new." in out

    def test_the_same_record_under_two_ids_prints_once(self, qobuz, capsys):
        qobuz.discography = {1: []}
        qobuz.index = {"aja monet": [hit(505), hit(506)]}
        qobuz.albums = {"505": detail(505), "506": detail(506)}
        qobuz.run(["--days", "0"], watching={1: "aja monet"})
        out = capsys.readouterr().out

        assert out.count("Ananta") == 1
        assert "1 duplicate" in out

    def test_an_unreadable_album_is_counted_not_crashed(self, qobuz, capsys):
        qobuz.discography = {1: []}
        qobuz.index = {"aja monet": [hit(507)]}
        qobuz.albums = {}                       # album/get 404s
        code = qobuz.run(["--days", "0"], watching={1: "aja monet"})

        assert code == 0
        assert "1 unreadable" in capsys.readouterr().out


class TestWhatItDoesNotSpend:
    def test_a_release_a_watched_artist_is_billed_on_is_never_read(self, qobuz, album):
        """Pass one already has it -- D42's Tame Impala / Justice overlap. The
        point of dropping it here is that it costs no album/get."""
        qobuz.discography = {1: [album(600, 1, "Pusher")], 2: []}
        qobuz.index = {"Tame Impala": [hit(600, billed=((1, "Justice"),))]}
        qobuz.albums = {"600": detail(600)}
        qobuz.run(["--days", "0"], watching={1: "Justice", 2: "Tame Impala"})

        assert qobuz.detailed == []

    def test_a_candidate_outside_the_window_is_never_read(self, qobuz):
        """The delivery date errs in one direction only -- never older than the
        real one -- so this cannot drop a release that belongs in the window."""
        qobuz.discography = {1: []}
        qobuz.index = {"aja monet": [hit(508, date="2020-01-01")]}
        qobuz.albums = {"508": detail(508)}
        qobuz.run(["--days", "30"], watching={1: "aja monet"})

        assert qobuz.detailed == []

    def test_no_credits_searches_nothing(self, qobuz, album, capsys):
        qobuz.discography = {1: [album(601, 1, "Her Own Record")]}
        qobuz.index = {"aja monet": [hit(509)]}
        qobuz.albums = {"509": detail(509)}
        qobuz.run(["--no-credits", "--days", "0"], watching={1: "aja monet"})
        out = capsys.readouterr().out

        assert qobuz.searched == []
        assert qobuz.detailed == []
        assert "Her Own Record" in out
        assert "Credit pass" not in out

    def test_one_album_is_read_once_however_many_tracks_matched(self, qobuz):
        """A guest on four tracks of one record is one candidate, not four."""
        qobuz.discography = {1: []}
        qobuz.index = {"aja monet": [hit(510, track=f"track {n}") for n in range(4)]}
        qobuz.albums = {"510": detail(510)}
        qobuz.run(["--days", "0"], watching={1: "aja monet"})

        assert qobuz.detailed == ["510"]


class TestTheRunItself:
    def test_the_run_still_counts_artists_not_calls(self, qobuz, album, capsys):
        """Two passes per artist, one Batch per artist. Yielding them separately
        made a 128-artist run report "256 of 128"."""
        qobuz.discography = {1: [album(602, 1)], 2: [album(603, 2)]}
        qobuz.index = {"One": [], "Two": []}
        qobuz.run(["--days", "0"], watching={1: "One", 2: "Two"})

        assert "from 2 of 2 artists" in capsys.readouterr().out

    def test_scanned_counts_the_index_rows_it_read(self, qobuz, album, capsys):
        """Pass two reads hundreds of rows to keep none most weeks. Counting
        only what it kept would report a working run as a dead one."""
        qobuz.discography = {1: [album(604, 1)]}
        qobuz.index = {"aja monet": [hit(511, album_title="Culpables")] * 3}
        qobuz.albums = {"511": detail(511, album_title="Culpables",
                                      performers="Wanna, MainArtist")}
        qobuz.run(["--days", "0"], watching={1: "aja monet"})

        assert "Scanned 4 releases" in capsys.readouterr().out

    def test_a_failed_search_keeps_the_artists_own_releases(self, qobuz, album, capsys):
        qobuz.discography = {1: [album(605, 1, "Her Own Record")]}
        qobuz.index = {"aja monet": (None, "error")}
        code = qobuz.run(["--days", "0"], watching={1: "aja monet"})
        out, err = capsys.readouterr()

        assert code == 0
        assert "Her Own Record" in out
        assert "credit search failed" in err

    def test_an_appearance_is_recorded_as_seen(self, qobuz, capsys):
        """Same state file and the same id namespace as pass one, so a repeat
        week does not re-report it."""
        qobuz.discography = {1: []}
        qobuz.index = {"aja monet": [hit(512)]}
        qobuz.albums = {"512": detail(512)}
        qobuz.run(["--days", "0"], watching={1: "aja monet"})

        assert qobuz.saved == {"512"}

    def test_the_funnel_reaches_the_json_report(self, qobuz, tmp_path, capsys):
        import json
        path = tmp_path / "report.json"
        qobuz.discography = {1: []}
        qobuz.index = {"aja monet": [hit(513)]}
        qobuz.albums = {"513": detail(513)}
        qobuz.run(["--days", "0", "--json", str(path)], watching={1: "aja monet"})
        report = json.loads(path.read_text())

        assert report["credits"] == {"appearance": 1}
        assert report["releases"][0]["because"] == "aja monet - FeaturedArtist, SpokenWord"


class TestCompilations:
    def test_a_various_artists_record_is_not_an_appearance(self, qobuz, capsys):
        """`Canciones para recordar` -- 32 tracks, Various Artists -- printed as
        a Jorge Drexler album in the first live run of this pass."""
        qobuz.discography = {1: []}
        qobuz.index = {"Jorge Drexler": [hit(520, album_title="Canciones para recordar")]}
        payload = detail(520, album_title="Canciones para recordar", tracks=32,
                         billed=(), performers="Jorge Drexler, MainArtist",
                         track="Fusion")
        payload["artist"] = {"id": 7, "name": "Various Artists"}
        qobuz.albums = {"520": payload}
        qobuz.run(["--days", "0"], watching={1: "Jorge Drexler"})
        out = capsys.readouterr().out

        assert "Canciones para recordar" not in out
        assert "1 compilation" in out

    def test_an_appearance_is_billed_to_whoever_made_the_record(self, qobuz, capsys):
        """The artist column has to name the album's artist, not the watched
        name -- otherwise every appearance reads as their own release."""
        qobuz.discography = {1: []}
        qobuz.index = {"aja monet": [hit(521)]}
        qobuz.albums = {"521": detail(521)}
        qobuz.run(["--days", "0"], watching={1: "aja monet"})
        out = capsys.readouterr().out

        assert "Atwood - Ananta" in out
        assert "aja monet - Ananta" not in out


def test_a_redelivery_is_counted_by_the_pass_not_silently_dropped(qobuz, capsys):
    """The search payload let it through on a delivery date, so the pass has to
    own correcting itself -- "1 appearance" beside no printed row is a lie."""
    qobuz.discography = {1: []}
    qobuz.index = {"Jorge Drexler": [hit(530, date="2026-10-25", album_title="Fui Yo")]}
    qobuz.albums = {"530": detail(530, date="2021-01-14", album_title="Fui Yo",
                                  billed=((50, "Sebastian Jantos"),),
                                  performers="Sebastian Jantos, MainArtist - "
                                             "Jorge Drexler, FeaturedArtist")}
    qobuz.run(["--days", "30"], watching={1: "Jorge Drexler"})
    out = capsys.readouterr().out

    assert "1 redelivery" in out
    assert "appearance" not in out


def test_the_funnel_sums_to_the_candidates_read(qobuz, capsys):
    """One candidate, one count. A number that does not add up is a number
    nobody can re-measure, and the funnel is the whole evidence for D42."""
    qobuz.discography = {1: []}
    qobuz.index = {"aja monet": [hit(540), hit(541),            # one folds
                                 hit(542, album_title="Culpables")]}
    qobuz.albums = {
        "540": detail(540), "541": detail(541),
        "542": detail(542, album_title="Culpables", performers="Wanna, MainArtist"),
    }
    qobuz.run(["--days", "0", "--json", "/dev/null"], watching={1: "aja monet"})
    out = capsys.readouterr().out

    assert "1 appearance, 1 absent, 1 duplicate" in out
    assert qobuz.detailed == ["540", "541", "542"]
