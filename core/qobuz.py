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


def search_artists(name: str, store: str = STORE) -> list[dict]:
    """Autosuggest. Needs no app id and no cookies, and folds case and accents."""
    url = f"{SITE}/v4/{store}/catalog/search/autosuggest?q={urllib.parse.quote(name)}"
    # Qobuz returns intermittent HTTP 500 under sustained load; without a retry
    # a transient failure becomes a permanent "not_found" for that person.
    for attempt in range(3):
        status, body, _ = get(url, {"x-requested-with": "XMLHttpRequest"})
        if status == 200:
            try:
                return json.loads(body).get("artists") or []
            except json.JSONDecodeError:
                return []
        if status < 500:
            print(f"warning: search for {name!r} HTTP {status}", file=sys.stderr)
            return []
        time.sleep(0.8 * (attempt + 1))
    print(f"warning: search for {name!r} failed with 5xx after 3 tries", file=sys.stderr)
    return []


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
