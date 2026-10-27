"""core/discogs.py: the rate limit, and the gate that stops a fan-out early.

Discogs' 25 requests/minute is the binding constraint on the whole pipeline, so
the two things worth testing here are both about not spending requests:

  the throttle   reads Discogs' OWN header rather than guessing, and the 20/40/60s
                 backoff on a 429 exists because urllib3's 0.8/1.6/3.2s retries
                 all land inside the same closed 60-second rolling window. The
                 adapter cannot fix a 429 here; only the long sleep reopens it.
  the page gate  the TRUE total arrives with page 1, so a caller can stop before
                 paying for pages 2..n. Kevorkian yielded 7 rows in 3 pages
                 against a true total of 1,070, and the gate is what turns a
                 service masterer into one request instead of three plus the
                 whole Qobuz fan-out his credits would have caused.

The fixture lives here rather than in conftest.py on purpose: it stubs the
transport and captures sleeps, which is this module's internals rather than a
harness any other test would share.
"""

from __future__ import annotations

import json

import pytest

import core.discogs as dg


@pytest.fixture
def discogs(monkeypatch):
    """core.discogs with the transport, the clock and sleeping stubbed.

    `.queue` is the responses to hand back, each `(status, body)` or
    `(status, body, headers)`; a dict body is encoded for you. `.paths` records
    what was requested and `.slept` every sleep, which is how the backoff and
    the throttle interval are asserted without waiting for them.
    """
    class Handle:
        def __init__(self):
            self.queue: list = []
            self.paths: list[str] = []
            self.headers_sent: list[dict] = []
            self.slept: list[float] = []
            self.clock = 1000.0

        def _get(self, url, headers=None, timeout=30, user_agent=None,
                 service="", fatal=True):
            self.paths.append(url.replace(dg.DISCOGS, ""))
            self.headers_sent.append(dict(headers or {}))
            if not self.queue:
                return 200, json.dumps({}), {}
            item = self.queue.pop(0)
            status, body, *rest = item
            if not isinstance(body, str):
                body = json.dumps(body)
            return status, body, (rest[0] if rest else {})

        def install(self):
            monkeypatch.setattr(dg, "http_get", self._get)
            monkeypatch.setattr(dg.time, "sleep", self.slept.append)
            monkeypatch.setattr(dg.time, "monotonic", lambda: self.clock)
            return self

        def throttle(self, per_minute=25):
            return dg.Throttle(per_minute)

    return Handle().install()


# ---- Throttle -----------------------------------------------------------


def test_the_interval_comes_from_the_published_limit():
    assert dg.Throttle(25).interval == pytest.approx(2.4)
    assert dg.Throttle(60).interval == pytest.approx(1.0)


def test_a_nonsense_limit_does_not_divide_by_zero():
    """max(per_minute, 1): a caller passing 0 or a negative gets one request a
    minute, which is slow and safe rather than a crash mid-run."""
    assert dg.Throttle(0).interval == 60.0
    assert dg.Throttle(-5).interval == 60.0


def test_the_first_call_does_not_wait(discogs):
    throttle = discogs.throttle()
    throttle.wait()
    assert discogs.slept == []


def test_a_call_too_soon_sleeps_the_remainder_of_the_interval(discogs):
    throttle = discogs.throttle(60)            # 1.0s apart
    throttle.wait()
    discogs.clock += 0.25
    throttle.wait()
    assert discogs.slept == [pytest.approx(0.75)]


def test_a_call_late_enough_does_not_sleep_at_all(discogs):
    throttle = discogs.throttle(60)
    throttle.wait()
    discogs.clock += 5.0
    throttle.wait()
    assert discogs.slept == []


def test_being_nearly_out_waits_for_the_window_to_roll_over(discogs, capsys):
    """Discogs counts a 60-second ROLLING window, so the only thing that helps
    at the end of one is waiting for it to pass."""
    throttle = discogs.throttle()
    throttle.remaining = 1
    throttle.wait()
    assert 60 in discogs.slept
    assert "rate limit nearly exhausted" in capsys.readouterr().err


