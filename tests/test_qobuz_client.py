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


# ---- find_artist: the one that keeps a failure apart from an absence -----
#
# Replaces stages/resolve_discogs.qobuz_find_artist, which searched a single
# spelling and could not report `ambiguous`. The distinction these tests are
# about is the one its docstring recorded: treating a 500 as a miss once
# discarded 146 of 154 collaborators on a run.


def artists(*names) -> str:
    """An autosuggest body, most-albums-first being the tie-break pick() uses."""
    import json
    return json.dumps({"artists": [
        {"id": i, "name": n, "albumsCount": 10 - i}
        for i, n in enumerate(names)]})


def test_a_failed_search_is_an_error_not_a_missing_artist(monkeypatch):
    """The whole reason this function exists rather than search_artists + pick:
    search_artists flattens a 500 to [] and pick calls that "not_found"."""
    responses(monkeypatch, (500, "boom"))
    assert cq.find_artist(["Carles Campi Campon"]) == (None, "error")


def test_an_error_stops_the_search_rather_than_trying_the_next_spelling(monkeypatch):
    """A storefront that just failed will fail again, and the caller wants the
    person marked retryable, not three requests spent proving it."""
    calls = responses(monkeypatch, (500, "boom"), (200, artists("Valeria Castro")))
    assert cq.find_artist(["Valeria Castro*", "Valeria Castro"]) == (None, "error")
    assert len(calls) == 1


def test_an_empty_result_is_not_found(monkeypatch):
    responses(monkeypatch, (200, '{"artists": []}'))
    assert cq.find_artist(["Nobody At All"]) == (None, "not_found")


def test_candidates_that_match_nothing_are_distinguished_from_none_at_all(monkeypatch):
    """Two different facts: "Qobuz has never heard the name" and "Qobuz offered
    somebody else". Only the second means a human might resolve it by hand."""
    responses(monkeypatch, (200, artists("Someone Else")))
    assert cq.find_artist(["Carles Campi Campon"]) == (None, "no_exact_match")


def test_the_second_spelling_is_tried_when_the_first_finds_nothing(monkeypatch):
    """The actual fix: these names come from Discogs credit rows, which decorate
    what they disambiguate. "Valeria Castro*" matches nothing verbatim."""
    calls = responses(monkeypatch,
                      (200, '{"artists": []}'),
                      (200, artists("Valeria Castro")))
    hit, how = cq.find_artist(["Valeria Castro*", "Valeria Castro"])
    assert (hit["name"], how) == ("Valeria Castro", "exact")
    assert len(calls) == 2


def test_a_search_under_one_spelling_can_match_a_candidate_under_another(monkeypatch):
    """Matching is against the full set, not the name that was queried -- so the
    decorated spelling's search still resolves if Qobuz answers with the clean
    one. One request, not two."""
    calls = responses(monkeypatch, (200, artists("Mauro Refosco")))
    hit, how = cq.find_artist(["Mauro (5)", "Mauro Refosco"])
    assert (hit["name"], how) == ("Mauro Refosco", "exact")
    assert len(calls) == 1


def test_several_exact_matches_are_reported_as_ambiguous(monkeypatch):
    """The other thing the deleted copy could not say. It is still a hit -- the
    most-albums candidate -- but the caller can now record that it was a guess."""
    responses(monkeypatch, (200, artists("Mauro Refosco", "Mauro Refosco")))
    hit, how = cq.find_artist(["Mauro Refosco"])
    assert how == "ambiguous"
    assert hit["albumsCount"] == 10          # most albums won


def test_a_hit_stops_the_search_early(monkeypatch):
    calls = responses(monkeypatch, (200, artists("Valeria Castro")))
    assert cq.find_artist(["Valeria Castro", "Valeria Castro*"])[1] == "exact"
    assert len(calls) == 1


def test_duplicate_and_blank_spellings_cost_no_requests(monkeypatch):
    """strip_discogs_suffix returns the name unchanged when there is nothing to
    strip, so the caller passes the same string twice on most rows."""
    calls = responses(monkeypatch, (200, artists("Ana Prada")))
    assert cq.find_artist(["Ana Prada", "Ana Prada", "", "  "])[1] == "exact"
    assert len(calls) == 1


def test_no_usable_spelling_asks_nothing(monkeypatch):
    calls = responses(monkeypatch, (200, artists("Ana Prada")))
    assert cq.find_artist(["", "   "]) == (None, "not_found")
    assert cq.find_artist([]) == (None, "not_found")
    assert calls == []


def test_search_artists_still_flattens_a_failure_for_the_human_facing_callers(monkeypatch):
    """stages/favourites.py shows a person a menu, and an empty menu is a fine
    way to say "nothing". Kept deliberately, so it is asserted deliberately."""
    responses(monkeypatch, (500, "boom"))
    assert cq.search_artists("Anyone") == []
    responses(monkeypatch, (500, "boom"))
    assert cq.search_artists_outcome("Anyone") == ([], "error")
