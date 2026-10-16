"""The `watch` field, and the --mute/--unmute that set it."""

from __future__ import annotations

import json


def rows():
    return [
        {"name": "Bobby Cruz", "qobuz_id": 55, "qobuz_match": "exact", "tracks": 1},
        {"name": "Jorge Drexler", "qobuz_id": 41620, "qobuz_match": "exact"},
        {"name": "Feli Colina", "qobuz_id": 77, "qobuz_match": "exact", "watch": False},
    ]


def run(favourites_file, monkeypatch, argv, entries=None):
    import sys
    stage = favourites_file.install()
    favourites_file.entries = entries if entries is not None else rows()
    monkeypatch.setattr(sys, "argv", ["favourites.py", *argv])
    return stage.main()


def test_mute_sets_the_field(favourites_file, monkeypatch, capsys):
    code = run(favourites_file, monkeypatch, ["--mute", "bobby  CRUZ"])
    assert code == 0
    assert favourites_file.entries[0]["watch"] is False
    out = capsys.readouterr().out
    assert "Bobby Cruz: muted" in out and "1 changed" in out


def test_mute_needs_no_user_and_makes_no_request(favourites_file, monkeypatch):
    """Nothing is stubbed here but the file, so a network call would fail."""
    assert run(favourites_file, monkeypatch, ["--mute", "Bobby Cruz"]) == 0


def test_already_muted_is_a_no_op(favourites_file, monkeypatch, capsys):
    run(favourites_file, monkeypatch, ["--mute", "Feli Colina"])
    assert favourites_file.saved is None
    out = capsys.readouterr().out
    assert "already muted" in out and "nothing changed" in out


def test_unmute_removes_the_key_rather_than_writing_true(favourites_file, monkeypatch):
    """Absent means watched everywhere else here, and a default written into
    data is one you cannot change later without rewriting every row."""
    run(favourites_file, monkeypatch, ["--unmute", "Feli Colina"])
    assert "watch" not in favourites_file.entries[2]


def test_several_names_at_once_and_a_typo_gets_a_hint(favourites_file, monkeypatch, capsys):
    run(favourites_file, monkeypatch,
        ["--mute", "Bobby Cruz", "Drexler", "Nobody Here"])
    err = capsys.readouterr().err

    assert favourites_file.entries[0]["watch"] is False     # the rest still applied
    assert "did you mean Jorge Drexler?" in err
    assert "not found: Nobody Here" in err


def test_dry_run_writes_nothing(favourites_file, monkeypatch, capsys):
    run(favourites_file, monkeypatch, ["--mute", "Bobby Cruz", "--dry-run"])
    assert favourites_file.saved is None
    assert "nothing written" in capsys.readouterr().out


def test_mute_and_unmute_together_is_rejected(favourites_file, monkeypatch):
    import pytest
    with pytest.raises(SystemExit) as exit:
        run(favourites_file, monkeypatch, ["--mute", "A", "--unmute", "B"])
    assert exit.value.code == 2


# --- the field's semantics across a resolve ------------------------------

def test_a_muted_artist_stays_muted_when_the_top_lists_re_see_them(
        favourites_file, monkeypatch):
    """Deleting the entry would not work -- a deleted artist is just a name
    nobody recognises, so the next run adds it straight back."""
    import sys
    stage = favourites_file.install()
    favourites_file.entries = [
        {"name": "Bobby Cruz", "qobuz_id": 55, "qobuz_match": "exact", "watch": False},
        {"name": "Jorge Drexler", "qobuz_id": 41620, "qobuz_match": "exact"},
    ]
    monkeypatch.setattr(stage, "collect", lambda user, periods, count: {
        "bobby cruz": {"name": "Bobby Cruz", "mbid": "m-bc", "plays": 41,
                       "ranks": {"year": 90}},
        "jorge drexler": {"name": "Jorge Drexler", "mbid": "m-jd", "plays": 6447,
                          "ranks": {"all_time": 1}},
    })
    monkeypatch.setattr(stage, "search_artists",
                        lambda n, s: pytest_fail("should not re-resolve"))
    monkeypatch.setattr(sys, "argv", ["favourites.py", "--user", "x"])
    assert stage.main() == 0

    saved = {a["name"]: a for a in favourites_file.saved}
    assert saved["Bobby Cruz"]["watch"] is False
    assert saved["Bobby Cruz"]["plays"] == 41            # stats still refreshed
    assert "watch" not in saved["Jorge Drexler"]


def pytest_fail(message):
    raise AssertionError(message)


def test_the_radar_never_sees_a_muted_artist(tmp_path):
    from core import favourites as core_fav

    path = tmp_path / "favourites.json"
    assert core_fav.ids_for("qobuz_id", {0: "fallback"}, path) == {0: "fallback"}

    path.write_text(json.dumps({"artists": rows()}))
    assert core_fav.ids_for("qobuz_id", {0: "fallback"}, path) == {
        55: "Bobby Cruz", 41620: "Jorge Drexler"}       # Feli Colina is muted


def test_a_file_with_no_id_for_a_source_falls_back(tmp_path, capsys):
    """Resolving only Qobuz ids must not quietly empty the iTunes radar."""
    from core import favourites as core_fav

    path = tmp_path / "favourites.json"
    path.write_text(json.dumps({"artists": rows()}))
    assert core_fav.ids_for("itunes_id", {16421943: "Drexler"}, path) == {
        16421943: "Drexler"}
    assert "has no itunes_id for any artist" in capsys.readouterr().err


def test_an_unreadable_file_degrades_to_the_fallback(tmp_path, capsys):
    from core import favourites as core_fav

    path = tmp_path / "favourites.json"
    path.write_text("{ not json")
    assert core_fav.ids_for("qobuz_id", {0: "fallback"}, path) == {0: "fallback"}
    assert "ignoring unreadable" in capsys.readouterr().err
