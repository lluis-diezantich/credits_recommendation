"""core/musicbrainz.py: the one fact no listening history can contain.

A play count cannot say whether an artist died or a band split, and the release
dates cannot either -- a dead artist keeps putting out compilations. The real
answers, which this module reads:

  Celia Cruz     Person  ended  2003-07-16
  Extremoduro    Group   ended  2019-12-17   split four years before you last
                                             played them, and still core
  Jorge Drexler  Person  active

The distinction that matters most here is "no answer" against "active". A
failed lookup must not read as a living artist.
"""

from __future__ import annotations

import json

import pytest

import core.musicbrainz as mod


@pytest.fixture
def mb(monkeypatch, tmp_path):
    """core.musicbrainz with its network and its 1/s sleep stubbed."""

    class Handle:
        def __init__(self):
            self.dir = tmp_path / "mb"
            self.replies: list[tuple] = []
            self.asked: list[str] = []
            self.slept = 0.0

        def install(self):
            monkeypatch.setattr(mod, "CACHE_DIR", self.dir)
            monkeypatch.setattr(mod, "get", self._get)
            monkeypatch.setattr(mod.time, "sleep", self._sleep)
            return mod

        def _get(self, url, **kwargs):
            self.asked.append(url)
            return self.replies.pop(0)

        def _sleep(self, seconds):
            self.slept += seconds

    return Handle()


def person(ended=False, end=None, kind="Person"):
    span = {"ended": ended}
    if end:
        span["end"] = end
    return {"name": "Someone", "type": kind, "life-span": span}


def ok(document):
    return (200, json.dumps(document), {})


# ---- artist -------------------------------------------------------------


def test_an_artist_is_fetched_once_and_cached(mb):
    mb.install()
    mb.replies = [ok(person(ended=True, end="2003-07-16"))]
    first = mod.artist("mbid-celia")
    second = mod.artist("mbid-celia")          # no second reply queued
    assert first == second
    assert len(mb.asked) == 1


def test_the_published_rate_limit_is_respected(mb):
    """One a second, strictly: a burst earns a 503 rather than a 429."""
    mb.install()
    mb.replies = [ok(person())]
    mod.artist("mbid-1")
    assert mb.slept >= 1.0


def test_a_cache_hit_costs_no_sleep(mb):
    mb.install()
    mb.replies = [ok(person())]
    mod.artist("mbid-1")
    before = mb.slept
    mod.artist("mbid-1")
    assert mb.slept == before


def test_a_refused_lookup_is_none_rather_than_an_empty_artist(mb):
    """"MusicBrainz does not know" must stay distinct from "MusicBrainz says
    active", or an outage silently marks everybody alive."""
    mb.install()
    mb.replies = [(503, "Service Temporarily Unavailable", {})]
    assert mod.artist("mbid-1") is None


def test_a_non_json_body_is_none(mb):
    mb.install()
    mb.replies = [(200, "<html>nope</html>", {})]
    assert mod.artist("mbid-1") is None


def test_nothing_is_cached_from_a_failed_lookup(mb):
    mb.install()
    mb.replies = [(503, "", {}), ok(person(ended=True, end="1993-06-29"))]
    assert mod.artist("mbid-1") is None
    assert mod.artist("mbid-1") == person(ended=True, end="1993-06-29")


def test_a_corrupt_cache_entry_is_refetched_not_fatal(mb):
    mb.install()
    mb.dir.mkdir(parents=True)
    mod.cache_path("mbid-1", mb.dir).write_text("{broken")
    mb.replies = [ok(person())]
    assert mod.artist("mbid-1") == person()


def test_refresh_re_asks_instead_of_reading_the_cache(mb):
    mb.install()
    mb.replies = [ok(person()), ok(person(ended=True, end="2019-12-17"))]
    mod.artist("mbid-1")
    again = mod.artist("mbid-1", refresh=True)
    assert again is not None and again["life-span"]["ended"] is True
    assert len(mb.asked) == 2


# ---- ended / why --------------------------------------------------------


def test_the_flag_is_the_authority_not_the_date():
    """MusicBrainz sets `ended` for a group that split on an unknown date, so a
    date-only test would read it as active."""
    assert mod.ended(person(ended=True)) == (True, None)
    assert mod.ended(person(ended=True, end="2019-12-17")) == (True, "2019-12-17")


def test_an_active_artist_and_an_unknown_one_both_read_not_ended():
    assert mod.ended(person()) == (False, None)
    assert mod.ended(None) == (False, None)


def test_an_artist_with_no_life_span_at_all_is_not_ended():
    assert mod.ended({"name": "Someone"}) == (False, None)


def test_why_separates_a_death_from_a_split():
    """Worth keeping: one is a person, the other a decision, and a report that
    says which is easier to trust."""
    assert mod.why(person(ended=True, end="2003-07-16")) == "died"
    assert mod.why(person(ended=True, end="2019-12-17", kind="Group")) == "split"
    assert mod.why(person()) == ""
    assert mod.why(None) == ""


# ---- which names an artist is credited under ----------------------------


def test_the_performing_name_comes_first():
    assert mod.names({"name": "Björk", "sort-name": "Björk"}) == ["Björk"]


def test_an_alias_is_a_name_the_artist_is_credited_under():
    """Björk's legal name is an alias, and Qobuz credits 120 of her 148 own
    albums to it -- which made her the top of her own collaborator graph."""
    assert mod.names({
        "name": "Björk", "sort-name": "Björk",
        "aliases": [{"name": "Björk Guðmundsdóttir"}, {"name": "Bjork"}],
    }) == ["Björk", "Björk Guðmundsdóttir", "Bjork"]


def test_an_is_person_relationship_is_read_as_well_as_the_aliases():
    """Aliases alone are not enough: Little Simz has NO alias for "Simbiatu
    Ajikawo" and is linked to it as a person. Missing this left 20 of her 44
    own albums credited to her own biggest "collaborator"."""
    assert mod.names({
        "name": "Little Simz",
        "relations": [{"type": "is person",
                       "artist": {"name": "Simbiatu Ajikawo",
                                  "sort-name": "Ajikawo, Simbiatu"}}],
    }) == ["Little Simz", "Simbiatu Ajikawo", "Ajikawo, Simbiatu"]


def test_other_relationships_are_not_other_names():
    """"member of band" is a different claim: SPACE AGE is not Little Simz."""
    assert mod.names({
        "name": "Little Simz",
        "relations": [{"type": "member of band", "artist": {"name": "SPACE AGE"}}],
    }) == ["Little Simz"]


def test_the_same_name_twice_is_listed_once():
    assert mod.names({"name": "Sjón", "sort-name": "Sjón",
                      "aliases": [{"name": "Sjón"}]}) == ["Sjón"]


def test_an_unreadable_artist_has_no_names_rather_than_raising():
    """None means MusicBrainz could not be read, and the caller then drops only
    the performing name -- the old behaviour -- and says so."""
    assert mod.names(None) == []
    assert mod.names({}) == []


def test_a_nameless_alias_is_skipped():
    assert mod.names({"name": "X", "aliases": [{"locale": "ja"}, {"name": "Y"}]}) == [
        "X", "Y"]
