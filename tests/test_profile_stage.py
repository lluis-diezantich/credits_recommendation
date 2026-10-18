"""stages/profile.py: the three jobs, with the network and the store stubbed.

Two of the cases here are defects this stage exists to avoid:

  the sample zip   stages/load.py takes sorted(glob)[-1], and
                   "listenbrainz_sample.zip" sorts AFTER the real export, so a
                   2,000-listen sample silently shadowed 190,131 listens.
                   --seed picks the largest file instead.
  a missing month  `range=month` only answers about one past month, so a month
                   nobody fetched can never be recovered from the API. One file
                   per month makes the hole visible.
"""

from __future__ import annotations

import json
import sys
import zipfile

import pytest

import core.listens as listens
import policy
import stages.profile as mod


@pytest.fixture
def store(monkeypatch, tmp_path):
    """Point both month directories at tmp_path, and the watchlist at a list."""
    months = tmp_path / "seeded"
    snapshots = tmp_path / "snapshots"
    monkeypatch.setattr(listens, "SEEDED", months)
    monkeypatch.setattr(listens, "SNAPSHOTS", snapshots)
    monkeypatch.setattr(listens, "MONTHS", months)

    class Handle:
        def __init__(self):
            self.dir = months
            self.snapshots = snapshots
            self.entries: list[dict] = []
            self.replies: list[tuple] = []
            self.asked: list[str] = []

        def install(self):
            handle = self

            class Favourites:
                @staticmethod
                def load(*a, **k):
                    return handle.entries

            monkeypatch.setattr(mod, "favourites", Favourites())
            monkeypatch.setattr(mod, "http_get", self._get)
            return mod

        def _get(self, url, **kwargs):
            self.asked.append(url)
            return self.replies.pop(0)

        def write(self, month, new_rows, source="export"):
            """Merge into the month, since each artist is written separately."""
            existing = listens.read_months(self.dir).get(month, [])
            listens.write_month(month, existing + list(new_rows), source, self.dir)

        def run(self, *argv):
            monkeypatch.setattr(sys, "argv", ["profile.py", *argv])
            return mod.main()

    return Handle()


def rows(*pairs):
    return [{"mbid": m, "name": n, "plays": p} for m, n, p in pairs]


def spread(handle, mbid, name, months, recent, plays=10):
    """Write `months` active months, `recent` of them inside the last 24.

    Recent months are hung off 2026, older ones off 2015, so the two groups
    cannot collide however many are asked for. `plays` is per month, and a
    short history needs recent * plays >= policy.EMERGING_PLAYS to be emerging.
    """
    for i in range(recent):
        handle.write(f"2026-{(i % 12) + 1:02d}" if i < 12 else f"2025-{(i % 12) + 1:02d}",
                     rows((mbid, name, plays)))
    for i in range(months - recent):
        handle.write(f"{2015 + i // 12}-{(i % 12) + 1:02d}", rows((mbid, name, plays)))


def payload(artists, from_ts=1788220800, total=None):
    return json.dumps({"payload": {"from_ts": from_ts, "to_ts": from_ts + 2592000,
                                   "total_artist_count": total or len(artists),
                                   "artists": artists}})


# ---- --seed -------------------------------------------------------------


def zip_with(tmp_path, stamps):
    path = tmp_path / "listenbrainz_x.zip"
    with zipfile.ZipFile(path, "w") as zf:
        lines = [json.dumps({"listened_at": s, "track_metadata": {
            "artist_name": "Mogwai",
            "mbid_mapping": {"artist_mbids": ["mb-mog"],
                             "artists": [{"artist_mbid": "mb-mog",
                                          "artist_credit_name": "Mogwai"}]}}})
                 for s in stamps]
        zf.writestr("listens/2026/5.jsonl", "\n".join(lines) + "\n")
    return path


def test_seed_writes_one_file_per_month(store, tmp_path, capsys):
    store.install()
    path = zip_with(tmp_path, [1777000000, 1764000000])
    assert store.run("--seed", "--export", str(path)) == 0
    assert sorted(p.name for p in store.dir.glob("*.json")) == ["2025-11.json",
                                                               "2026-04.json"]
    assert "2 months" in capsys.readouterr().out