def test_the_remaining_count_is_cleared_after_waiting(discogs):
    """Otherwise every subsequent call sleeps 60s on a count that is now stale."""
    throttle = discogs.throttle()
    throttle.remaining = 0
    throttle.wait()
    assert throttle.remaining is None


def test_a_healthy_remaining_count_does_not_trigger_the_long_wait(discogs):
    throttle = discogs.throttle()
    throttle.remaining = 20
    throttle.wait()
    assert 60 not in discogs.slept


def test_the_remaining_count_is_read_from_discogs_own_header():
    throttle = dg.Throttle(25)
    throttle.note({"x-discogs-ratelimit-remaining": "7"})
    assert throttle.remaining == 7


def test_a_header_that_is_not_a_number_is_treated_as_unknown():
    """Unknown, not zero: guessing zero would sleep 60s on a malformed header."""
    throttle = dg.Throttle(25)
    throttle.remaining = 5
    throttle.note({"x-discogs-ratelimit-remaining": "lots"})
    assert throttle.remaining is None


def test_an_absent_header_leaves_what_was_already_known():
    throttle = dg.Throttle(25)
    throttle.remaining = 5
    throttle.note({})
    assert throttle.remaining == 5


# ---- discogs_get --------------------------------------------------------


def test_a_good_response_is_parsed(discogs):
    discogs.queue = [(200, {"id": 1})]
    assert dg.discogs_get("/x", discogs.throttle(), None) == {"id": 1}


def test_a_token_is_sent_as_an_authorization_header(discogs):
    discogs.queue = [(200, {})]
    dg.discogs_get("/x", discogs.throttle(), "secret")
    assert discogs.headers_sent[0]["Authorization"] == "Discogs token=secret"


def test_no_token_sends_no_authorization_header(discogs):
    """Discogs allows 25/min unauthenticated, so running without one is a
    supported mode rather than a misconfiguration."""
    discogs.queue = [(200, {})]
    dg.discogs_get("/x", discogs.throttle(), None)
    assert "Authorization" not in discogs.headers_sent[0]


def test_an_unreachable_host_warns_and_returns_none(discogs, capsys):
    """fatal=False in the call: this walks hundreds of people at 25 a minute and
    its stage writes nothing until the end, so a SystemExit from the middle
    throws away every lookup already paid for."""
    discogs.queue = [(0, "connection reset")]
    assert dg.discogs_get("/x", discogs.throttle(), None) is None
    assert "unreachable: connection reset" in capsys.readouterr().err


def test_a_non_200_warns_and_returns_none(discogs, capsys):
    discogs.queue = [(404, "")]
    assert dg.discogs_get("/x", discogs.throttle(), None) is None
    assert "HTTP 404" in capsys.readouterr().err


def test_a_body_that_is_not_json_is_none_rather_than_a_crash(discogs):
    discogs.queue = [(200, "<html>nope</html>")]
    assert dg.discogs_get("/x", discogs.throttle(), None) is None


def test_a_429_backs_off_in_twenty_second_steps_then_succeeds(discogs, capsys):
    """20/40/60s, not urllib3's 0.8/1.6/3.2 — those three all land inside the
    same closed 60-second window, which is why the adapter cannot help here."""
    discogs.queue = [(429, ""), (429, ""), (200, {"ok": True})]
    assert dg.discogs_get("/x", discogs.throttle(), None) == {"ok": True}
    assert [s for s in discogs.slept if s in (20, 40, 60)] == [20, 40]
    assert "HTTP 429, backing off 20s" in capsys.readouterr().err


def test_a_429_that_never_clears_gives_up_after_three_retries(discogs, capsys):
    discogs.queue = [(429, "")] * 5
    assert dg.discogs_get("/x", discogs.throttle(), None) is None
    assert len(discogs.paths) == 4              # the first try, plus three
    assert "HTTP 429" in capsys.readouterr().err


def test_the_rate_limit_header_is_read_even_on_a_429(discogs):
    """"the 429 is precisely when its value matters" -- reading it only on the
    happy path would discard the number that explains the failure."""
    throttle = discogs.throttle()
    discogs.queue = [(429, "", {"x-discogs-ratelimit-remaining": "0"}),
                     (200, {}, {"x-discogs-ratelimit-remaining": "24"})]
    dg.discogs_get("/x", throttle, None)
    assert throttle.remaining == 24            # the later header won


