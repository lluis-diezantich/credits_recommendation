"""core/qobuz.py: status mapping and name resolution. No retry loop any more."""

from __future__ import annotations

import core.qobuz as cq


def responses(monkeypatch, *pairs):
    """Stub core.qobuz.get with a queue of (status, body), counting calls."""
    calls = []
    queue = list(pairs)

    def fake_get(url, headers=None, timeout=40):
        calls.append(url)
        return (*(queue.pop(0) if queue else (200, "{}")), None)

    monkeypatch.setattr(cq, "get", fake_get)
    return calls


def test_get_json_makes_exactly_one_request(monkeypatch):
    """The transport retries now. get_json retrying too would multiply the
    attempts -- three adapter retries inside three loop passes."""
    calls = responses(monkeypatch, (500, "boom"))
    assert cq.get_json("u", what="artist/get 1") == (None, "error")
    assert len(calls) == 1


def test_get_json_maps_statuses(monkeypatch):
    responses(monkeypatch, (200, '{"name": "Jorge Drexler"}'))
    assert cq.get_json("u") == ({"name": "Jorge Drexler"}, "ok")

    responses(monkeypatch, (404, ""))
    assert cq.get_json("u") == (None, "not_found")

    responses(monkeypatch, (400, '{"message": "nope"}'))
    assert cq.get_json("u") == (None, "error")

    responses(monkeypatch, (200, "not json"))
    assert cq.get_json("u") == (None, "error")


def test_artist_name_separates_unknown_from_broken(monkeypatch):
    """Three outcomes, not two: "no such artist" means the id is wrong, "error"
    means try again. Collapsing them would tell you to fix a correct id."""
    responses(monkeypatch, (200, '{"name": "Jorge Drexler"}'))
    assert cq.artist_name(41620, "gb-en", "c=1") == ("Jorge Drexler", "ok")

    responses(monkeypatch, (404, ""))
    assert cq.artist_name(999, "gb-en", "c=1") == (None, "not_found")

    responses(monkeypatch, (500, "boom"))
    assert cq.artist_name(1, "gb-en", "c=1") == (None, "error")


def test_a_200_with_no_name_is_also_unknown(monkeypatch):
    responses(monkeypatch, (200, "{}"))
    assert cq.artist_name(1, "gb-en", "c=1") == (None, "not_found")


def test_search_artists_returns_empty_on_any_failure(monkeypatch):
    responses(monkeypatch, (200, '{"artists": [{"id": 1, "name": "A"}]}'))
    assert cq.search_artists("A", "gb-en") == [{"id": 1, "name": "A"}]

    responses(monkeypatch, (500, "boom"))
    assert cq.search_artists("A", "gb-en") == []


def test_pick_is_exact_or_nothing():
    """A fuzzy pick would silently poison the pool, so there isn't one."""
    candidates = [
        {"name": "Javier Colina", "albumsCount": 9},
        {"name": "Javier Colina", "albumsCount": 40},
        {"name": "Someone Else", "albumsCount": 99},
    ]
    chosen, how = cq.pick(["Javier Colina"], candidates)
    assert how == "ambiguous" and chosen["albumsCount"] == 40

    chosen, how = cq.pick(["jorge  DREXLER"], [{"name": "Jorge Drexler", "albumsCount": 20}])
    assert how == "exact" and chosen["name"] == "Jorge Drexler"

    assert cq.pick(["Nobody"], candidates) == (None, "no_exact_match")
    assert cq.pick(["Nobody"], []) == (None, "not_found")


def test_pick_folds_accents_and_case():
    assert cq.pick(["Oscar D'Leon"], [{"name": "Óscar D'León", "albumsCount": 3}])[1] == "exact"