def test_seed_dry_run_writes_nothing(store, tmp_path, capsys):
    store.install()
    path = zip_with(tmp_path, [1777000000])
    assert store.run("--seed", "--export", str(path), "--dry-run") == 0
    assert not store.dir.exists()
    assert "1 months" in capsys.readouterr().out


def test_seeding_an_export_with_no_listens_fails_rather_than_writing_nothing(
        store, tmp_path):
    store.install()
    path = tmp_path / "empty.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("user.json", "{}")
    assert store.run("--seed", "--export", str(path)) == 1


def test_seeding_a_zip_that_is_not_there_is_an_argument_error(store, tmp_path):
    store.install()
    with pytest.raises(SystemExit):
        store.run("--seed", "--export", str(tmp_path / "absent.zip"))


# ---- --month ------------------------------------------------------------


def test_a_month_is_fetched_and_saved_under_the_window_it_covers(store, capsys):
    """Into SNAPSHOTS, not the seeded directory: a snapshot cannot be refetched."""
    store.install()
    store.replies = [(200, payload([{"artist_mbid": "mb-1", "artist_name": "A",
                                     "listen_count": 7}]), {})]
    assert store.run("--month", "--user", "someone") == 0
    assert (store.snapshots / "2026-09.json").exists()
    assert not (store.dir / "2026-09.json").exists()
    assert "range=month&count=1000" in store.asked[0]
    assert "2026-09" in capsys.readouterr().out


def test_month_dry_run_fetches_but_writes_nothing(store):
    store.install()
    store.replies = [(200, payload([{"artist_mbid": "mb-1", "artist_name": "A",
                                     "listen_count": 7}]), {})]
    assert store.run("--month", "--user", "someone", "--dry-run") == 0
    assert not store.snapshots.exists()
    assert store.asked                      # it still asked


def test_a_truncated_answer_warns_because_the_month_would_be_incomplete(store, capsys):
    """total_artist_count above what came back means the count must go up."""
    store.install()
    store.replies = [(200, payload([{"artist_mbid": "mb-1", "artist_name": "A",
                                     "listen_count": 7}], total=900), {})]
    assert store.run("--month", "--user", "someone") == 0
    assert "got 1 of 900" in capsys.readouterr().err


def test_no_stats_yet_is_reported_and_writes_nothing(store):
    store.install()
    store.replies = [(204, "", {})]
    assert store.run("--month", "--user", "someone") == 1
    assert not store.snapshots.exists()


def test_an_unknown_user_is_fatal_rather_than_an_empty_month(store):
    """Unlike a quiet window, a 404 means every later run is wrong too."""
    store.install()
    store.replies = [(404, "not found", {})]
    with pytest.raises(SystemExit):
        store.run("--month", "--user", "nobody")


def test_a_server_error_fails_without_writing(store):
    store.install()
    store.replies = [(503, "down", {})]
    assert store.run("--month", "--user", "someone") == 1
    assert not store.snapshots.exists()


def test_month_without_a_user_is_an_argument_error(store):
    store.install()
    with pytest.raises(SystemExit):
        store.run("--month")


def test_seed_and_month_are_separate_runs(store):
    store.install()
    with pytest.raises(SystemExit):
        store.run("--seed", "--month")


# ---- the report ---------------------------------------------------------


def test_profiling_before_seeding_says_so(store):
    store.install()
    assert store.run() == 1


def test_each_band_is_named_and_counted(store, capsys):
    store.install()
    spread(store, "mb-core", "Deep Current", months=30, recent=12)
    spread(store, "mb-lapsed", "Deep Cooled", months=30, recent=2)
    spread(store, "mb-new", "Just Found", months=4, recent=4, plays=40)
    assert store.run() == 0
    out = capsys.readouterr().out
    assert "core 1" in out and "lapsed 1" in out and "emerging 1" in out
    assert "Deep Current" in out and "Deep Cooled" in out


