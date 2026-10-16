"""stages/favourites.py --review: fixing the matches that did not resolve."""

from __future__ import annotations

CANDIDATES = {
    "Javier Colina": [{"id": 111, "name": "Javier Colina", "albumsCount": 9},
                      {"id": 222, "name": "Javier Colina", "albumsCount": 40}],
    "Rosalia": [{"id": 333, "name": "ROSALÍA", "albumsCount": 7}],
    "Nobody At All": [],
}


def rows():
    return [
        {"name": "Javier Colina", "qobuz_id": 111, "qobuz_match": "ambiguous", "plays": 300},
        {"name": "Nobody At All", "qobuz_id": None, "qobuz_match": "not_found", "plays": 80},
        {"name": "Unwanted", "qobuz_id": None, "qobuz_match": "no_exact_match", "plays": 5},
        {"name": "Fine", "qobuz_id": 9, "qobuz_match": "exact"},
        {"name": "Already", "qobuz_id": 8, "qobuz_match": "manual"},
        {"name": "Hushed", "qobuz_id": None, "qobuz_match": "not_found", "watch": False},
    ]


def review(favourites_file, monkeypatch, answers, entries=None, dry_run=False):
    stage = favourites_file.install()
    favourites_file.entries = entries if entries is not None else rows()
    monkeypatch.setattr(stage, "search_artists",
                        lambda name, store: CANDIDATES.get(name, []))
    favourites_file.answers(answers)
    return stage.review("gb-en", dry_run)


def test_only_open_rows_are_asked_about(favourites_file, monkeypatch, capsys):
    """An exact match needs no second opinion, a manual one has already had
    yours, and a muted row is a decision too."""
    code = review(favourites_file, monkeypatch, ["2", "/Rosalia", "1", "m"])
    entries = favourites_file.entries
    out = capsys.readouterr().out

    assert code == 0
    assert "3 artists to review" in out
    assert entries[3]["qobuz_id"] == 9 and "watch" not in entries[3]
    assert entries[4]["qobuz_id"] == 8


def test_picking_a_number_records_it_as_manual(favourites_file, monkeypatch):
    """`manual` is what stops --refresh overruling you later."""
    review(favourites_file, monkeypatch, ["2", "s", "s"])
    entry = favourites_file.entries[0]
    assert entry["qobuz_id"] == 222 and entry["qobuz_match"] == "manual"


def test_slash_searches_a_different_spelling(favourites_file, monkeypatch):
    """The way out of not_found, where the artist's own name returns nothing."""
    review(favourites_file, monkeypatch, ["s", "/Rosalia", "1", "s"])
    assert favourites_file.entries[1]["qobuz_id"] == 333


def test_m_mutes_and_s_leaves_the_row_alone(favourites_file, monkeypatch, capsys):
    review(favourites_file, monkeypatch, ["s", "s", "m"])
    assert favourites_file.entries[2]["watch"] is False
    assert favourites_file.entries[0]["qobuz_id"] == 111        # skipped, unchanged
    assert "0 picked, 1 muted, 2 left open." in capsys.readouterr().out


def test_the_current_id_is_marked_so_skipping_is_an_informed_choice(
        favourites_file, monkeypatch, capsys):
    review(favourites_file, monkeypatch, ["s"],
           entries=[{"name": "Javier Colina", "qobuz_id": 222, "qobuz_match": "ambiguous"}])
    out = capsys.readouterr().out
    assert "*2." in out and " 1." in out


def test_q_saves_the_decisions_made_so_far(favourites_file, monkeypatch, capsys):
    entries = [{"name": "Javier Colina", "qobuz_id": None, "qobuz_match": "not_found"},
               {"name": "Rosalia", "qobuz_id": None, "qobuz_match": "not_found"}]
    review(favourites_file, monkeypatch, ["1", "q"], entries=entries)
    assert entries[0]["qobuz_id"] == 111 and entries[1]["qobuz_id"] is None
    assert "stopped at 2 of 2" in capsys.readouterr().out
    assert favourites_file.saved is entries


