"""stages/favourites.py --from-profile: candidates from measurement, not rank.

The ListenBrainz windows admit an artist on play count, which is the
confidence-weighting bug roadmap.md names, and they missed 140 artists with 24+
active months. This is the other source for the same resolve loop -- so the
test that matters is that it produces collect()'s shape and nothing downstream
can tell the difference.
"""

from __future__ import annotations

import json

import pytest

import stages.favourites as mod


def profile_file(tmp_path, artists, through="2026-05"):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"generated": "2026-10-18T00:00:00+00:00",
                                "through": through, "window": 24,
                                "floors": {"m24": 10, "deep": 24,
                                           "emerging_plays": 100},
                                "artists": artists}))
    return path


def artist(name, band="core", mbid="mb-1", plays=500, months=30):
    return {"name": name, "mbid": mbid, "band": band, "months": months,
            "recent": 12, "plays": plays, "recent_plays": plays,
            "first": "2015-01", "last": "2026-05"}


def test_it_returns_the_same_shape_collect_does(tmp_path):
    """The resolve loop is shared, so the shape is the contract."""
    path = profile_file(tmp_path, [artist("Sparklehorse")])
    merged = mod.candidates_from_profile(path)
    assert merged == {"sparklehorse": {"name": "Sparklehorse", "mbid": "mb-1",
                                       "plays": 500, "ranks": {}}}


def test_core_and_emerging_are_taken_and_lapsed_is_not(tmp_path):
    """lapsed means real past interest with nothing current -- adding it back
    would undo the point of measuring."""
    path = profile_file(tmp_path, [
        artist("Deep Current", band="core"),
        artist("Just Found", band="emerging", mbid="mb-2"),
        artist("Deep Cooled", band="lapsed", mbid="mb-3"),
    ])
    assert sorted(mod.candidates_from_profile(path)) == ["deep current", "just found"]


def test_the_band_filter_is_overridable(tmp_path):
    path = profile_file(tmp_path, [artist("Deep Cooled", band="lapsed")])
    assert list(mod.candidates_from_profile(path, bands=("lapsed",))) == ["deep cooled"]


def test_keys_are_normalised_so_the_resolve_loop_can_match_existing_entries(tmp_path):
    """Entries are matched on normalise(name); an accent must not add a row."""
    path = profile_file(tmp_path, [artist("María José Llergo")])
    assert list(mod.candidates_from_profile(path)) == ["maria jose llergo"]


def test_an_artist_with_no_mbid_is_still_a_candidate(tmp_path):
    """j milo resolves to no MBID anywhere and is still worth watching."""
    path = profile_file(tmp_path, [artist("j milo", mbid=None)])
    assert mod.candidates_from_profile(path)["j milo"]["mbid"] is None


def test_a_nameless_row_is_skipped_rather_than_keyed_empty(tmp_path):
    path = profile_file(tmp_path, [artist("Real"), {"name": "", "band": "core"}])
    assert list(mod.candidates_from_profile(path)) == ["real"]


def test_a_missing_profile_file_says_what_to_run(tmp_path, capsys):
    with pytest.raises(SystemExit) as caught:
        mod.candidates_from_profile(tmp_path / "absent.json")
    assert "--json" in str(caught.value)


def test_an_empty_profile_yields_no_candidates(tmp_path):
    assert mod.candidates_from_profile(profile_file(tmp_path, [])) == {}


def test_the_window_it_was_measured_through_is_reported(tmp_path, capsys):
    """So a stale verdict file is visible before it spends a Qobuz request."""
    mod.candidates_from_profile(profile_file(tmp_path, [artist("A")], through="2025-01"))
    assert "through 2025-01" in capsys.readouterr().err