def test_the_header_is_read_on_a_failure_too(discogs):
    throttle = discogs.throttle()
    discogs.queue = [(500, "", {"x-discogs-ratelimit-remaining": "3"})]
    dg.discogs_get("/x", throttle, None)
    assert throttle.remaining == 3


# ---- find_discogs_artist ------------------------------------------------


def results(*titles_and_ids):
    return {"results": [{"title": t, "id": i} for t, i in titles_and_ids]}


def test_an_exact_match_is_found(discogs):
    discogs.queue = [(200, results(("Carles Campi Campon", 42)))]
    hit, how = dg.find_discogs_artist(["Carles Campi Campon"], discogs.throttle(), None)
    assert (hit["id"], how) == (42, "exact")


def test_discogs_own_name_decorations_are_stripped_before_matching(discogs):
    """"Mauro (5)" disambiguates same-named artists and "Valeria Castro*" marks
    a name variation. Both would fail an exact match verbatim."""
    discogs.queue = [(200, results(("Mauro (5)", 7)))]
    hit, how = dg.find_discogs_artist(["Mauro"], discogs.throttle(), None)
    assert (hit["id"], how) == (7, "exact")

    discogs.queue = [(200, results(("Valeria Castro*", 8)))]
    hit, how = dg.find_discogs_artist(["Valeria Castro"], discogs.throttle(), None)
    assert (hit["id"], how) == (8, "exact")


def test_accents_and_case_fold(discogs):
    discogs.queue = [(200, results(("JORGE DREXLER", 1)))]
    hit, _ = dg.find_discogs_artist(["Jorge Drexler"], discogs.throttle(), None)
    assert hit["id"] == 1


def test_candidates_that_match_nothing_are_not_guessed_at(discogs):
    """Same discipline as qobuz pick(): a wrong artist here injects a whole
    bogus collaborator network, which is very hard to notice downstream."""
    discogs.queue = [(200, results(("Somebody Else", 1)))]
    assert dg.find_discogs_artist(["Carles Campi Campon"], discogs.throttle(),
                                  None) == (None, "no_exact_match")


def test_several_exact_matches_prefer_the_lowest_id_and_say_ambiguous(discogs):
    """With nothing to choose on, Discogs numbers the canonical entry first.

    Only a fallback since the spelling rule below: all three titles here are
    the name as written, so the id is all that is left to sort on.
    """
    discogs.queue = [(200, results(("Mauro", 900), ("Mauro", 12), ("Mauro", 55)))]
    hit, how = dg.find_discogs_artist(["Mauro"], discogs.throttle(), None)
    assert (hit["id"], how) == (12, "ambiguous")


def test_the_spelling_as_written_beats_a_lower_id(discogs):
    """The accent is the discriminator, and normalise() has already folded it.

    Measured 2026-10-24: "Mana" matched Discogs id 6859 (21 releases) over id
    570007 "Mana" (505), because the fold made four candidates equal and the
    lowest id won. The direction is what makes it serious -- a wrong id reads
    as a SMALL catalogue, so a ubiquity penalty built on it would rank one of
    Latin America's biggest bands as highly selective.
    """
    discogs.queue = [(200, results(("Mana", 6859), ("Man\u00e1", 570007),
                                   ("Mana (4)", 407925)))]
    hit, how = dg.find_discogs_artist(["Man\u00e1"], discogs.throttle(), None)
    assert (hit["id"], how) == (570007, "ambiguous")


def test_the_spelling_rule_reads_every_spelling_the_credits_used(discogs):
    """`names` is a list because one person arrives under several spellings;
    a literal match against any of them beats a lower id."""
    discogs.queue = [(200, results(("C\u00e1rles Campon", 11),
                                   ("Carles Campon", 99)))]
    hit, _ = dg.find_discogs_artist(["Carles Campi Campon", "Carles Campon"],
                                    discogs.throttle(), None)
    assert hit["id"] == 99


