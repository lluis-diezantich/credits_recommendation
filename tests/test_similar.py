"""core/similar.py and core/shown.py: the opponent, and the scoreboard.

Offline, like everything here (D3): the fetch is stubbed at `core.similar.get`
and the cache path is redirected at a tmp dir. docs/adr/D31 has the decision.
"""

from __future__ import annotations

import json

import pytest

from core import shown, similar

BODY = json.dumps([
    {"artist_mbid": "a1", "name": "Radiohead", "type": "Group", "score": 6682},
    {"artist_mbid": "a2", "name": "Portishead", "type": "Group", "score": 4936},
    {"artist_mbid": None, "name": "", "score": 10},          # no name, skipped
    {"not": "a row"},
])


@pytest.fixture
def fetched(monkeypatch):
    """Records every URL asked for, so a cache hit is visible as silence."""
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return 200, BODY, {}
    monkeypatch.setattr(similar, "get", fake_get)
    return calls


# ---- the client ---------------------------------------------------------


def test_the_rows_keep_the_order_the_api_gave_them(fetched, tmp_path):
    """The order IS the recommendation, exactly as the ranked co-appearance
    list's order is."""
    rows = similar.similar("mbid", directory=tmp_path)
    assert rows is not None
    assert [r["name"] for r in rows] == ["Radiohead", "Portishead"]
    assert rows[0]["score"] == 6682


def test_a_row_with_no_name_is_dropped_rather_than_kept_blank(fetched, tmp_path):
    rows = similar.similar("mbid", directory=tmp_path)
    assert rows is not None
    assert all(r["name"] for r in rows)


def test_a_body_that_is_not_a_list_is_no_rows(monkeypatch, tmp_path):
    """The API answers with an array. Anything else is an outage page."""
    monkeypatch.setattr(similar, "get",
                        lambda url, **kw: (200, '{"error": "nope"}', {}))
    assert similar.similar("mbid", directory=tmp_path) == []


def test_a_second_run_costs_no_request(fetched, tmp_path):
    similar.similar("mbid", directory=tmp_path)
    similar.similar("mbid", directory=tmp_path)
    assert len(fetched) == 1


def test_refresh_asks_again(fetched, tmp_path):
    similar.similar("mbid", directory=tmp_path)
    similar.similar("mbid", refresh=True, directory=tmp_path)
    assert len(fetched) == 2


def test_a_failed_request_is_none_and_not_an_empty_list(monkeypatch, tmp_path):
    """"ListenBrainz has no similar artists for this seed" is a result a
    comparison must be able to report. "The request failed" is not."""
    monkeypatch.setattr(similar, "get", lambda url, **kw: (503, "", {}))
    assert similar.similar("mbid", directory=tmp_path) is None
    assert not similar.cache_path("mbid", tmp_path).exists()


def test_a_corrupt_cache_entry_is_refetched(fetched, tmp_path):
    similar.cache_path("mbid", tmp_path).write_text("{ not json")
    assert similar.similar("mbid", directory=tmp_path)
    assert len(fetched) == 1


def test_non_json_from_the_api_is_no_rows_rather_than_a_crash(monkeypatch,
                                                              tmp_path):
    monkeypatch.setattr(similar, "get", lambda url, **kw: (200, "<html>", {}))
    assert similar.similar("mbid", directory=tmp_path) == []


def test_the_algorithm_is_in_the_cache_filename(tmp_path):
    """A run under a different similarity model must not read this one's file:
    a silent mix of two would be a comparison of nothing in particular."""
    assert "session_based" in similar.cache_path("mbid", tmp_path).name
    assert "mbid" in similar.cache_path("mbid", tmp_path).name


def test_the_algorithm_is_pinned_and_in_the_request(fetched, tmp_path):
    similar.similar("mbid", directory=tmp_path)
    assert similar.ALGORITHM in fetched[0]
    assert "artist_mbids=mbid" in fetched[0]


# ---- the scoreboard -----------------------------------------------------


def test_no_file_is_no_runs_rather_than_a_crash(tmp_path):
    assert shown.load(tmp_path) == []


def test_a_hand_mangled_file_is_no_runs(tmp_path):
    shown.path(tmp_path).write_text('{"runs": 7}')
    assert shown.load(tmp_path) == []


def test_an_entry_records_the_source_the_date_and_the_claim():
    rows = [{"person_key": "a", "name": "A", "sort_key": (2.0, 3.4), "seeds": 2},
            {"person_key": "b", "name": "B", "sort_key": (1.0, 9.9), "seeds": 1}]
    run = shown.entry("breadth", "2026-10-22", rows, limit=1)
    assert run["source"] == "breadth" and run["shown"] == "2026-10-22"
    assert run["candidates"] == 2          # all of them, not just the logged one
    assert [r["rank"] for r in run["top"]] == [1]
    assert run["top"][0]["score"] == [2.0, 3.4]


def test_a_row_with_no_score_logs_none_rather_than_inventing_one():
    run = shown.entry("similar", "2026-10-22",
                      [{"person_key": "a", "name": "A"}], limit=1)
    assert run["top"][0]["score"] is None


def test_runs_accumulate(tmp_path):
    shown.append(tmp_path, shown.entry("breadth", "2026-01-01", [], 1))
    assert shown.append(tmp_path, shown.entry("similar", "2026-02-01", [], 1)) == 2
    assert [r["source"] for r in shown.load(tmp_path)] == ["breadth", "similar"]


def test_a_hit_counts_only_when_the_play_came_after_the_run():
    runs = [{"shown": "2026-01-01", "source": "breadth",
             "top": [{"person_key": "early", "name": "E"},
                     {"person_key": "late", "name": "L"}]}]
    played = {("late", "2026-01-01"): True}
    out = shown.hit_rate(runs, lambda key, when: played.get((key, when), False))
    assert out["breadth"] == (1, 2, 1)


def test_a_name_shown_twice_by_one_source_counts_once():
    """The question is whether the recommendation worked, not how often it was
    repeated."""
    runs = [{"shown": "2026-01-01", "source": "breadth",
             "top": [{"person_key": "a", "name": "A"}]},
            {"shown": "2026-02-01", "source": "breadth",
             "top": [{"person_key": "a", "name": "A"}]}]
    out = shown.hit_rate(runs, lambda key, when: True)
    assert out["breadth"] == (2, 1, 1)


def test_two_sources_are_scored_separately():
    """The whole point of one file: a hit rate is only a comparison if both
    lists are scored the same way over the same window."""
    runs = [{"shown": "2026-01-01", "source": "breadth",
             "top": [{"person_key": "a", "name": "A"}]},
            {"shown": "2026-01-01", "source": "similar",
             "top": [{"person_key": "b", "name": "B"}]}]
    out = shown.hit_rate(runs, lambda key, when: key == "a")
    assert out["breadth"] == (1, 1, 1)
    assert out["similar"] == (1, 1, 0)


def test_a_run_written_before_the_source_field_still_scores():
    """The first runs on file carry `strategy`, which is what rank.py wrote
    before baseline.py needed the same file."""
    runs = [{"shown": "2026-01-01", "strategy": "breadth",
             "top": [{"person_key": "a", "name": "A"}]}]
    assert "breadth" in shown.hit_rate(runs, lambda key, when: False)
