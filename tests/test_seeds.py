"""stages/seeds.py: who is worth 50 requests, and which 50 to spend first.

The rule is `policy.seedable`, tested in test_policy.py. What this file pins is
the stage around it: the two ids a walk needs, the order the candidates come
back in, and that a missing store degrades the order rather than the rule.

docs/adr/D26 has the decision and the numbers behind both floors.
"""

from __future__ import annotations

import json

import pytest

import stages.seeds as seeds

# profile.json's shape, with the four seeds already walked plus two others.
PROFILE = {"artists": [
    {"name": "Jorge Drexler", "band": "core", "months": 68, "recent": 24,
     "plays": 6988},
    {"name": "Sílvia Pérez Cruz", "band": "core", "months": 50, "recent": 17,
     "plays": 1369},
    {"name": "Little Simz", "band": "emerging", "months": 21, "recent": 20,
     "plays": 1327},
    {"name": "ROSALÍA", "band": "core", "months": 56, "recent": 21, "plays": 900},
    {"name": "Nathy Peluso", "band": "core", "months": 35, "recent": 24,
     "plays": 1534},
    {"name": "Frankie Ruiz", "band": "emerging", "months": 22, "recent": 21,
     "plays": 389},
    {"name": "Radiohead", "band": "lapsed", "months": 73, "recent": 3,
     "plays": 5000},
]}

IDS = {"jorge drexler": {"name": "Jorge Drexler", "qobuz_id": 41620, "mbid": "d"},
       "silvia perez cruz": {"name": "Sílvia Pérez Cruz", "qobuz_id": 656411,
                             "mbid": "s"},
       "little simz": {"name": "Little Simz", "qobuz_id": 2020906, "mbid": "l"},
       "rosalia": {"name": "ROSALÍA", "qobuz_id": 219860, "mbid": "r"},
       "nathy peluso": {"name": "Nathy Peluso", "qobuz_id": 3526537, "mbid": "n"},
       "frankie ruiz": {"name": "Frankie Ruiz", "qobuz_id": 1, "mbid": "f"},
       "radiohead": {"name": "Radiohead", "qobuz_id": 2, "mbid": "x"}}

WALKED = {41620, 656411, 2020906}
CO = {"rosalia"}


def pick(**kwargs):
    args = {"profile": PROFILE, "ids": IDS, "walked": WALKED,
            "co_artists": CO, **kwargs}
    return seeds.candidates(args["profile"], args["ids"], args["walked"],
                            args["co_artists"])


# ---- the two ids a walk needs -------------------------------------------


def test_an_artist_with_no_mbid_is_not_a_candidate(tmp_path):
    """The walk runs without one and reports the seed as its own biggest
    collaborator, which is the defect D23 exists to prevent."""
    (tmp_path / "favourites.json").write_text(json.dumps([
        {"name": "Has Both", "qobuz_id": 1, "mbid": "m"},
        {"name": "No Mbid", "qobuz_id": 2},
        {"name": "No Qobuz Id", "mbid": "m"},
    ]))
    assert set(seeds.walkable(tmp_path / "favourites.json")) == {"has both"}


def test_favourites_as_a_dict_reads_the_same(tmp_path):
    """The file has carried both shapes."""
    (tmp_path / "favourites.json").write_text(json.dumps(
        {"artists": [{"name": "Has Both", "qobuz_id": 1, "mbid": "m"}]}))
    assert set(seeds.walkable(tmp_path / "favourites.json")) == {"has both"}


def test_an_artist_the_watchlist_does_not_carry_is_rejected_with_that_reason():
    kept, dropped = pick(ids={})
    assert kept == []
    assert all("favourites.json" in r["why"] for r in dropped)


# ---- who passes ---------------------------------------------------------


def test_the_rule_selects_all_four_seeds_already_walked():
    """The validation the floors were chosen against: a rule that excludes a
    seed already known to be good is wrong. Perez Cruz at 17/24 is the one a
    floor of 18 would have missed."""
    kept, _ = pick()
    assert {"Jorge Drexler", "Sílvia Pérez Cruz", "Little Simz"} <= {
        r["name"] for r in kept}


def test_a_lapsed_artist_never_qualifies():
    _, dropped = pick()
    assert "Radiohead" in {r["name"] for r in dropped}


def test_a_short_history_under_the_plays_floor_says_so():
    _, dropped = pick()
    why = {r["name"]: r["why"] for r in dropped}
    assert "short history" in why["Frankie Ruiz"]


# ---- the order ----------------------------------------------------------


def test_a_guaranteed_intersection_is_walked_first():
    """ROSALÍA is already a co-artist, so walking her puts range into the
    ranker's main column at once. Nathy Peluso has more recent months and
    more plays and still comes second."""
    kept, _ = pick()
    fresh = [r["name"] for r in kept if not r["walked"]]
    assert fresh[0] == "ROSALÍA"
    assert fresh[1] == "Nathy Peluso"


def test_the_walked_ones_sort_to_the_end():
    kept, _ = pick()
    walked_at = [i for i, r in enumerate(kept) if r["walked"]]
    assert walked_at == list(range(len(kept) - len(walked_at), len(kept)))