def test_the_next_spelling_is_tried_when_the_first_finds_nothing(discogs):
    discogs.queue = [(200, {"results": []}),
                     (200, results(("Lucas Piedra Cueva", 3)))]
    hit, how = dg.find_discogs_artist(["Lucas Piedracueva", "Lucas Piedra Cueva"],
                                      discogs.throttle(), None)
    assert (hit["id"], how) == (3, "exact")
    assert len(discogs.paths) == 2


def test_the_next_spelling_is_tried_when_the_first_matches_nothing_exactly(discogs):
    """Results but no exact match is not the end: another spelling may land."""
    discogs.queue = [(200, results(("Wrong Person", 1))),
                     (200, results(("Carles Campon", 4)))]
    hit, _ = dg.find_discogs_artist(["Carles Campi Campon", "Carles Campon"],
                                    discogs.throttle(), None)
    assert hit["id"] == 4


def test_a_failed_search_is_not_an_exact_match(discogs):
    discogs.queue = [(500, "")]
    assert dg.find_discogs_artist(["Anyone"], discogs.throttle(),
                                  None) == (None, "no_exact_match")


def test_the_search_is_scoped_to_artists(discogs):
    discogs.queue = [(200, {"results": []})]
    dg.find_discogs_artist(["Ana Prada"], discogs.throttle(), None)
    assert "type=artist" in discogs.paths[0]
    assert "q=Ana+Prada" in discogs.paths[0]


# ---- discogs_credits ----------------------------------------------------


def page(releases, items=None, pages=1):
    return {"releases": releases,
            "pagination": {"items": items if items is not None else len(releases),
                           "pages": pages}}


def release(role="Producer", artist="Someone", title="A Record", year=2020):
    return {"role": role, "artist": artist, "title": title, "year": year}


def test_a_credit_is_returned_with_its_role_and_year(discogs):
    discogs.queue = [(200, page([release(role="Mixed By", year=1999)]))]
    credits, own, total, gated = dg.discogs_credits(1, discogs.throttle(), None, 3)
    assert credits == [{"year": 1999, "role": "Mixed By", "artist": "Someone",
                        "title": "A Record"}]
    assert (own, gated) == ([], False)


def test_their_own_releases_are_kept_apart_from_their_credits(discogs):
    """For someone with no Qobuz page, a Main credit is new information rather
    than a collaboration -- so it goes in its own bucket, not the graph."""
    discogs.queue = [(200, page([release(role="Main", title="Theirs"),
                                 release(role="Producer", title="Somebody's")]))]
    credits, own, _, _ = dg.discogs_credits(1, discogs.throttle(), None, 3)
    assert [c["title"] for c in credits] == ["Somebody's"]
    assert [o["title"] for o in own] == ["Theirs"]


@pytest.mark.parametrize("role", ["Appearance", "TrackAppearance",
                                  "UnofficialRelease"])
def test_the_roles_that_are_not_a_working_credit_are_dropped(discogs, role):
    """249 of 300 rows on one artist were compilation inclusions, so this is
    not optional filtering."""
    discogs.queue = [(200, page([release(role=role)]))]
    credits, own, _, _ = dg.discogs_credits(1, discogs.throttle(), None, 3)
    assert (credits, own) == ([], [])


def test_the_artist_name_on_a_credit_is_stripped_of_its_decorations(discogs):
    discogs.queue = [(200, page([release(artist="Valeria Castro*")]))]
    credits, _, _, _ = dg.discogs_credits(1, discogs.throttle(), None, 3)
    assert credits[0]["artist"] == "Valeria Castro"


def test_the_true_total_is_returned_not_the_number_of_rows_kept(discogs):
    """The whole reason the signature has four values. Kevorkian yielded 7 rows
    against a true total of 1,070; using the fetched count as a selectivity
    measure would rank him the most selective person in the file."""
    discogs.queue = [(200, page([release(role="Appearance")] * 99
                                + [release(role="Mixed By")], items=1070))]
    credits, _, total, _ = dg.discogs_credits(1, discogs.throttle(), None, 3)
    assert len(credits) == 1
    assert total == 1070


