"""core/radar.py: the decision and the wire shape, with no source attached.

These two are now the shared load-bearing parts -- every radar's idea of "is
this news?" is verdict(), and everything radars/report.py formats comes out of
Release.row(). Testing them here rather than through a source is the point of
having extracted them.
"""

from __future__ import annotations

from core.radar import Batch, Release, verdict

KEEP = {"Album", "EP", "Single"}


def release(rid="1", date="2026-10-14", kind="Album") -> Release:
    return Release(id=rid, date=date, kind=kind, artist="A", title="T", source="s")


def test_what_you_have_been_told_is_not_news():
    assert verdict(release(), {"1"}, set(), "", KEEP) == "seen"


def test_the_same_release_twice_in_one_run_is_shared_not_filtered():
    """Order matters: `shared` is checked before the kind and date filters, or a
    release credited to two watched artists is counted as filtered the second
    time and the report's "listed once" note goes quiet."""
    assert verdict(release(), set(), {"1"}, "2026-10-01", KEEP) == "shared"


def test_an_unwanted_kind_is_dropped():
    assert verdict(release(kind="Broadcast"), set(), set(), "", KEEP) == "kind"


def test_keep_types_none_keeps_everything():
    assert verdict(release(kind="Broadcast"), set(), set(), "", None) == "new"


def test_older_than_the_cutoff_is_not_news():
    assert verdict(release(date="2026-01-01"), set(), set(), "2026-10-01", KEEP) == "old"


def test_no_cutoff_means_no_date_filter():
    assert verdict(release(date="1974-01-01"), set(), set(), "", KEEP) == "new"


def test_absent_knowledge_is_absent_from_the_row():
    """Apple does not say whether a release is hi-res. `None` must not reach the
    report as `false`, which would claim it is not."""
    row = release().row()
    assert "hires" not in row and "streamable" not in row


def test_what_a_source_does_know_is_carried():
    row = Release(id="1", date="2026-10-14", kind="Album", artist="A", title="T",
                  source="qobuz", tracks=9, hires=False, streamable=True).row()
    assert row["hires"] is False and row["streamable"] is True


def test_the_wire_calls_it_type_not_kind():
    """radars/report.py and every report already written key on "type"."""
    assert release().row()["type"] == "Album"


def test_a_feed_batch_reports_rows_examined_not_rows_kept():
    assert Batch(releases=[release()], scanned=2000).examined == 2000


def test_a_per_artist_batch_examines_what_it_returns():
    assert Batch(releases=[release(), release("2")]).examined == 2