def test_intersecting_is_not_part_of_the_rule_only_the_order():
    """Otherwise the corpus grows only along links it already knows, which is
    the opposite of discovery. With nothing in the store the same artists pass
    and only their order changes."""
    kept_with, _ = pick()
    kept_without, _ = pick(co_artists=set())
    assert {r["name"] for r in kept_with} == {r["name"] for r in kept_without}
    assert [r["name"] for r in kept_without if not r["walked"]][0] == "Nathy Peluso"


def test_most_recent_months_first_then_most_plays():
    kept, _ = pick(co_artists=set(), walked=set())
    order = [(-r["recent"], -r["plays"]) for r in kept]
    assert order == sorted(order)


# ---- failure modes ------------------------------------------------------


def test_no_profile_says_which_stage_to_run(tmp_path, monkeypatch):
    monkeypatch.setattr(seeds, "DATA", tmp_path)
    monkeypatch.setattr("sys.argv", ["seeds.py"])
    with pytest.raises(SystemExit, match="profile.py"):
        seeds.main()


# ---- what it prints -----------------------------------------------------


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    """The stage over fixture files and a store that does not exist."""
    (tmp_path / "profile.json").write_text(json.dumps(PROFILE, ensure_ascii=False))
    (tmp_path / "favourites.json").write_text(
        json.dumps(list(IDS.values()), ensure_ascii=False))
    monkeypatch.setattr(seeds, "DATA", tmp_path)

    def invoke(*args):
        monkeypatch.setattr("sys.argv", ["seeds.py", "--db",
                                         str(tmp_path / "none.db"), *args])
        assert seeds.main() == 0
        return capsys.readouterr()
    return invoke


def test_a_missing_store_degrades_the_order_not_the_rule(run):
    """No store is not an error: the rule reads the profile, and only the
    intersection-first ordering needs the graph."""
    said = run()
    assert "no readable store" in said.err
    assert "Nathy Peluso" in said.out


def test_the_listing_says_how_many_are_left_to_walk(run):
    said = run().out
    assert "artists pass the rule" in said
    assert "to go" in said


def test_next_prints_a_runnable_command_per_seed(run):
    said = run("--next", "2").out
    assert "./stages/discover.py --artist 3526537" in said
    assert said.count("./stages/discover.py") == 2
    # And the step that must not be skipped between the walk and the ranking.
    assert "aliases.json" in said


def test_next_cannot_promise_more_seeds_than_there_are(run):
    """Five artists pass the rule in the fixture, and with no store none of
    them counts as walked."""
    said = run("--next", "99").out
    assert "the next 5 seeds" in said
    assert "~250 in total" in said


def test_all_names_the_test_each_rejected_artist_failed(run):
    said = run("--all").out
    assert "rejected" in said
    # Radiohead fails on months, not on its band: "lapsed" is a long history
    # with a recent count below policy's m24 floor, so the month test answers
    # first and 3/24 is what the line says.
    assert "3 recent months, floor is 17" in said
    assert "short history" in said


def test_a_real_store_decides_who_is_walked_and_who_intersects(tmp_path,
                                                               monkeypatch,
                                                               capsys):
    """The path the no-store test cannot reach: both queries actually run."""
    import sqlite3

    import stages.load as load

    (tmp_path / "profile.json").write_text(json.dumps(PROFILE, ensure_ascii=False))
    (tmp_path / "favourites.json").write_text(
        json.dumps(list(IDS.values()), ensure_ascii=False))
    monkeypatch.setattr(seeds, "DATA", tmp_path)

    db = tmp_path / "music.db"
    con = sqlite3.connect(db)
    for statement in load.SCHEMA.strip().split(";"):
        if statement.strip():
            con.execute(statement)
    con.execute("INSERT INTO seeds (seed_qobuz_id, name) VALUES (41620, 'JD')")
    con.execute("""INSERT INTO co_artists (seed_qobuz_id, person_key, name,
                   albums, seed_records, their_records)
                   VALUES (41620, 'rosalia', 'ROSALÍA', 1, 1, 0)""")
    con.commit()

    monkeypatch.setattr("sys.argv", ["seeds.py", "--db", str(db), "--json"])
    assert seeds.main() == 0
    said = json.loads(capsys.readouterr().out)
    rows = {r["name"]: r for r in said["candidates"]}
    assert rows["Jorge Drexler"]["walked"] is True
    assert rows["ROSALÍA"]["intersects"] is True
    assert rows["Nathy Peluso"]["intersects"] is False
    # And the order it buys: the intersection ahead of more recent months.
    fresh = [r["name"] for r in said["candidates"] if not r["walked"]]
    assert fresh[0] == "ROSALÍA"


def test_json_carries_the_candidates_and_the_rejections(run):
    """With no store nothing is known to intersect and nothing is known to be
    walked, so the order is the recent-months fallback: Drexler's 24/24 and
    6,988 plays ahead of Nathy Peluso's 24/24 and 1,534."""
    said = json.loads(run("--json").out)
    assert [r["name"] for r in said["candidates"]][:2] == [
        "Jorge Drexler", "Nathy Peluso"]
    assert "Radiohead" in {r["name"] for r in said["rejected"]}
