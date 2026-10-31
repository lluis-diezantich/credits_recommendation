"""radars/labels.py end to end, offline: catalogue in, rows out.

These cover the SHAPE of a run, which tests/test_labels.py cannot: one
`label/get` per label, one `album_detail` per surviving candidate, which ones
are dropped before a request is spent, and what gets recorded.
"""

from __future__ import annotations

import pytest

PRODUCER = "Carles Campi Campón"
PEOPLE = {"carles campi campon": PRODUCER, "campi": PRODUCER}


def test_reports_a_release_a_watched_producer_made(labels, catalogue_row,
                                                   album_detail_row, capsys):
    labels.catalogues = {7: [catalogue_row("new", "Semitrópico")]}
    labels.albums = {"new": album_detail_row(
        "new", "Semitrópico", f"Napa, MainArtist - {PRODUCER}, Producer")}
    assert labels.run(["--days", "0"], watching={7: "Napa"}, people=PEOPLE) == 0
    out = capsys.readouterr().out
    assert "Semitrópico" in out
    assert f"{PRODUCER} - Producer" in out
    assert "1 new release" in out


def test_drops_a_release_billed_to_an_artist_you_already_watch(labels, catalogue_row,
                                                               album_detail_row):
    """And without spending a request on it -- the Friday radar has this row."""
    labels.catalogues = {7: [catalogue_row("mine", "Tinta y Tiempo",
                                           artists=[("41620", "Jorge Drexler")])]}
    labels.albums = {"mine": album_detail_row("mine", "Tinta y Tiempo", "whatever")}
    assert labels.run(["--days", "0"], watching={7: "Napa"}, people=PEOPLE,
                      favourite_ids={41620: "Jorge Drexler"}) == 0
    assert labels.detailed == []


def test_a_writer_only_credit_is_a_cover_and_is_not_reported(labels, catalogue_row,
                                                             album_detail_row, capsys):
    labels.catalogues = {7: [catalogue_row("cover", "Tu Falta de Querer")]}
    labels.albums = {"cover": album_detail_row(
        "cover", "Tu Falta de Querer", f"Someone, MainArtist - {PRODUCER}, ComposerLyricist")}
    assert labels.run(["--days", "0"], watching={7: "Napa"}, people=PEOPLE) == 0
    out = capsys.readouterr().out
    assert "Nothing new." in out
    assert "1 writing" in out


def test_mixing_is_a_sideline_until_the_run_asks_for_it(labels, catalogue_row,
                                                        album_detail_row, capsys):
    labels.catalogues = {7: [catalogue_row("mixed", "Some Record")]}
    labels.albums = {"mixed": album_detail_row(
        "mixed", "Some Record", f"Someone, MainArtist - {PRODUCER}, Mixing Engineer")}

    assert labels.run(["--days", "0"], watching={7: "Napa"}, people=PEOPLE) == 0
    assert "1 sideline" in capsys.readouterr().out

    assert labels.run(["--days", "0", "--credit", "engineering"],
                      watching={7: "Napa"}, people=PEOPLE) == 0
    assert "Some Record" in capsys.readouterr().out


def test_an_unknown_credit_family_is_refused_rather_than_ignored(labels):
    with pytest.raises(SystemExit) as exit_info:
        labels.run(["--credit", "producing"], watching={7: "Napa"}, people=PEOPLE)
    assert "unknown credit family" in str(exit_info.value)


def test_the_real_date_overrides_a_delivery_date(labels, catalogue_row,
                                                 album_detail_row, capsys):
    """D42's 866 of 1163. The catalogue says today, album/get says 2019."""
    labels.catalogues = {7: [catalogue_row("old", "Fui Yo", date="2026-10-30")]}
    labels.albums = {"old": album_detail_row(
        "old", "Fui Yo", f"Someone, MainArtist - {PRODUCER}, Producer",
        date="2019-01-14")}
    assert labels.run(["--days", "14"], watching={7: "Napa"}, people=PEOPLE) == 0
    out = capsys.readouterr().out
    assert "Nothing new." in out
    assert "1 redelivery" in out


