"""radars/report.py: a radar's JSON, as a markdown issue body."""

from __future__ import annotations

import radars.report as rep

RUN = {"generated": "2026-10-16T05:17:00+00:00", "source": "qobuz",
       "store": "gb-en", "window": "last 10 days", "watching": 3, "fetched": 3,
       "failed": 0, "shared": 0, "releases": []}


def body(**over):
    return rep.to_markdown({**RUN, **over}, over.pop("warnings", ""))


def release(**over):
    base = {"date": "2026-10-14", "type": "Album", "artist": "CHUWI",
            "title": "Libertad", "id": 901, "tracks": 13, "hires": True,
            "streamable": True, "upcoming": False}
    return {**base, **over}


def test_the_table_renders():
    """The body opens on the records. Every count about the run is bookkeeping
    and lives in the collapsed block now -- it used to push the first row below
    the fold."""
    out = body(releases=[release()])
    assert out.startswith("| date | type | artist | release | | id |")
    assert "| 2026-10-14 | Album | CHUWI | Libertad | 13 tr · hi-res | `901` |" in out
    assert "1 new release from 3 of 3 artists in the gb-en store" in out


def test_a_pipe_in_a_title_cannot_break_the_table():
    out = body(releases=[release(title="Voice In My Knives / A | B")])
    assert r"A \| B" in out


def test_upcoming_comes_from_the_run_not_the_formatter():
    """Only the run knows what "today" was; a report can be formatted days
    later, when recomputing it here would quietly relabel everything."""
    assert "*(upcoming)*" in body(releases=[release(upcoming=True)])
    assert "*(upcoming)*" not in body(releases=[release(upcoming=False)])


def test_badges_are_whatever_is_present():
    assert "not streamable" in body(releases=[release(streamable=False)])
    out = body(releases=[release(tracks=0, hires=False)])
    assert "| |" in out or "|  |" in out


def test_an_empty_week_says_so():
    """"Nothing new." stays in the body: with the counts folded away it is the
    only thing left that says the run happened and found nothing."""
    out = body(releases=[])
    assert out.startswith("Nothing new.")
    assert "0 new releases from 3 of 3 artists" in out


def test_a_partial_failure_is_stated_in_the_body():
    """Not only in the run log: an incomplete list that looks complete is
    worse than a red run."""
    out = body(failed=2, fetched=1, releases=[release()])
    assert "2 of 3 artists could not be fetched" in out
    assert "this list is incomplete" in out


def test_shared_releases_are_counted_and_pluralised():
    assert "1 release was credited" in body(shared=1, releases=[release()])
    assert "2 releases were credited" in body(shared=2, releases=[release()])


def test_warnings_are_folded_in_collapsed():
    out = rep.to_markdown(RUN, "warning: Oscar D'León returned no releases\n")
    assert "<details><summary>warnings</summary>" in out
    assert "Oscar" in out


def test_a_report_missing_every_optional_field_still_formats():
    """So an itunes or listenbrainz report in the same shape can use this."""
    out = rep.to_markdown({"releases": [{"date": "2026-01-01", "title": "X",
                                         "artist": "Y"}],
                           "watching": 1, "fetched": 1})
    assert "| 2026-01-01 | ? | Y | X |" in out


def test_the_provenance_line_is_always_there():
    assert "<sub>qobuz · generated 2026-10-16" in body(releases=[release()])


# -- credited appearances (D42) ----------------------------------------------
# A release carrying `because` was found by the credit pass: it is somebody
# else's record, and it answers a different question from the rest of the
# table. These are about keeping the two apart.

def appearance(**over):
    base = {"artist": "Miguel Atwood-Ferguson", "title": "Ananta", "id": "cvj",
            "tracks": 8, "because": "aja monet - FeaturedArtist, SpokenWord"}
    return release(**{**base, **over})


def test_appearances_get_their_own_section_and_a_credit_column():
    out = body(releases=[release(), appearance()])
    assert "**1 credited appearance** on other artists' releases." in out
    assert "| date | type | artist | release | credit | | id |" in out
    assert "| aja monet - FeaturedArtist, SpokenWord |" in out


