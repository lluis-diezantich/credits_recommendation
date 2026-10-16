"""radars/remezcla.py: the shape of a roundup, locked against a fixture.

Verified separately against the whole cached corpus when the parser moved from
regex to BeautifulSoup: 314 issues, 3,799 picks, byte-identical, and the only
change in the 996 untitled rows was HTML entities in `embed_hint` arriving
decoded instead of raw.
"""

from __future__ import annotations

import radars.remezcla as rem

ISSUE = """
<html><head><script type="application/ld+json">
{"datePublished":"2026-10-14T09:00:00+00:00"}
</script></head><body>
  <section class="story__item">
    <h3 class="story__item-title">Silvana Estrada &amp; M. Ward &#8211; "Todo Baila" 3</h3>
    <p>A duet that earns its restraint. &#8212; Cheky</p>
  </section>
  <section class="story__item">
    <h3 class="story__item-title">Bemquere- "Sua Voz e Casa"</h3>
    <p>Hyphen, because the track title opens with a quote. &#8212; Marcos Hassan</p>
  </section>
  <section class="story__item">
    <h3 class="story__item-title"></h3>
    <iframe title="Tito &quot;El Bambino&quot; &amp; Gotay - El Boom (Official Audio)"></iframe>
    <p>Empty title element. &#8212; Felipe Maia</p>
  </section>
  <section class="other">
    <h3 class="story__item-title">Not A Pick - "Wrong Section"</h3>
  </section>
</body></html>
"""


def test_picks_are_split_into_artist_and_track():
    picks, _ = rem.parse_issue(ISSUE, "/issue", "2000-01-01")
    assert len(picks) == 2
    assert picks[0]["artist"] == "Silvana Estrada & M. Ward"
    assert picks[0]["track"] == "Todo Baila"
    assert picks[0]["date"] == "2026-10-14"


def test_the_trailing_layout_number_is_not_part_of_the_name():
    picks, _ = rem.parse_issue(ISSUE, "/issue", "2000-01-01")
    assert not picks[0]["track"].endswith("3")


def test_a_hyphen_splits_only_when_the_track_opens_with_a_quote():
    """"Bemquere- "Sua Voz e Casa"" -- hyphens otherwise appear inside names."""
    picks, _ = rem.parse_issue(ISSUE, "/issue", "2000-01-01")
    assert picks[1]["artist"] == "Bemquere"
    assert picks[1]["track"] == "Sua Voz e Casa"


def test_the_byline_is_the_last_dash_introduced_name():
    picks, _ = rem.parse_issue(ISSUE, "/issue", "2000-01-01")
    assert [p["curator"] for p in picks] == ["Cheky", "Marcos Hassan"]


def test_an_empty_title_goes_to_untitled_rather_than_being_guessed(capsys):
    """The artist survives only inside the embed's title attribute, and parsing
    that back is guesswork -- so the row is kept apart for a deliberate pass."""
    picks, untitled = rem.parse_issue(ISSUE, "/issue", "2000-01-01")
    assert len(untitled) == 1
    assert untitled[0]["curator"] == "Felipe Maia"
    assert untitled[0]["date"] == "2026-10-14"
    # Entities decoded, which is what the parser rewrite changed.
    assert untitled[0]["embed_hint"] == 'Tito "El Bambino" & Gotay - El Boom (Official Audio)'


def test_only_story_items_count():
    """A title element in another section is not a pick."""
    picks, untitled = rem.parse_issue(ISSUE, "/issue", "2000-01-01")
    assert all(p["artist"] != "Not A Pick" for p in picks)
    assert len(picks) + len(untitled) == 3


def test_the_fallback_date_is_used_when_the_page_has_none():
    picks, _ = rem.parse_issue(
        '<section class="story__item"><h3 class="story__item-title">A - "B"</h3></section>',
        "/issue", "1999-12-31")
    assert picks[0]["date"] == "1999-12-31"