def test_two_editions_of_one_release_cost_one_request(labels, catalogue_row,
                                                      album_detail_row):
    labels.catalogues = {7: [catalogue_row("hi", "Before The World Blows"),
                             catalogue_row("lo", "before the world blows")]}
    labels.albums = {
        "lo": album_detail_row("lo", "Before The World Blows",
                               f"Erykah Badu, MainArtist - {PRODUCER}, Producer"),
        "hi": album_detail_row("hi", "Before The World Blows",
                               f"Erykah Badu, MainArtist - {PRODUCER}, Producer"),
    }
    assert labels.run(["--days", "0"], watching={7: "Napa"}, people=PEOPLE) == 0
    assert len(labels.detailed) == 1


def test_the_same_record_on_two_labels_is_listed_once(labels, catalogue_row,
                                                      album_detail_row, capsys):
    """A distributor delivers one record to two labels under two ids, which
    core/radar.py dedups on id and cannot see."""
    performers = f"Napa, MainArtist - {PRODUCER}, Producer"
    labels.catalogues = {7: [catalogue_row("one", "Semitrópico")],
                         8: [catalogue_row("two", "Semitrópico")]}
    labels.albums = {"one": album_detail_row("one", "Semitrópico", performers),
                     "two": album_detail_row("two", "Semitrópico", performers)}
    assert labels.run(["--days", "0"], watching={7: "A", 8: "B"}, people=PEOPLE) == 0
    out = capsys.readouterr().out
    assert out.count("Semitrópico") == 1
    assert "1 duplicate" in out


def test_nothing_is_recorded_for_a_release_nobody_was_credited_on(labels, catalogue_row,
                                                                  album_detail_row):
    """record_scanned is False here: banking an uncredited release would hide
    it for good the day its producer is added to data/producers.json."""
    labels.catalogues = {7: [catalogue_row("nobody", "Some Record")]}
    labels.albums = {"nobody": album_detail_row(
        "nobody", "Some Record", "Stranger, MainArtist - Someone Else, Producer")}
    assert labels.run(["--days", "0"], watching={7: "Napa"}, people=PEOPLE) == 0
    assert labels.saved is None


def test_a_reported_release_is_recorded(labels, catalogue_row, album_detail_row):
    labels.catalogues = {7: [catalogue_row("new", "Semitrópico")]}
    labels.albums = {"new": album_detail_row(
        "new", "Semitrópico", f"Napa, MainArtist - {PRODUCER}, Producer")}
    assert labels.run(["--days", "0"], watching={7: "Napa"}, people=PEOPLE) == 0
    assert labels.saved == {"new"}


def test_every_label_failing_is_a_broken_run(labels):
    labels.catalogues = {7: (None, "error"), 8: (None, "error")}
    assert labels.run(["--days", "0"], watching={7: "A", 8: "B"}, people=PEOPLE) == 1


def test_one_label_failing_does_not_end_the_run(labels, catalogue_row,
                                                album_detail_row, capsys):
    labels.catalogues = {7: (None, "error"), 8: [catalogue_row("new", "Semitrópico")]}
    labels.albums = {"new": album_detail_row(
        "new", "Semitrópico", f"Napa, MainArtist - {PRODUCER}, Producer")}
    assert labels.run(["--days", "0"], watching={7: "A", 8: "B"}, people=PEOPLE) == 0
    assert "Semitrópico" in capsys.readouterr().out


def test_an_unreadable_candidate_is_counted_not_crashed_on(labels, catalogue_row):
    labels.catalogues = {7: [catalogue_row("gone", "Some Record")]}
    labels.albums = {}
    assert labels.run(["--days", "0"], watching={7: "Napa"}, people=PEOPLE) == 0
    assert labels.saved is None


def test_an_empty_people_file_warns_rather_than_reporting_everything(labels, catalogue_row,
                                                                     album_detail_row,
                                                                     capsys):
    labels.catalogues = {7: [catalogue_row("new", "Semitrópico")]}
    labels.albums = {"new": album_detail_row(
        "new", "Semitrópico", f"Napa, MainArtist - {PRODUCER}, Producer")}
    assert labels.run(["--days", "0"], watching={7: "Napa"}, people={}) == 0
    captured = capsys.readouterr()
    assert "nothing can be credited" in captured.err
    assert "Nothing new." in captured.out


def test_no_labels_to_scan_exits_with_the_builder_hint(labels):
    with pytest.raises(SystemExit) as exit_info:
        labels.run(["--days", "0"], watching={}, people=PEOPLE)
    assert "--discover" in str(exit_info.value)