def test_the_headline_counts_only_what_the_watched_artists_released():
    """"9 new releases from 128 artists" has meant one thing in every issue so
    far, and the credit pass must not quietly restate it -- folded away or
    not."""
    out = body(releases=[release(), appearance(), appearance(id="two")])
    assert "1 new release from 3 of 3 artists" in out
    assert "**2 credited appearances**" in out


def test_the_first_table_has_no_credit_column():
    out = body(releases=[release()])
    assert "| date | type | artist | release | | id |" in out
    assert "credit |" not in out


def test_appearances_alone_do_not_read_as_nothing_new():
    out = body(releases=[appearance()])
    assert "Nothing new." not in out
    assert "0 new releases from 3 of 3 artists" in out


def test_no_appearances_leaves_the_report_exactly_as_it_was():
    assert "credited appearance" not in body(releases=[release()])


def test_a_quiet_week_in_both_passes_still_says_nothing_new():
    assert "Nothing new." in body(releases=[])


def test_the_funnel_is_printed_so_the_numbers_get_re_measured():
    out = body(releases=[appearance()],
               credits={"appearance": 1, "writer": 96, "absent": 42})
    assert "credit candidates: 1 appearance, 96 writer, 42 absent" in out


def test_a_pipe_in_a_credit_cannot_break_the_table():
    out = body(releases=[appearance(because="x | y")])
    assert "x \\| y" in out


def test_the_folded_block_is_plain_text():
    """It renders inside a fence, so markdown in it shows as markdown."""
    out = body(releases=[release()])
    folded = out.split("```")[1]
    assert "`gb-en`" not in folded and "gb-en store" in folded
    assert "**" not in folded


def test_stderr_warnings_still_reach_the_block_below_the_counts():
    out = body(releases=[release()], warnings="warning: Two (2) lookup failed\n")
    folded = out.split("```")[1]
    assert folded.index("1 new release") < folded.index("Two (2) lookup failed")


def test_the_block_is_there_even_with_no_stderr_warnings():
    """It used to appear only when something had gone wrong. The counts live
    there now, so it is always present and always has content."""
    assert "<details><summary>warnings</summary>" in body(releases=[release()])


def test_an_incomplete_list_is_flagged_in_the_body_not_folded_away():
    """A caveat about whether the table is the whole answer, not a count."""
    out = body(releases=[release()], failed=2)
    assert "⚠ 2 of 3 artists could not be fetched" in out.split("<details>")[0]


def test_a_label_report_counts_labels_and_credited_rows():
    """The label radar (D44) has no billed rows at all -- everything it reports
    is somebody else's record -- so the headline cannot be about releases by
    artists it watches, and the noun cannot be "artists"."""
    report = {
        "source": "labels", "unit": "labels", "window": "last 14 days",
        "watching": 212, "fetched": 212, "store": "gb-en",
        "releases": [{"date": "2026-10-28", "type": "Album", "artist": "Napa",
                      "title": "Semitrópico", "id": "abc", "source": "qobuz",
                      "tracks": 9, "because": "Carles Campi Campón - Producer"}],
        "watchlist": {"ids": 212, "entries": 254, "major": 27, "self": 15},
        "credits": {"credit": 1, "absent": 180, "sideline": 9},
    }
    body = rep.to_markdown(report)
    assert "1 credited release from 212 of 212 labels" in body
    assert "Watching 212 of 254 on the list: 27 too big to mean anything" in body
    assert "an artist's own imprint" in body
    assert "credit candidates: 1 credit, 180 absent, 9 sideline" in body
    assert "Carles Campi Campón - Producer" in body


def test_an_artist_report_is_unchanged_without_a_unit():
    """Every other radar omits `unit`, and its headline must read exactly as it
    did before the label radar existed."""
    report = {
        "source": "qobuz", "window": "last 10 days", "watching": 128,
        "fetched": 128, "store": "gb-en",
        "releases": [{"date": "2026-10-28", "type": "Album", "artist": "Björk",
                      "title": "Some Record", "id": "abc", "source": "qobuz",
                      "tracks": 9}],
    }
    body = rep.to_markdown(report)
    assert "1 new release from 128 of 128 artists" in body