def test_a_watched_artist_is_marked_and_a_muted_one_is_shouted_about(store, capsys):
    store.install()
    store.entries = [{"name": "Deep Current", "mbid": "mb-core"},
                     {"name": "Dead Legend", "mbid": "mb-dead", "watch": False}]
    spread(store, "mb-core", "Deep Current", months=30, recent=12)
    spread(store, "mb-dead", "Dead Legend", months=30, recent=12)
    assert store.run() == 0
    marks = {line.split()[1] + line.split()[2]: line.split()[-1]
             for line in capsys.readouterr().out.splitlines() if line.startswith("core ")}
    assert marks == {"DeepCurrent": "yes", "DeadLegend": "MUTED"}


def test_the_three_action_sets_are_counted(store, capsys):
    """A lapsed artist you watch, and a core artist you muted -- Celia Cruz's case."""
    store.install()
    store.entries = [{"name": "Deep Cooled", "mbid": "mb-lapsed"},
                     {"name": "Dead Legend", "mbid": "mb-dead", "watch": False}]
    spread(store, "mb-lapsed", "Deep Cooled", months=30, recent=2)
    spread(store, "mb-dead", "Dead Legend", months=30, recent=12)
    spread(store, "mb-unwatched", "Worth Watching", months=30, recent=12)
    assert store.run() == 0
    out = capsys.readouterr().out
    assert "watch these, not watched yet : 1" in out
    assert "watched but lapsed           : 1" in out
    assert "muted but still core         : 1" in out


def test_thin_artists_are_hidden_until_asked_for(store, capsys):
    store.install()
    store.write("2026-05", rows(("mb-1", "Deep Current", 10)))
    store.write("2015-01", rows(("mb-2", "One Off", 1)))
    spread(store, "mb-1", "Deep Current", months=30, recent=12)
    assert store.run() == 0
    assert "One Off" not in capsys.readouterr().out
    assert store.run("--all") == 0
    assert "One Off" in capsys.readouterr().out


def test_min_months_hides_the_short_histories(store, capsys):
    store.install()
    spread(store, "mb-new", "Just Found", months=4, recent=4, plays=40)
    assert store.run("--min-months", "6") == 0
    assert "Just Found" not in capsys.readouterr().out
    assert store.run("--min-months", "2") == 0
    assert "Just Found" in capsys.readouterr().out


def test_the_window_is_overridable_without_touching_policy(store, capsys):
    """A narrower window must move a verdict, or the flag is decoration."""
    store.install()
    spread(store, "mb-1", "Deep Current", months=30, recent=12)
    assert store.run("--window", "6") == 0
    assert "lapsed" in capsys.readouterr().out


def test_the_header_states_the_floors_it_judged_with(store, capsys):
    store.install()
    spread(store, "mb-1", "Deep Current", months=30, recent=12)
    store.run()
    assert f"floors {policy.M24_FLOOR}/{policy.DEEP_FLOOR}" in capsys.readouterr().out


def test_a_thin_artist_with_a_long_enough_history_is_still_hidden(store, capsys):
    """min_months lets it through; the band is what hides it, until --all.

    The current artist is not decoration: the window counts back from the
    newest month on disk, so without one "Long Gone" would be recent relative
    to itself.
    """
    store.install()
    spread(store, "mb-cur", "Still Here", months=30, recent=12)
    spread(store, "mb-old", "Long Gone", months=5, recent=0)
    assert store.run() == 0
    assert "Long Gone" not in capsys.readouterr().out
    assert store.run("--all") == 0
    assert "Long Gone" in capsys.readouterr().out


# ---- --json, the handoff to favourites.py -------------------------------


def verdicts(path):
    return {a["name"]: a for a in json.loads(path.read_text())["artists"]}


def test_the_verdict_file_carries_the_three_actionable_bands_only(store, tmp_path):
    """thin is 5,608 of 7,807 rows and nothing consumes it."""
    store.install()
    spread(store, "mb-core", "Deep Current", months=30, recent=12)
    spread(store, "mb-lapsed", "Deep Cooled", months=30, recent=2)
    spread(store, "mb-new", "Just Found", months=4, recent=4, plays=40)
    spread(store, "mb-thin", "One Listen", months=4, recent=1, plays=1)
    out = tmp_path / "profile.json"
    assert store.run("--json", str(out)) == 0
    assert set(verdicts(out)) == {"Deep Current", "Deep Cooled", "Just Found"}