def test_a_catalogue_longer_than_a_page_is_paged(labels, catalogue_row, album_detail_row):
    import core.qobuz as client
    rows = [catalogue_row(f"a{n}", f"Record {n}") for n in range(client.LABEL_PAGE + 5)]
    labels.catalogues = {7: rows}
    labels.albums = {}
    assert labels.run(["--days", "0"], watching={7: "Napa"}, people=PEOPLE) == 0
    assert labels.asked == [7, 7]


def test_paging_stops_once_the_window_is_cleared(labels, catalogue_row):
    """The catalogue is date-descending, so page two is older than page one."""
    import core.qobuz as client
    rows = [catalogue_row(f"a{n}", f"Record {n}", date="2019-01-01")
            for n in range(client.LABEL_PAGE + 5)]
    labels.catalogues = {7: rows}
    labels.albums = {}
    assert labels.run(["--days", "14"], watching={7: "Napa"}, people=PEOPLE) == 0
    assert labels.asked == [7]


def test_one_label_cannot_fill_the_report(labels, catalogue_row, album_detail_row, capsys):
    """Five of the first run's thirteen rows were one act on one label."""
    performers = f"Beckdown, MainArtist - {PRODUCER}, Producer"
    labels.catalogues = {7: [catalogue_row(f"s{n}", f"Single {n}",
                                           date=f"2026-10-2{n}") for n in range(5)]}
    labels.albums = {f"s{n}": album_detail_row(f"s{n}", f"Single {n}", performers,
                                               date=f"2026-10-2{n}") for n in range(5)}
    assert labels.run(["--days", "0", "--per-label", "2"],
                      watching={7: "Sumi Ani"}, people=PEOPLE) == 0
    out = capsys.readouterr().out
    assert "2 new releases" in out
    assert "3 capped" in out
    # The newest two, not whichever the catalogue returned first.
    assert "Single 4" in out and "Single 3" in out and "Single 0" not in out


def test_the_cap_can_be_turned_off(labels, catalogue_row, album_detail_row, capsys):
    performers = f"Beckdown, MainArtist - {PRODUCER}, Producer"
    labels.catalogues = {7: [catalogue_row(f"s{n}", f"Single {n}") for n in range(5)]}
    labels.albums = {f"s{n}": album_detail_row(f"s{n}", f"Single {n}", performers)
                     for n in range(5)}
    assert labels.run(["--days", "0", "--per-label", "0"],
                      watching={7: "Sumi Ani"}, people=PEOPLE) == 0
    assert "5 new releases" in capsys.readouterr().out


def test_the_row_names_the_producer_not_the_busiest_person(labels, catalogue_row,
                                                           album_detail_row, capsys):
    """The first run attributed Día de Muertos to its Music Director."""
    labels.catalogues = {7: [catalogue_row("mix", "Día de Muertos")]}
    labels.albums = {"mix": album_detail_row("mix", "Día de Muertos", [
        f"Someone, MainArtist - {PRODUCER}, Music Director",
        f"Someone, MainArtist - {PRODUCER}, Music Director",
        "Someone, MainArtist - Real Producer, Producer",
    ])}
    people = {**PEOPLE, "real producer": "Real Producer"}
    assert labels.run(["--days", "0"], watching={7: "Napa"}, people=people) == 0
    out = capsys.readouterr().out
    assert "Real Producer - Producer" in out
    assert "Music Director" not in out


def test_a_remaster_is_not_news(labels, catalogue_row, album_detail_row, capsys):
    """Fania delivered a 1960s Ismael Rivera record on 2026-10-30, so the real
    date cannot catch it -- the delivery and the remaster are the same day."""
    labels.catalogues = {7: [catalogue_row("old", "La Quiniela del Día (Remastered 2026)")]}
    labels.albums = {"old": album_detail_row(
        "old", "La Quiniela del Día (Remastered 2026)",
        f"Ismael Rivera, MainArtist - {PRODUCER}, Producer")}
    assert labels.run(["--days", "0"], watching={7: "Fania"}, people=PEOPLE) == 0
    out = capsys.readouterr().out
    assert "Nothing new." in out
    assert "1 reissue" in out


