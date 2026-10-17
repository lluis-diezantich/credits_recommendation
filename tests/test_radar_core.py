"""core/radar.py: the decision and the wire shape, with no source attached.

These two are now the shared load-bearing parts -- every radar's idea of "is
this news?" is verdict(), and everything radars/report.py formats comes out of
Release.row(). Testing them here rather than through a source is the point of
having extracted them.
"""

from __future__ import annotations

import json

from core.radar import Batch, Radar, Release, verdict

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


# ---- --state: where a run records what it has seen ----------------------
#
# The real load_seen/save_seen, not the conftest stubs, because the thing under
# test IS the path resolution. The flag exists for the runner: data/*_seen.json
# is gitignored on purpose, so CI needs a file of its own to commit back.


class Fake(Radar):
    """A radar with a fixed, always-successful batch of one release."""

    name = "fake"
    keep_types = None
    guard_empty_run = False

    def watching(self):
        return {1: "someone"}

    def batches(self, args, watching):
        yield Batch(releases=[release(rid="r1"), release(rid="r2")], ok=True)


def run(tmp_path, *argv):
    import core.radar as runner
    ap = runner.parser(Fake(), "fake")
    code = runner.execute(Fake(), ap.parse_args(["--days", "0", *argv]))
    return code


def test_state_goes_to_the_radars_own_file_by_default(tmp_path, monkeypatch):
    import core.radar as runner
    monkeypatch.setattr(runner, "DATA", tmp_path)
    assert run(tmp_path) == 0
    assert (tmp_path / "fake_seen.json").exists()


def test_state_can_be_pointed_somewhere_else(tmp_path, monkeypatch):
    """The runner's whole requirement: its state is ITS OWN, so committing it
    back cannot make one machine's "already reported" everyone's."""
    import core.radar as runner
    monkeypatch.setattr(runner, "DATA", tmp_path)
    elsewhere = tmp_path / "ci" / "fake_seen.json"
    assert run(tmp_path, "--state", str(elsewhere)) == 0
    assert set(json.loads(elsewhere.read_text())) == {"r1", "r2"}
    assert not (tmp_path / "fake_seen.json").exists()


def test_a_missing_directory_is_created_rather_than_losing_the_run(tmp_path, monkeypatch):
    """data/ci/ will not exist on a fresh checkout, and a run that fetched
    everything correctly must not throw it away over a missing folder."""
    import core.radar as runner
    monkeypatch.setattr(runner, "DATA", tmp_path)
    nested = tmp_path / "a" / "b" / "c" / "fake_seen.json"
    assert run(tmp_path, "--state", str(nested)) == 0
    assert nested.exists()


def test_what_the_named_file_already_holds_is_not_re_reported(tmp_path, monkeypatch, capsys):
    import core.radar as runner
    monkeypatch.setattr(runner, "DATA", tmp_path)
    elsewhere = tmp_path / "ci" / "fake_seen.json"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_text(json.dumps(["r1"]))
    assert run(tmp_path, "--state", str(elsewhere)) == 0
    out = capsys.readouterr().out
    assert "1 new release." in out          # r1 was already recorded there
    assert set(json.loads(elsewhere.read_text())) == {"r1", "r2"}


def test_all_ignores_the_named_file_and_writes_nothing_to_it(tmp_path, monkeypatch):
    """--all is what the workflow passed while it had nowhere durable to keep
    state. It must stay a read-only mode, or a stateless run would overwrite
    the state a stateful one is keeping."""
    import core.radar as runner
    monkeypatch.setattr(runner, "DATA", tmp_path)
    elsewhere = tmp_path / "ci" / "fake_seen.json"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_text(json.dumps(["r1"]))
    assert run(tmp_path, "--state", str(elsewhere), "--all") == 0
    assert set(json.loads(elsewhere.read_text())) == {"r1"}


def test_dry_run_records_nothing_at_the_named_path_either(tmp_path, monkeypatch):
    import core.radar as runner
    monkeypatch.setattr(runner, "DATA", tmp_path)
    elsewhere = tmp_path / "ci" / "fake_seen.json"
    assert run(tmp_path, "--state", str(elsewhere), "--dry-run") == 0
    assert not elsewhere.exists()