def test_a_verdict_row_carries_what_a_decision_needs(store, tmp_path):
    store.install()
    spread(store, "mb-core", "Deep Current", months=30, recent=12)
    out = tmp_path / "profile.json"
    store.run("--json", str(out))
    row = verdicts(out)["Deep Current"]
    assert row["band"] == "core" and row["mbid"] == "mb-core"
    assert set(row) == {"name", "mbid", "band", "months", "recent", "plays",
                        "recent_plays", "first", "last"}


def test_the_verdict_file_records_the_floors_it_was_written_with(store, tmp_path):
    """A verdict is only readable next to the numbers that produced it."""
    store.install()
    spread(store, "mb-core", "Deep Current", months=30, recent=12)
    out = tmp_path / "profile.json"
    store.run("--json", str(out))
    data = json.loads(out.read_text())
    assert data["floors"] == {"m24": policy.M24_FLOOR, "deep": policy.DEEP_FLOOR,
                              "emerging_plays": policy.EMERGING_PLAYS}
    assert data["through"] == "2026-12"


def test_no_json_flag_writes_no_file(store, tmp_path):
    store.install()
    spread(store, "mb-core", "Deep Current", months=30, recent=12)
    assert store.run() == 0
    assert not (tmp_path / "profile.json").exists()


def test_dry_run_suppresses_the_verdict_file(store, tmp_path):
    store.install()
    spread(store, "mb-core", "Deep Current", months=30, recent=12)
    out = tmp_path / "profile.json"
    assert store.run("--json", str(out), "--dry-run") == 0
    assert not out.exists()


# ---- the burst flag -----------------------------------------------------


def test_an_intense_lapse_is_flagged_in_the_table_and_the_file(store, tmp_path, capsys):
    """Omar's shape: deep, few recent months, many plays inside them."""
    store.install()
    spread(store, "mb-burst", "Went Back To", months=30, recent=4, plays=50)
    out = tmp_path / "profile.json"
    assert store.run("--json", str(out)) == 0
    printed = capsys.readouterr().out
    assert "burst?" in printed
    assert verdicts(out)["Went Back To"]["burst"] is True
    assert verdicts(out)["Went Back To"]["band"] == "lapsed"


def test_an_ordinary_lapse_carries_no_flag(store, tmp_path, capsys):
    store.install()
    spread(store, "mb-cold", "Gone Quiet", months=30, recent=3, plays=2)
    out = tmp_path / "profile.json"
    store.run("--json", str(out))
    assert "burst?" not in capsys.readouterr().out
    assert "burst" not in verdicts(out)["Gone Quiet"]


def test_a_core_artist_is_never_flagged_however_intensely_played(store, tmp_path):
    """The flag is doubt about a lapse. Drexler plays 136 a month and is core."""
    store.install()
    spread(store, "mb-core", "Deep Current", months=30, recent=12, plays=200)
    out = tmp_path / "profile.json"
    store.run("--json", str(out))
    row = verdicts(out)["Deep Current"]
    assert row["band"] == "core" and "burst" not in row


def test_a_watched_artist_whose_lapse_is_doubtful_is_called_out(store, capsys):
    """So "watched but lapsed" is not read as five names to mute."""
    store.install()
    store.entries = [{"name": "Went Back To", "mbid": "mb-burst"},
                     {"name": "Gone Quiet", "mbid": "mb-cold"}]
    spread(store, "mb-burst", "Went Back To", months=30, recent=4, plays=50)
    spread(store, "mb-cold", "Gone Quiet", months=30, recent=3, plays=2)
    assert store.run() == 0
    out = capsys.readouterr().out
    assert "watched but lapsed           : 2" in out
    assert "played intensely : 1  (Went Back To)" in out