def test_a_remaster_marked_only_in_the_version_field_is_still_a_reissue(
        labels, catalogue_row, album_detail_row, capsys):
    """Qobuz returns `La Quiniela del Día` with version `Remastered 2026`. The
    first run read the title alone and printed it as news."""
    labels.catalogues = {7: [catalogue_row("old", "La Quiniela del Día")]}
    detail = album_detail_row("old", "La Quiniela del Día",
                              f"Ismael Rivera, MainArtist - {PRODUCER}, Producer")
    detail["version"] = "Remastered 2026"
    labels.albums = {"old": detail}
    assert labels.run(["--days", "0"], watching={7: "Fania"}, people=PEOPLE) == 0
    out = capsys.readouterr().out
    assert "Nothing new." in out
    assert "1 reissue" in out


def test_a_muted_artists_record_is_still_not_reported(labels, catalogue_row,
                                                      album_detail_row, monkeypatch):
    """A mute means you do not want that artist. The Friday radar honours it,
    so reaching them through their producer would undo it by accident."""
    import core.favourites as favourites
    monkeypatch.setattr(favourites, "load",
                        lambda *a, **k: [{"name": "Carin León", "qobuz_id": 2222870,
                                          "watch": False}])
    labels.catalogues = {7: [catalogue_row("mudah", "MudaH",
                                           artists=[("2222870", "Carin León")])]}
    labels.albums = {"mudah": album_detail_row("mudah", "MudaH", "whatever")}
    assert labels.run(["--days", "0"], watching={7: "Socios Music"},
                      people=PEOPLE) == 0
    assert labels.detailed == []


def test_the_row_says_which_of_your_artists_the_producer_works_with(
        labels, catalogue_row, album_detail_row, capsys):
    """"James Ford - Producer" is a stranger. The names are the reason the row
    is in the report."""
    labels.catalogues = {7: [catalogue_row("new", "Marianne")]}
    labels.albums = {"new": album_detail_row(
        "new", "Marianne", f"FONTAINES D.C., MainArtist - {PRODUCER}, Producer")}
    assert labels.run(["--days", "0"], watching={7: "XL"}, people=PEOPLE,
                      worked_for={PRODUCER: ["Björk", "Little Simz"]}) == 0
    assert "works with Björk, Little Simz" in capsys.readouterr().out


def test_a_long_list_of_your_artists_is_trimmed(labels, catalogue_row,
                                                album_detail_row, capsys):
    labels.catalogues = {7: [catalogue_row("new", "Marianne")]}
    labels.albums = {"new": album_detail_row(
        "new", "Marianne", f"Someone, MainArtist - {PRODUCER}, Producer")}
    assert labels.run(["--days", "0"], watching={7: "XL"}, people=PEOPLE,
                      worked_for={PRODUCER: ["A", "B", "C", "D", "E"]}) == 0
    out = capsys.readouterr().out
    assert "works with A, B, C +2 more" in out


def test_a_remix_is_not_a_record_they_made(labels, catalogue_row,
                                           album_detail_row, capsys):
    """D30 decided this on roles; this is the other shape of it -- a Producer
    credit on a release that is itself a rework."""
    title = "The Boy (Louie Vega, Josh Milan & 2SoulFusion Dub Remix)"
    labels.catalogues = {7: [catalogue_row("rmx", title)]}
    labels.albums = {"rmx": album_detail_row(
        "rmx", title, f"Rochelle Jordan, MainArtist - {PRODUCER}, Producer")}
    assert labels.run(["--days", "0"], watching={7: "EMPIRE"}, people=PEOPLE) == 0
    out = capsys.readouterr().out
    assert "Nothing new." in out
    assert "1 remix" in out


STRANGER = "Stranger, MainArtist - Nobody You Know, Producer"


def test_the_feed_reports_an_album_nobody_you_follow_made(labels, catalogue_row,
                                                          album_detail_row, capsys):
    """D45: the label is reason enough for an album, with no credit attached."""
    labels.catalogues = {7: [catalogue_row("alb", "Some Album")]}
    labels.albums = {"alb": album_detail_row("alb", "Some Album", STRANGER, tracks=10)}
    assert labels.run(["--days", "0"], watching={7: "Mute"}, people=PEOPLE) == 0
    out = capsys.readouterr().out
    assert "Some Album" in out
    assert "↳" not in out          # no credit line: nothing earned it one
    assert "1 on the feed" in out


