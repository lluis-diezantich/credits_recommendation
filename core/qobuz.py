"""Qobuz storefront access.

APP_ID is the public web-player app id, not a secret; the API also wants the
cookies any /discover page hands out. Both were copied into four scripts.
"""
from __future__ import annotations

from core.http import get as _http_get
from core.http import message as message  # noqa: F401  (re-exported for callers)

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
