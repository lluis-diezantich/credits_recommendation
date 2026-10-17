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
import urllib.parse
from collections.abc import Iterable

from core.http import SESSION
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


def get(url: str, headers: dict[str, str] | None = None, timeout: int = 40):
    """GET against Qobuz, with the storefront user agent."""
    return _http_get(url, headers=headers, timeout=timeout, user_agent=UA, service="Qobuz")


def store_cookies(store: str = STORE) -> str:
    """Cookies any public storefront page issues; the API wants them present.

    Loading the page is what matters: core.http's shared Session keeps a
    cookie jar, so every later request to qobuz.com carries these whether or
    not the caller passes them on. The string is still returned because
    callers thread it through an explicit `cookie` header, and because being
    able to see what was issued is worth more than the line it costs.

    Reading the jar rather than the Set-Cookie headers is not a detail: urllib
    exposed repeated headers via get_all(), requests folds them into one
    CaseInsensitiveDict, and only the jar has them separated.
    """
    status, _, _ = get(f"{SITE}/{store}/discover")
    if status != 200:
        raise SystemExit(f"could not load the {store} storefront (HTTP {status}) "
                         "- is that a valid store code?")
    return "; ".join(f"{c.name}={c.value}" for c in SESSION.cookies
                     if c.name and "qobuz" in (c.domain or "qobuz"))


def get_json(url: str, headers: dict[str, str] | None = None,
             what: str = "Qobuz") -> tuple[dict | list | None, str]:
    """(parsed body, outcome) for a Qobuz GET: "ok", "not_found" or "error".

    No retry loop here: core.http's adapter has already retried 5xx and 429
    with backoff before a status arrives, so a 503 at this point means it
    stayed broken. That loop used to live here and ignored Retry-After.

    `what` names the thing being fetched, for the warning. Nothing here raises:
    a caller looping over hundreds of artists must be able to skip one.
    """
    status, body, _ = get(url, headers)
    if status == 200:
        try:
            return json.loads(body), "ok"
        except json.JSONDecodeError:
            print(f"warning: {what} returned a non-JSON body", file=sys.stderr)
            return None, "error"
    if status == 404:
        return None, "not_found"
    print(f"warning: {what} HTTP {status}: {message(body)}", file=sys.stderr)
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


def artist_releases(artist_id: int, store: str,
                    cookies: str) -> tuple[str, list[dict], bool]:
    """(artist name, every release where they are a primary artist, succeeded).

    `extra=albums_with_last_release` puts the discography under
    `albums_without_last_release`. Paginated because prolific artists exceed
    one page.

    This was the same loop in four files -- radars/qobuz.py, stages/discover.py,
    stages/resolve_qobuz.py and stages/resolve_discogs.py -- and they had
    already drifted on the only interesting question, which is what to do when
    a page fails: one raised SystemExit, one warned and returned what it had,
    one returned silently, one handed back a flag. The flag is the shape that
    keeps every option open, so it is the one that moved here. get_json has
    already retried and warned by this point; the caller decides whether a
    partial discography is fatal.

    Never raises. One artist failing used to abort radars/qobuz.py's whole run,
    and because the state file is written at the end, that threw away every
    release found before it -- fine when the watchlist held one artist, ruinous
    at a few hundred, where an intermittent 5xx is expected rather than
    unlucky. Partial results are safe there: what was not seen is simply not
    recorded as seen, so it is reported next run.
    """
    zone = store.split("-")[0].upper()
    headers = {"x-app-id": APP_ID, "cookie": cookies}
    name = "?"
    collected: list[dict] = []
    offset = 0

    while True:
        query = urllib.parse.urlencode({
            "artist_id": artist_id,
            "extra": "albums_with_last_release",
            "limit": PAGE_LIMIT,
            "offset": offset,
            "zone": zone,
            "store": store,
        })
        data, outcome = get_json(f"{API}/artist/get?{query}", headers,
                                 f"artist/get {artist_id}")
        if outcome != "ok" or not isinstance(data, dict):
            return name, collected, False

        name = data.get("name") or name
        page = (data.get("albums_without_last_release") or {}).get("items") or []
        # Skip releases where this artist is only a composer or a guest: the
        # discography otherwise fills up with other people's records.
        collected += [album for album in page
                      if any(str(a.get("id")) == str(artist_id)
                             for a in (album.get("artists") or []))]
        if len(page) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT

    return name, collected, True