def test_junk_and_out_of_range_re_prompt(favourites_file, monkeypatch, capsys):
    review(favourites_file, monkeypatch, ["7", "x", "1", "s", "s"])
    assert capsys.readouterr().out.count("? expected") == 2


def test_dry_run_decides_but_does_not_save(favourites_file, monkeypatch, capsys):
    review(favourites_file, monkeypatch, ["1", "s", "s"], dry_run=True)
    assert favourites_file.saved is None
    assert "nothing written" in capsys.readouterr().out


def test_a_clean_file_says_there_is_nothing_to_review(favourites_file, monkeypatch, capsys):
    code = review(favourites_file, monkeypatch, [],
                  entries=[{"name": "Fine", "qobuz_id": 1, "qobuz_match": "exact"}])
    assert code == 0 and favourites_file.saved is None
    assert "nothing to review" in capsys.readouterr().out


# --- #<id>, the hand-typed escape hatch ----------------------------------

def hand_typed(favourites_file, monkeypatch, answers, names=None):
    stage = favourites_file.install()
    favourites_file.entries = [{"name": "Nobody At All", "qobuz_id": None,
                                "qobuz_match": "not_found"}]
    monkeypatch.setattr(stage, "search_artists", lambda n, s: [])
    cookies = []
    monkeypatch.setattr(stage, "store_cookies",
                        lambda store: cookies.append(store) or "c=1")
    monkeypatch.setattr(stage, "artist_name",
                        lambda i, store, c: (names or {}).get(i, (None, "error")))
    favourites_file.answers(answers)
    stage.review("gb-en", False)
    return cookies


def test_a_confirmed_id_is_accepted_and_echoed(favourites_file, monkeypatch, capsys):
    """A typo'd id would otherwise watch nobody forever and look like a quiet
    month, so it is confirmed against Qobuz before being written."""
    cookies = hand_typed(favourites_file, monkeypatch, ["#41620"],
                         {41620: ("Jorge Drexler", "ok")})
    entry = favourites_file.entries[0]
    assert entry["qobuz_id"] == 41620 and entry["qobuz_match"] == "manual"
    assert "set 41620  Jorge Drexler" in capsys.readouterr().out
    assert cookies == ["gb-en"]


def test_an_unknown_or_unreachable_id_is_never_written(favourites_file, monkeypatch, capsys):
    hand_typed(favourites_file, monkeypatch, ["#999", "#abc", "#7", "s"],
               {999: (None, "not_found")})
    out = capsys.readouterr().out
    assert "no artist 999" in out
    assert "#<id> wants a number" in out
    assert "could not confirm 7" in out
    assert favourites_file.entries[0]["qobuz_id"] is None


def test_cookies_are_only_fetched_when_an_id_is_typed(favourites_file, monkeypatch):
    """autosuggest needs none; artist/get does. A review that never types #
    should cost no extra request."""
    stage = favourites_file.install()
    favourites_file.entries = [{"name": "Javier Colina", "qobuz_id": None,
                                "qobuz_match": "not_found"}]
    monkeypatch.setattr(stage, "search_artists", lambda n, s: CANDIDATES["Javier Colina"])
    cookies = []
    monkeypatch.setattr(stage, "store_cookies",
                        lambda store: cookies.append(store) or "c=1")
    favourites_file.answers(["1"])
    stage.review("gb-en", False)
    assert cookies == []


def test_a_storefront_failure_mid_review_loses_nothing(favourites_file, monkeypatch, capsys):
    """store_cookies raises SystemExit, which would discard every decision
    made so far."""
    stage = favourites_file.install()
    favourites_file.entries = [{"name": "Javier Colina", "qobuz_id": None,
                                "qobuz_match": "not_found"}]
    monkeypatch.setattr(stage, "search_artists", lambda n, s: CANDIDATES["Javier Colina"])

    def boom(store):
        raise SystemExit("could not load the zz-zz storefront (HTTP 404)")

    monkeypatch.setattr(stage, "store_cookies", boom)
    favourites_file.answers(["#41620", "1"])
    stage.review("gb-en", False)

    assert "could not load the zz-zz storefront" in capsys.readouterr().out
    assert favourites_file.entries[0]["qobuz_id"] == 111
    assert favourites_file.saved is favourites_file.entries