def test_the_feed_leaves_singles_out_by_default(labels, catalogue_row,
                                                album_detail_row, capsys):
    """Singles were 175 of 300 releases in the measured fortnight."""
    labels.catalogues = {7: [catalogue_row("sng", "Some Single")]}
    labels.albums = {"sng": album_detail_row("sng", "Some Single", STRANGER, tracks=1)}
    assert labels.run(["--days", "0"], watching={7: "Mute"}, people=PEOPLE) == 0
    assert "Nothing new." in capsys.readouterr().out


def test_feed_all_takes_the_singles_too(labels, catalogue_row, album_detail_row,
                                        capsys):
    labels.catalogues = {7: [catalogue_row("sng", "Some Single")]}
    labels.albums = {"sng": album_detail_row("sng", "Some Single", STRANGER, tracks=1)}
    assert labels.run(["--days", "0", "--feed", "all"],
                      watching={7: "Mute"}, people=PEOPLE) == 0
    assert "Some Single" in capsys.readouterr().out


def test_feed_off_is_the_old_credits_only_behaviour(labels, catalogue_row,
                                                    album_detail_row, capsys):
    labels.catalogues = {7: [catalogue_row("alb", "Some Album")]}
    labels.albums = {"alb": album_detail_row("alb", "Some Album", STRANGER, tracks=10)}
    assert labels.run(["--days", "0", "--feed", "off"],
                      watching={7: "Mute"}, people=PEOPLE) == 0
    assert "Nothing new." in capsys.readouterr().out


def test_a_credited_single_is_reported_although_the_feed_drops_singles(
        labels, catalogue_row, album_detail_row, capsys):
    """Westerman's `L/C` is a single, and Marta Salogni producing it is the
    whole point of the radar."""
    labels.catalogues = {7: [catalogue_row("sng", "L/C")]}
    labels.albums = {"sng": album_detail_row(
        "sng", "L/C", f"Westerman, MainArtist - {PRODUCER}, Producer", tracks=1)}
    assert labels.run(["--days", "0"], watching={7: "Partisan"}, people=PEOPLE) == 0
    out = capsys.readouterr().out
    assert "L/C" in out
    assert f"{PRODUCER} - Producer" in out


def test_a_busy_feed_cannot_push_out_a_credited_release(labels, catalogue_row,
                                                        album_detail_row, capsys):
    """The cap is per group, so one label's feed rows and its credited row do
    not compete for the same two slots."""
    rows = [catalogue_row(f"f{n}", f"Feed {n}", date=f"2026-10-2{n}")
            for n in range(4)]
    rows.append(catalogue_row("good", "The Credited One", date="2026-10-10"))
    labels.catalogues = {7: rows}
    labels.albums = {f"f{n}": album_detail_row(f"f{n}", f"Feed {n}", STRANGER,
                                               tracks=10, date=f"2026-10-2{n}")
                     for n in range(4)}
    labels.albums["good"] = album_detail_row(
        "good", "The Credited One", f"Someone, MainArtist - {PRODUCER}, Producer",
        tracks=10, date="2026-10-10")
    assert labels.run(["--days", "0", "--per-label", "2"],
                      watching={7: "Mute"}, people=PEOPLE) == 0
    out = capsys.readouterr().out
    assert "The Credited One" in out
    assert out.count("Feed ") == 2


def test_the_feed_count_excludes_what_the_cap_removed(labels, catalogue_row,
                                                      album_detail_row, capsys):
    """A first run said "103 on the feed" beside 50 printed rows."""
    rows = [catalogue_row(f"f{n}", f"Feed {n}", date=f"2026-10-2{n}")
            for n in range(5)]
    labels.catalogues = {7: rows}
    labels.albums = {f"f{n}": album_detail_row(f"f{n}", f"Feed {n}", STRANGER,
                                               tracks=10, date=f"2026-10-2{n}")
                     for n in range(5)}
    assert labels.run(["--days", "0", "--per-label", "2"],
                      watching={7: "Mute"}, people=PEOPLE) == 0
    out = capsys.readouterr().out
    assert "2 on the feed" in out
    assert "2 new releases" in out
