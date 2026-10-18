"""--check-active: the `ended` field, and why it is not `watch`.

A mute is yours and you can lift it. An artist who died or a band that split
will not release again whatever you think about it, so the two are separate
fields and `--check-active` refreshes one without touching the other.

On the real watchlist this found six artists the Friday radar had been querying
every week: Frankie Ruiz, Fela Kuti, Enrique Morente and Joe Arroyo dead,
Extremoduro and Los Abuelos de la Nada split. Two of them are `core` in the
profile -- genuinely played, never releasing again.
"""

from __future__ import annotations

import sys

import pytest

import core.favourites as core_favourites


def rows():
    return [
        {"name": "Fela Kuti", "qobuz_id": 1, "mbid": "mb-fela"},
        {"name": "Jorge Drexler", "qobuz_id": 2, "mbid": "mb-drexler"},
        {"name": "j milo", "qobuz_id": 3},                       # no mbid
        {"name": "Feli Colina", "qobuz_id": 4, "mbid": "mb-feli", "watch": False},
    ]


def person(ended=False, end=None, kind="Person"):
    span = {"ended": ended}
    if end:
        span["end"] = end
    return {"type": kind, "life-span": span}


def run(favourites_file, monkeypatch, argv, answers, entries=None):
    """`answers` maps mbid -> a MusicBrainz document, or None for no answer."""
    stage = favourites_file.install()
    favourites_file.entries = entries if entries is not None else rows()
    monkeypatch.setattr(stage.musicbrainz, "artist",
                        lambda mbid, **kw: answers.get(mbid))
    monkeypatch.setattr(sys, "argv", ["favourites.py", *argv])
    return stage.main()


# ---- the stamp ----------------------------------------------------------


def test_a_dead_artist_is_stamped_with_the_date(favourites_file, monkeypatch, capsys):
    code = run(favourites_file, monkeypatch, ["--check-active"],
               {"mb-fela": person(True, "1997-08-02"),
                "mb-drexler": person()})
    assert code == 0
    saved = {e["name"]: e for e in favourites_file.saved}
    assert saved["Fela Kuti"]["ended"] == "1997-08-02"
    assert "ended" not in saved["Jorge Drexler"]
    assert "died" in capsys.readouterr().out


def test_a_split_group_with_no_date_is_still_stamped(favourites_file, monkeypatch):
    """The flag is the authority, so True stands in for an unknown date."""
    code = run(favourites_file, monkeypatch, ["--check-active"],
               {"mb-fela": person(True, kind="Group"), "mb-drexler": person()})
    assert code == 0
    saved = {e["name"]: e for e in favourites_file.saved}
    assert saved["Fela Kuti"]["ended"] is True


def test_an_artist_musicbrainz_now_calls_active_loses_the_stamp(
        favourites_file, monkeypatch, capsys):
    """A corrected MBID or a corrected database must be able to undo this."""
    entries = [{"name": "Wrongly Buried", "qobuz_id": 9, "mbid": "mb-x",
                "ended": "1999-01-01"}]
    code = run(favourites_file, monkeypatch, ["--check-active"],
               {"mb-x": person()}, entries=entries)
    assert code == 0
    assert "ended" not in favourites_file.saved[0]
    assert "active again" in capsys.readouterr().out


def test_no_answer_does_not_mark_anybody_active(favourites_file, monkeypatch, capsys):
    """An outage must not read as "everyone is alive" and wipe the stamps."""
    entries = [{"name": "Fela Kuti", "qobuz_id": 1, "mbid": "mb-fela",
                "ended": "1997-08-02"}]
    code = run(favourites_file, monkeypatch, ["--check-active"],
               {"mb-fela": None}, entries=entries)
    assert code == 0
    assert favourites_file.saved is None            # nothing written
    out = capsys.readouterr()
    assert "no answer" in out.err and "1 unanswered" in out.out


def test_an_artist_with_no_mbid_is_reported_not_assumed(favourites_file, monkeypatch,
                                                        capsys):
    run(favourites_file, monkeypatch, ["--check-active"],
        {"mb-fela": person(), "mb-drexler": person()})
    assert "no MBID, so unchecked: j milo" in capsys.readouterr().out


def test_a_muted_artist_is_not_asked_about(favourites_file, monkeypatch, capsys):
    """One request a second, so do not spend one on somebody already skipped."""
    asked = []
    stage = favourites_file.install()
    favourites_file.entries = rows()
    monkeypatch.setattr(stage.musicbrainz, "artist",
                        lambda mbid, **kw: asked.append(mbid) or person())
    monkeypatch.setattr(sys, "argv", ["favourites.py", "--check-active"])
    stage.main()
    assert "mb-feli" not in asked


def test_nothing_new_writes_nothing(favourites_file, monkeypatch, capsys):
    code = run(favourites_file, monkeypatch, ["--check-active"],
               {"mb-fela": person(), "mb-drexler": person()})
    assert code == 0
    assert favourites_file.saved is None
    assert "nothing changed" in capsys.readouterr().out


def test_dry_run_writes_nothing(favourites_file, monkeypatch, capsys):
    code = run(favourites_file, monkeypatch, ["--check-active", "--dry-run"],
               {"mb-fela": person(True, "1997-08-02"), "mb-drexler": person()})
    assert code == 0
    assert favourites_file.saved is None
    assert "--dry-run" in capsys.readouterr().out


def test_an_empty_watchlist_says_what_to_run_first(favourites_file, monkeypatch):
    with pytest.raises(SystemExit):
        run(favourites_file, monkeypatch, ["--check-active"], {}, entries=[])


# ---- what the radars see ------------------------------------------------


def test_an_ended_artist_is_skipped_by_every_radar(tmp_path):
    """ids_for is the one place all three radars read, so the skip lives there."""
    import json
    path = tmp_path / "favourites.json"
    path.write_text(json.dumps({"artists": [
        {"name": "Fela Kuti", "qobuz_id": 1, "ended": "1997-08-02"},
        {"name": "Jorge Drexler", "qobuz_id": 2},
    ]}))
    assert core_favourites.ids_for("qobuz_id", {}, path) == {2: "Jorge Drexler"}


def test_ended_and_watch_false_are_independent_skips(tmp_path):
    """Lifting a mute must not resurrect a dead artist, and vice versa."""
    import json
    path = tmp_path / "favourites.json"
    path.write_text(json.dumps({"artists": [
        {"name": "Dead and watched", "qobuz_id": 1, "ended": True},
        {"name": "Alive and muted", "qobuz_id": 2, "watch": False},
        {"name": "Dead and muted", "qobuz_id": 3, "ended": True, "watch": False},
        {"name": "Alive and watched", "qobuz_id": 4},
    ]}))
    assert core_favourites.ids_for("qobuz_id", {}, path) == {4: "Alive and watched"}
