"""stages/baseline.py: the opponent list, and the overlap with ours.

Offline: `core.similar.similar` is stubbed, so no test reaches ListenBrainz.
What this pins is the part that is easy to get silently wrong -- dropping what
you already play, on either key, and deduping across seeds without losing the
score.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import closing

import pytest

import stages.baseline as mod
import stages.load as load
from core import shown


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "music.db"
    con = sqlite3.connect(path)
    for statement in load.SCHEMA.strip().split(";"):
        if statement.strip():
            con.execute(statement)
    con.execute("INSERT INTO seeds (seed_qobuz_id, name) VALUES (1, 'Björk')")
    monkeypatch.setattr(mod, "DATA", tmp_path)
    monkeypatch.setattr(mod.favourites, "mbid_for", lambda sid: f"mbid-{sid}")

    class Handle:
        def __init__(self):
            self.path = path
            self.dir = tmp_path
            self.answers: dict[str, list | None] = {}

        def seed(self, seed_id, name):
            con.execute("INSERT INTO seeds (seed_qobuz_id, name) VALUES (?,?)",
                        (seed_id, name))

        def listen(self, artist_key, mbid=None):
            con.execute("INSERT INTO listens (artist_key, artist_mbid,"
                        " listened_date) VALUES (?,?,'2026-01-01')",
                        (artist_key, mbid))

        def similar(self, mbid, rows):
            self.answers[mbid] = rows

        def co_artist(self, key, name, title="Record"):
            con.execute(
                "INSERT INTO co_artists (seed_qobuz_id, person_key, name,"
                " albums, seed_records, their_records) VALUES (1,?,?,1,1,0)",
                (key, name))
            con.execute(
                "INSERT INTO co_artist_albums (seed_qobuz_id, person_key,"
                " album_id, title, date, provenance)"
                " VALUES (1,?,?,?, '2020-01-01','own')", (key, "a1", title))

        def gather(self, refresh=False):
            con.commit()
            monkeypatch.setattr(mod.similar, "similar",
                                lambda m, refresh=False, directory=None:
                                self.answers.get(m))
            with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as read:
                read.row_factory = sqlite3.Row
                return mod.gather(read, refresh)

        def run(self, *args):
            con.commit()
            monkeypatch.setattr(mod.similar, "similar",
                                lambda m, refresh=False, directory=None:
                                self.answers.get(m))
            monkeypatch.setattr(sys, "argv",
                                ["baseline.py", "--db", str(path), *args])
            assert mod.main() == 0

    return Handle()


def row(name, score, mbid=None):
    return {"name": name, "mbid": mbid, "score": score, "type": "Group"}


# ---- what reaches the list ----------------------------------------------


def test_the_list_is_score_ordered(store):
    store.similar("mbid-1", [row("Low", 10), row("High", 900)])
    rows, failed = store.gather()
    assert [r["name"] for r in rows] == ["High", "Low"]
    assert failed == []


def test_an_artist_you_already_play_is_dropped_on_the_name_key(store):
    store.similar("mbid-1", [row("Radiohead", 900), row("Portishead", 800)])
    store.listen("radiohead")
    rows, _ = store.gather()
    assert [r["name"] for r in rows] == ["Portishead"]


def test_an_artist_you_already_play_is_dropped_on_the_mbid_too(store):
    """ListenBrainz answers in MBIDs and `listens` carries one wherever its own
    mapping found one, so the exact match is worth using where it exists."""
    store.similar("mbid-1", [row("Spelled Oddly", 900, mbid="x1")])
    store.listen("something else entirely", mbid="x1")
    rows, _ = store.gather()
    assert rows == []


def test_the_seed_suggested_as_its_own_neighbour_is_dropped(store):
    store.similar("mbid-1", [row("Björk", 9999), row("Real", 10)])
    rows, _ = store.gather()
    assert [r["name"] for r in rows] == ["Real"]


def test_one_artist_from_two_seeds_keeps_the_higher_affinity_and_counts_both(store):
    """Same shape the co-appearance list reports, so the two are comparable
    rather than merely adjacent."""
    store.seed(2, "Residente")
    store.similar("mbid-1", [row("The xx", 500), row("Top For Bjork", 1000)])
    store.similar("mbid-2", [row("The xx", 1600), row("Top For Res", 1600)])
    found = {r["name"]: r for r in store.gather()[0]}["The xx"]
    assert found["affinity"] == 1.0          # 1600 of Residente's top 1600
    assert found["score"] == 1600            # the raw number, as provenance
    assert found["seeds"] == 2
    assert sorted(found["seed_names"]) == ["Björk", "Residente"]


def test_each_seed_is_divided_by_its_own_ceiling(store):
    """ListenBrainz returns a session co-occurrence COUNT, which scales with
    how much the seed is listened to globally: Björk's top is 6,682 and Pérez
    Cruz's is 24. On the raw maximum, her best neighbour ranked below Björk's
    hundredth."""
    store.seed(2, "Sílvia Pérez Cruz")
    store.similar("mbid-1", [row("Big Seed Second", 3000),
                             row("Big Seed Top", 6000)])
    store.similar("mbid-2", [row("Small Seed Top", 24)])
    names = [r["name"] for r in store.gather()[0]]
    # The small seed's best beats the big seed's second, which is the point.
    assert names == ["Big Seed Top", "Small Seed Top", "Big Seed Second"]


def test_the_seed_count_only_breaks_a_tie(store):
    """ListenBrainz has no cross-seed notion, so rewarding breadth here would
    be designing the opponent rather than using it. The co-appearance list is
    the one making that claim."""
    store.seed(2, "Residente")
    store.similar("mbid-1", [row("Both", 100), row("One Only", 100)])
    store.similar("mbid-2", [row("Both", 100)])
    names = [r["name"] for r in store.gather()[0]]
    assert names == ["Both", "One Only"]      # equal affinity, more seeds first


def test_a_seed_whose_scores_are_all_zero_does_not_divide_by_zero(store):
    store.similar("mbid-1", [row("Flat", 0)])
    (found,), _ = store.gather()
    assert found["affinity"] == 0.0


def test_a_seed_with_no_mbid_is_named_rather_than_skipped_silently(store,
                                                                   monkeypatch):
    monkeypatch.setattr(mod.favourites, "mbid_for", lambda sid: None)
    rows, failed = store.gather()
    assert rows == []
    assert "no mbid" in failed[0]


def test_a_failed_request_is_named_and_the_other_seeds_still_run(store):
    store.seed(2, "Residente")
    store.similar("mbid-2", [row("Kept", 10)])      # mbid-1 answers None
    rows, failed = store.gather()
    assert [r["name"] for r in rows] == ["Kept"]
    assert "request failed" in failed[0]


def test_the_affinity_is_logged_as_the_key_the_order_used(store):
    store.similar("mbid-1", [row("A", 42), row("Top", 84)])
    found = {r["name"]: r for r in store.gather()[0]}["A"]
    assert found["sort_key"] == (0.5,)


# ---- the report ---------------------------------------------------------


def test_the_overlap_is_reported_against_the_co_appearance_list(store, capsys):
    store.similar("mbid-1", [row("Shared", 900), row("Only Similar", 800)])
    store.co_artist("shared", "Shared")
    store.run("--compare")
    said = capsys.readouterr().out
    assert "similar-artist list: 2 unheard" in said
    assert "co-appearance list:  1 unheard" in said
    assert "in both:             1" in said
    assert "Shared" in said
    # And it refuses to claim the comparison means something on its own.
    assert "--score does" in said


def test_log_writes_into_the_same_file_the_strategies_use(store, capsys):
    """One file is the whole point: a hit rate is only a comparison if both
    sources are recorded identically."""
    store.similar("mbid-1", [row("A", 900)])
    store.run("--log", "--top", "1")
    runs = shown.load(store.dir)
    assert len(runs) == 1
    assert runs[0]["source"] == "similar"
    assert runs[0]["top"][0]["name"] == "A"


def test_json_is_the_same_rows(store, capsys):
    store.similar("mbid-1", [row("A", 900)])
    store.run("--json", "--top", "1")
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["name"] == "A" and rows[0]["score"] == 900


def test_a_store_with_no_such_table_says_to_build_it(tmp_path, monkeypatch):
    (tmp_path / "empty.db").write_bytes(b"")
    monkeypatch.setattr(sys, "argv",
                        ["baseline.py", "--db", str(tmp_path / "empty.db")])
    with pytest.raises(SystemExit, match="load.py"):
        mod.main()


def test_a_seed_that_could_not_be_read_is_named_on_stderr(store, capsys):
    """The warning the gather() test checks as data, now as output: a run that
    silently skipped a seed would report a smaller list as if it were complete."""
    store.run("--top", "1")
    assert "no similar artists for Björk" in capsys.readouterr().err
