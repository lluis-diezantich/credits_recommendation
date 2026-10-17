"""Discogs access: throttle, GET, artist lookup, credit paging.

Discogs is used only as a reverse index -- it has an entity for every engineer
Qobuz cannot see. Its 25 req/min (60 with a token) is the binding constraint on
the whole pipeline, so the Throttle here reads Discogs' own headers rather than
guessing.

Lifted from the original discogs_resolve.py, including the page-1 gate that
lets a caller stop before paying for pages 2..n. The hand-rolled urlopen went
with the rest of them: this now goes through core/http.py, which pools the
connection and honours Retry-After. The 429 backoff below STAYS, because
urllib3 retries a 429 in 0.8/1.6/3.2s and Discogs is counting a 60-second
rolling window -- the adapter's three tries all land inside the same closed
window, and the long sleep is what actually reopens it.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
from collections.abc import Callable

from core.http import get as http_get
from core.names import normalise, strip_discogs_suffix

DISCOGS = "https://api.discogs.com"
# Discogs requires a descriptive User-Agent and blocks generic ones.
DISCOGS_UA = "fresh-releases-radar/1.0 +https://github.com/local/fresh-releases"

# Discogs `role` values that are NOT a working credit.
#   Main            - their own release as the billed artist (kept separately:
#                     for someone with no Qobuz page these are new information)
#   Appearance /    - compilation inclusions. 249 of 300 rows on one artist, so
#   TrackAppearance   filtering these out is not optional.
NOT_A_CREDIT = {"Appearance", "TrackAppearance", "UnofficialRelease"}

PAGE_LIMIT = 500


class Throttle:
    """Keeps us inside Discogs' published rate limit, using its own headers."""

    def __init__(self, per_minute: int) -> None:
        self.interval = 60.0 / max(per_minute, 1)
        self.last = 0.0
        self.remaining: int | None = None

    def wait(self) -> None:
        # If Discogs says we are nearly out, pause for the window to roll over.
        if self.remaining is not None and self.remaining <= 1:
            print("  [throttle] rate limit nearly exhausted, waiting 60s", file=sys.stderr)
            time.sleep(60)
            self.remaining = None
        gap = time.monotonic() - self.last
        if gap < self.interval:
            time.sleep(self.interval - gap)
        self.last = time.monotonic()

    def note(self, headers) -> None:
        value = headers.get("x-discogs-ratelimit-remaining")
        if value is not None:
            try:
                self.remaining = int(value)
            except ValueError:
                self.remaining = None


def discogs_get(path: str, throttle: Throttle, token: str | None,
                attempt: int = 0) -> dict | None:
    """One Discogs GET, or None. Never raises -- a caller is mid-loop.

    The rate-limit header is read on every outcome, not just the happy one:
    a 429 is precisely when its value matters.
    """
    throttle.wait()
    headers = {"Authorization": f"Discogs token={token}"} if token else {}
    status, body, response_headers = http_get(
        f"{DISCOGS}{path}", headers=headers, timeout=30,
        user_agent=DISCOGS_UA, service="Discogs", fatal=False)
    throttle.note(response_headers)
    if status == 0:
        print(f"warning: discogs {path} unreachable: {body}", file=sys.stderr)
        return None
    if status == 429 and attempt < 3:
        back = 20 * (attempt + 1)
        print(f"  [throttle] HTTP 429, backing off {back}s", file=sys.stderr)
        time.sleep(back)
        return discogs_get(path, throttle, token, attempt + 1)
    if status != 200:
        print(f"warning: discogs {path} HTTP {status}", file=sys.stderr)
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def find_discogs_artist(names: list[str], throttle: Throttle,
                        token: str | None) -> tuple[dict | None, str]:
    """Exact-match only, on any spelling the Qobuz credits used.

    Same discipline as qobuz_resolve.pick(): a wrong artist here injects a whole
    bogus collaborator network, which is very hard to notice downstream.
    """
    wanted = {normalise(n) for n in names}
    for name in names:
        query = urllib.parse.urlencode({"q": name, "type": "artist"})
        data = discogs_get(f"/database/search?{query}", throttle, token)
        results = (data or {}).get("results") or []
        if not results:
            continue
        exact = [r for r in results
                 if normalise(strip_discogs_suffix(r.get("title") or "")) in wanted]
        if exact:
            # Prefer the lowest id: Discogs numbers the canonical entry first and
            # suffixes later duplicates.
            exact.sort(key=lambda r: r.get("id") or 0)
            return exact[0], "exact" if len(exact) == 1 else "ambiguous"
    return None, "no_exact_match"


def discogs_credits(artist_id: int, throttle: Throttle, token: str | None,
                    max_pages: int,
                    gate: Callable[[int], bool] | None = None,
                    ) -> tuple[list[dict], list[dict], int, bool]:
    """(credited releases, their own releases, TRUE total, was_gated).

    The third value matters: the first two are truncated by max_pages and by
    Appearance filtering, so they badly understate prolific people. Kevorkian
    yielded 7 rows in 3 pages against a true total of 1,070 -- using the fetched
    count as a selectivity measure would rank him as the most selective person
    in the file, which is exactly backwards.

    Because that true total arrives with page 1, `gate` gets to see it there and
    say stop: a service masterer costs one page instead of max_pages, and the
    Qobuz fan-out his credits would have caused never starts.
    """
    credits, own = [], []
    total = 0
    page = 1
    while page <= max_pages:
        query = urllib.parse.urlencode({"per_page": 100, "page": page,
                                        "sort": "year", "sort_order": "desc"})
        data = discogs_get(f"/artists/{artist_id}/releases?{query}", throttle, token)
        if not data:
            break
        for release in data.get("releases") or []:
            role = release.get("role") or ""
            if role in NOT_A_CREDIT:
                continue
            row = {"year": release.get("year"), "role": role,
                   "artist": strip_discogs_suffix(release.get("artist") or ""),
                   "title": release.get("title")}
            (own if role == "Main" else credits).append(row)
        pagination = data.get("pagination") or {}
        total = pagination.get("items") or total
        if page == 1 and gate is not None and not gate(total):
            return credits, own, total, True
        if page >= (pagination.get("pages") or 1):
            break
        page += 1
    return credits, own, total, False
