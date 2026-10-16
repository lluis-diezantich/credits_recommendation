"""Qobuz storefront access.

APP_ID is the public web-player app id, not a secret; the API also wants the
cookies any /discover page hands out. Both were copied into four scripts.

search_artists/pick moved here from stages/resolve_qobuz.py: name resolution is
plumbing, not credits judgement, and leaving it in a stage meant anything that
wanted to look up an artist imported policy.py and the whole role vocabulary
with it.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
from collections.abc import Iterable

from core.http import get as _http_get
from core.http import message as message  # noqa: F401  (re-exported for callers)
from core.names import normalise

APP_ID = "712109809"
API = "https://www.qobuz.com/api.json/0.2"
SITE = "https://www.qobuz.com"
UA = "Mozilla/5.0"

STORE = "gb-en"
PAGE_LIMIT = 500
PAUSE = 0.22                 # Qobuz publishes no rate limit; be unhurried
RETRIES = 3                  # see get_json: 5xx under load is routine, not fatal


def get(url: str, headers: dict[str, str] | None = None, timeout: int = 40):
    """GET against Qobuz, with the storefront user agent."""
    return _http_get(url, headers=headers, timeout=timeout, user_agent=UA, service="Qobuz")


def store_cookies(store: str = STORE) -> str:
    """Cookies any public storefront page issues; the API wants them present.

    urllib exposes repeated Set-Cookie headers individually, so collect them
    all and keep just the name=value part of each.
    """
    status, _, headers = get(f"{SITE}/{store}/discover")
    if status != 200:
        raise SystemExit(f"could not load the {store} storefront (HTTP {status}) "
                         "- is that a valid store code?")
    raw = headers.get_all("Set-Cookie") or []
    pairs = [chunk.split(";", 1)[0].strip() for chunk in raw if "=" in chunk]
    return "; ".join(pairs)


def get_json(url: str, headers: dict[str, str] | None = None,
             what: str = "Qobuz") -> tuple[dict | list | None, str]:
    """(parsed body, outcome) for a Qobuz GET: "ok", "not_found" or "error".

    5xx is retried, because Qobuz returns intermittent HTTP 500 under sustained
    load and a single attempt turns a busy minute into a permanent failure. One
    watched artist that was tolerable; at a few hundred it is most runs.

    `what` names the thing being fetched, for the warning. Nothing here raises:
    a caller looping over hundreds of artists must be able to skip one.
    """
    for attempt in range(RETRIES):
        status, body, _ = get(url, headers)
        if status == 200:
            try:
                return json.loads(body), "ok"
            except json.JSONDecodeError:
                print(f"warning: {what} returned a non-JSON body", file=sys.stderr)
                return None, "error"
        if status == 404:
            return None, "not_found"
        if status < 500:
            print(f"warning: {what} HTTP {status}: {message(body)}", file=sys.stderr)
            return None, "error"
        if attempt < RETRIES - 1:
            time.sleep(0.8 * (attempt + 1))
    print(f"warning: {what} failed with 5xx after {RETRIES} tries", file=sys.stderr)
    return None, "error"


def search_artists(name: str, store: str = STORE) -> list[dict]:
    """Autosuggest. Needs no app id and no cookies, and folds case and accents."""
    url = f"{SITE}/v4/{store}/catalog/search/autosuggest?q={urllib.parse.quote(name)}"
    data, outcome = get_json(url, {"x-requested-with": "XMLHttpRequest"},
                             f"search for {name!r}")
    if outcome != "ok" or not isinstance(data, dict):
        return []
    return data.get("artists") or []


def pick(names: Iterable[str], candidates: list[dict]) -> tuple[dict | None, str]:
    """Choose a candidate matching any spelling in `names`, and say how confident.

    "exact"           one candidate whose normalised name matches a spelling
    "ambiguous"       several exact matches -- picked the one with most albums
    "not_found"       the search returned nothing at all
    "no_exact_match"  candidates, but none matched; a fuzzy pick is NOT made,
                      because a wrong artist silently poisons the pool and is
                      very hard to notice later
    """
    if not candidates:
        return None, "not_found"
    wanted = {normalise(n) for n in names}
    exact = [c for c in candidates if normalise(c.get("name") or "") in wanted]
    if not exact:
        return None, "no_exact_match"
    exact.sort(key=lambda c: -(c.get("albumsCount") or 0))
    return exact[0], ("exact" if len(exact) == 1 else "ambiguous")


def artist_name(artist_id: int, store: str = STORE,
                cookies: str | None = None) -> tuple[str | None, str]:
    """(name, outcome) for one artist id: "ok", "not_found" or "error".

    Three outcomes rather than two, because "Qobuz has no such artist" and "the
    request failed" must not look the same to a caller confirming a hand-typed
    id: one means the id is wrong, the other means try again.

    limit=1 because the caller wants the name as proof the id is real, not the
    discography -- radars/qobuz.py:artist_releases is the paging version.
    """
    query = urllib.parse.urlencode({
        "artist_id": artist_id,
        "limit": 1,
        "offset": 0,
        "zone": store.split("-")[0].upper(),
        "store": store,
    })
    headers = {"x-app-id": APP_ID,
               "cookie": cookies if cookies is not None else store_cookies(store)}
    data, outcome = get_json(f"{API}/artist/get?{query}", headers, f"artist/get {artist_id}")
    if outcome != "ok" or not isinstance(data, dict):
        return None, outcome
    # A 200 with no name is Qobuz's other way of saying the id is unknown.
    name = data.get("name")
    return (name, "ok") if name else (None, "not_found")