def test_the_gate_sees_the_true_total_on_page_one_and_can_stop(discogs):
    """A service masterer costs one request instead of max_pages, and the Qobuz
    fan-out his credits would have caused never starts."""
    discogs.queue = [(200, page([release()], items=1070, pages=11))]
    seen = []
    credits, own, total, gated = dg.discogs_credits(
        1, discogs.throttle(), None, 3, gate=lambda t: seen.append(t) or t <= 600)

    assert seen == [1070]
    assert gated is True
    assert total == 1070
    assert len(discogs.paths) == 1             # page 2 never requested


def test_a_gate_that_says_go_does_not_stop_the_paging(discogs):
    discogs.queue = [(200, page([release(title="p1")], items=2, pages=2)),
                     (200, page([release(title="p2")], items=2, pages=2))]
    credits, _, total, gated = dg.discogs_credits(
        1, discogs.throttle(), None, 3, gate=lambda t: True)
    assert [c["title"] for c in credits] == ["p1", "p2"]
    assert gated is False


def test_no_gate_at_all_pages_normally(discogs):
    discogs.queue = [(200, page([release()], pages=2)),
                     (200, page([release()], pages=2))]
    credits, _, _, gated = dg.discogs_credits(1, discogs.throttle(), None, 3)
    assert len(credits) == 2 and gated is False


def test_the_gate_is_only_consulted_on_page_one(discogs):
    """It exists to avoid paying for pages 2..n, so asking again on page 2 would
    be asking after the money was spent."""
    discogs.queue = [(200, page([release()], items=5, pages=3)),
                     (200, page([release()], items=5, pages=3)),
                     (200, page([release()], items=5, pages=3))]
    calls = []
    dg.discogs_credits(1, discogs.throttle(), None, 3,
                       gate=lambda t: calls.append(t) or True)
    assert calls == [5]


def test_max_pages_caps_the_spend(discogs):
    discogs.queue = [(200, page([release()], pages=99))] * 10
    dg.discogs_credits(1, discogs.throttle(), None, 2)
    assert len(discogs.paths) == 2


def test_paging_stops_at_the_last_page_discogs_reports(discogs):
    discogs.queue = [(200, page([release()], pages=2)),
                     (200, page([release()], pages=2))]
    dg.discogs_credits(1, discogs.throttle(), None, 10)
    assert len(discogs.paths) == 2


def test_a_failed_page_keeps_what_the_earlier_pages_returned(discogs):
    """The stage writes nothing until the end, so discarding a partial result
    throws away every request already paid for."""
    discogs.queue = [(200, page([release(title="kept")], items=9, pages=5)),
                     (500, "")]
    credits, _, total, gated = dg.discogs_credits(1, discogs.throttle(), None, 5)
    assert [c["title"] for c in credits] == ["kept"]
    assert (total, gated) == (9, False)


def test_a_failed_first_page_is_empty_rather_than_an_error(discogs):
    discogs.queue = [(500, "")]
    assert dg.discogs_credits(1, discogs.throttle(), None, 3) == ([], [], 0, False)


def test_the_pages_are_requested_newest_first(discogs):
    """sort=year desc: with max_pages truncating, the pages worth having are the
    recent ones."""
    discogs.queue = [(200, page([release()]))]
    dg.discogs_credits(1, discogs.throttle(), None, 3)
    assert "sort=year" in discogs.paths[0]
    assert "sort_order=desc" in discogs.paths[0]
    assert "per_page=100" in discogs.paths[0]


def test_every_request_goes_through_the_throttle(discogs):
    """Three pages is three waits. The throttle is per REQUEST, not per person,
    because the limit is."""
    discogs.queue = [(200, page([release()], pages=3))] * 3
    throttle = discogs.throttle(60)
    discogs.clock = 1000.0
    dg.discogs_credits(1, throttle, None, 3)
    # the first wait is free; the clock never advances, so pages 2 and 3 each
    # sleep the full interval
    assert discogs.slept == [pytest.approx(1.0), pytest.approx(1.0)]
