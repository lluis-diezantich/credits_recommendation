"""stages/rank.py: the feature query, the filters, and the shown-log loop.

The strategies and the ordering are tested in test_rank.py. What this file
pins is the part that touches the store: that a feature row is built from the
columns the strategies read, that the two read-side filters apply here as they
do in co_artists.py, and that --log then --score closes the loop D29 exists to
open.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
from contextlib import closing

import pytest

import stages.load as load
import stages.rank as mod

TODAY = dt.date(2026, 10, 22)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A store with two seeds, one of them accented, and a helper per table."""
    path = tmp_path / "music.db"
    con = sqlite3.connect(path)
    for statement in load.SCHEMA.strip().split(";"):
        if statement.strip():
            con.execute(statement)
    con.execute("INSERT INTO seeds (seed_qobuz_id, name) VALUES (1, 'Jorge Drexler')")
    con.execute("INSERT INTO seeds (seed_qobuz_id, name) VALUES (2, 'Sílvia Pérez Cruz')")
    monkeypatch.setattr(mod, "DATA", tmp_path)

    class Handle:
        def __init__(self):
            self.path = path
            self.dir = tmp_path

        def co_artist(self, seed, key, name, own=0, guest=0,
                      first="2020-01-01", last="2020-01-01"):
            con.execute(
                "INSERT INTO co_artists (seed_qobuz_id, person_key, name, albums,"
                " seed_records, their_records, first_seen, last_seen)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (seed, key, name, own + guest, own, guest, first, last))
            for n in range(own + guest):
                con.execute(
                    "INSERT INTO co_artist_albums (seed_qobuz_id, person_key,"
                    " album_id, title, date, provenance) VALUES (?,?,?,?,?,?)",
                    (seed, key, f"{key}-{seed}-{n}", f"Record {n}", last,
                     "own" if n < own else "guest"))

        def album(self, seed, key, album_id, provenance, date="2020-01-01"):
            con.execute(
                "INSERT INTO co_artist_albums (seed_qobuz_id, person_key,"
                " album_id, title, date, provenance) VALUES (?,?,?,?,?,?)",
                (seed, key, album_id, album_id, date, provenance))

        def credit(self, album_id, key, role, track=1):
            con.execute(
                "INSERT INTO credits (album_id, track_id, track_title,"
                " person_key, role, role_class) VALUES (?,?,?,?,?,'')",
                (album_id, track, "t", key, role))

        def listen(self, artist_key, when="2026-01-01", times=1):
            for _ in range(times):
                con.execute("INSERT INTO listens (artist_key, listened_date)"
                            " VALUES (?,?)", (artist_key, when))

        def rows(self):
            con.commit()
            with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as read:
                read.row_factory = sqlite3.Row
                return mod.candidates(read, TODAY)

        def run(self, *args):
            con.commit()
            monkeypatch.setattr(sys, "argv",
                                ["rank.py", "--db", str(path), *args])
            assert mod.main() == 0

    return Handle()


# ---- the feature row ----------------------------------------------------


def test_a_feature_row_carries_what_the_strategies_read(store):
    store.co_artist(1, "p", "P", own=1, guest=2, first="2016-01-01",
                    last="2024-01-01")
    store.credit("p-1-0", "p", "Guitar")
    row, = store.rows()
    assert row["seeds"] == 1
    assert (row["on_seeds"], row["on_theirs"], row["records"]) == (1, 2, 3)
    assert row["roles"] == ["Guitar"]
    assert row["role_weight"] > 0
    assert 0 < row["recency"] < 1
    assert row["span"] == pytest.approx(8, abs=0.1)


def test_one_person_on_two_seeds_is_one_row_with_both(store):
    """The grain that makes this different from co_artists.py, and the column
    D22's thesis rests on."""
    store.co_artist(1, "p", "P", own=1)
    store.co_artist(2, "p", "P", guest=1)
    row, = store.rows()
    assert row["seeds"] == 2
    assert sorted((row["seed_names"] or "").split(",")) == [
        "Jorge Drexler", "Sílvia Pérez Cruz"]
    assert (row["on_seeds"], row["on_theirs"]) == (1, 1)


def test_seed_plays_are_joined_on_the_normalised_key(store):
    """listens.artist_key is normalise(name) and seeds.name is the spelling
    Qobuz returned. LOWER() does not bridge "Sílvia Pérez Cruz" to
    "silvia perez cruz", and a join that matched nothing would have made
    seed_plays zero for every accented seed and looked like a weight."""
    store.co_artist(2, "p", "P", own=1)
    store.listen("silvia perez cruz", times=7)
    row, = store.rows()
    assert row["seed_plays"] == 7


def test_a_candidate_with_no_date_has_no_recency_rather_than_full(store):
    store.co_artist(1, "p", "P", own=1, first=None, last=None)
    row, = store.rows()
    assert row["recency"] == 0.0 and row["span"] == 0.0


# ---- the filters this shares with co_artists.py -------------------------


def test_a_billing_that_is_not_an_artist_is_not_a_candidate(store):
    """Penelope Cruz reads as a two-seed intersection in the raw table -- she
    is on "313" with both Perez Cruz and Residente -- so a ranker that skipped
    this filter would put her near the top."""
    store.co_artist(1, "penelope cruz", "Penelope Cruz", own=1)
    store.co_artist(2, "penelope cruz", "Penelope Cruz", own=1)
    store.co_artist(1, "p", "P", own=1)
    assert [r["person_key"] for r in store.rows()] == ["p"]


def test_a_billing_with_nothing_musical_behind_it_is_not_a_candidate(store):
    store.co_artist(1, "liniers", "Liniers", own=1)
    store.credit("liniers-1-0", "liniers", "MainArtist")
    store.credit("liniers-1-0", "liniers", "Designer")
    assert store.rows() == []


def test_a_role_on_a_compilation_is_not_evidence_here_either(store):
    store.co_artist(1, "p", "P", own=1)
    store.album(1, "p", "comp", "compilation", date="2005-01-01")
    store.credit("comp", "p", "Remixer")
    store.credit("p-1-0", "p", "Guitar")
    row, = store.rows()
    assert row["roles"] == ["Guitar"]


# ---- the report ---------------------------------------------------------


def test_the_strategies_list_their_claims(store, capsys):
    store.run("--list")
    said = capsys.readouterr().out
    assert "breadth" in said and "(default)" in said
    assert "taste" in said


def test_compare_reports_what_the_choice_changes(store, capsys):
    store.co_artist(1, "a", "A", guest=1)
    store.co_artist(1, "b", "B", own=1)
    store.co_artist(2, "b", "B", own=1)
    store.run("--compare", "breadth", "direction")
    said = capsys.readouterr().out
    assert "breadth vs direction" in said
    assert "do not move" in said


def test_an_unknown_strategy_is_refused_by_name(store):
    store.co_artist(1, "p", "P", own=1)
    with pytest.raises(KeyError, match="unknown ranking strategy"):
        store.run("--strategy", "breath")


# ---- the shown-log ------------------------------------------------------


def test_log_then_score_closes_the_loop(store, capsys):
    """The measurement every weight in policy's strategy block is waiting for.
    A name counts only if it was played AFTER the run that showed it."""
    store.co_artist(1, "played later", "Played Later", own=1)
    store.co_artist(1, "never", "Never", own=1)
    store.run("--log", "--top", "2")
    capsys.readouterr()

    logged = json.loads((store.dir / mod.LOG).read_text())
    assert len(logged["runs"]) == 1
    assert logged["runs"][0]["strategy"] == "breadth"
    assert [r["rank"] for r in logged["runs"][0]["top"]] == [1, 2]

    store.listen("played later", when="2099-01-01")
    store.run("--score")
    said = capsys.readouterr().out
    assert "1 run(s) on file" in said
    assert "1 (50%)" in said


def test_a_play_before_the_run_does_not_count(store, capsys):
    """Otherwise the log scores itself on listening that predates the claim."""
    store.co_artist(1, "p", "P", own=1)
    store.run("--log", "--top", "1")
    store.listen("p", when="1999-01-01")
    store.run("--score")
    assert "0 (0%)" in capsys.readouterr().out


def test_each_run_is_appended_rather_than_replacing_the_last(store, capsys):
    store.co_artist(1, "p", "P", own=1)
    store.run("--log", "--top", "1")
    store.run("--strategy", "taste", "--log", "--top", "1")
    runs = json.loads((store.dir / mod.LOG).read_text())["runs"]
    assert [r["strategy"] for r in runs] == ["breadth", "taste"]


def test_a_hand_mangled_log_does_not_lose_the_run(store, capsys):
    """A file somebody edited into a different shape is not a reason to lose
    the run, but it is a reason not to append to whatever is there."""
    (store.dir / mod.LOG).write_text('{"runs": 3}')
    store.co_artist(1, "p", "P", own=1)
    store.run("--log", "--top", "1")
    runs = json.loads((store.dir / mod.LOG).read_text())["runs"]
    assert len(runs) == 1


def test_score_with_no_log_says_to_run_log_first(store, capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["rank.py", "--db", str(store.path), "--score"])
    assert mod.main() == 1
    assert "--log first" in capsys.readouterr().err


def test_the_logged_score_is_the_key_the_ordering_used(store):
    """Not a recomputed number, and a lexicographic strategy logs every term."""
    store.co_artist(1, "p", "P", own=1)
    store.co_artist(2, "p", "P", own=1)
    store.run("--log", "--top", "1")
    row = json.loads((store.dir / mod.LOG).read_text())["runs"][0]["top"][0]
    assert row["score"][0] == 2.0 and len(row["score"]) == 2
    assert row["seeds"] == 2


def test_json_output_drops_the_row_object_sqlite_handed_back(store):
    """--json is the handoff downstream, so every value has to be JSON."""
    store.co_artist(1, "p", "P", own=1)
    store.run("--json", "--top", "1")


def test_an_empty_log_says_so_rather_than_dividing_by_zero(store, capsys,
                                                           monkeypatch):
    (store.dir / mod.LOG).write_text('{"version": 1, "runs": []}')
    monkeypatch.setattr(sys, "argv",
                        ["rank.py", "--db", str(store.path), "--score"])
    assert mod.main() == 1
    assert "no runs yet" in capsys.readouterr().err


def test_a_store_with_no_such_table_says_to_build_it(tmp_path, monkeypatch):
    (tmp_path / "empty.db").write_bytes(b"")
    monkeypatch.setattr(sys, "argv",
                        ["rank.py", "--db", str(tmp_path / "empty.db")])
    with pytest.raises(SystemExit, match="load.py"):
        mod.main()


# ---- a remix is not a collaboration -------------------------------------


def test_a_remix_only_candidate_is_not_ranked(store):
    """He was first under breadth. His two seeds were one record, and his one
    credit on it was the remix."""
    store.co_artist(1, "conrad taylor", "Conrad Taylor", own=1)
    store.co_artist(2, "conrad taylor", "Conrad Taylor", own=1)
    store.credit("conrad taylor-1-0", "conrad taylor", "Re-Mixer")
    store.credit("conrad taylor-2-0", "conrad taylor", "Re-Mixer")
    store.co_artist(1, "p", "P", own=1)
    assert [r["person_key"] for r in store.rows()] == ["p"]


def test_two_seeds_on_one_record_corroborate_once(store):
    """The feature that was double-counting. Same album_id under both seeds is
    what the real store had for "Berghain (Remix)"."""
    store.co_artist(1, "p", "P", own=1)
    store.album(2, "p", "p-1-0", "own")        # the SAME album, second seed
    con_rows = {r["person_key"]: r for r in store.rows()}
    row = con_rows["p"]
    assert (row["seeds"], row["albums"], row["corroboration"]) == (1, 1, 1)


def test_distinct_records_across_seeds_corroborate_twice(store):
    store.co_artist(1, "p", "P", own=1)
    store.co_artist(2, "p", "P", own=1)
    row, = store.rows()
    assert (row["seeds"], row["albums"], row["corroboration"]) == (2, 2, 2)
