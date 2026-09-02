"""One GET, one timeout.

The three copies this replaces had drifted to timeout=30 in one file and 40 in
the other two, with the docstring present in some and not others. 40 wins: it
is the majority and the more forgiving.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

DEFAULT_TIMEOUT = 40


def get(url: str, headers: dict[str, str] | None = None,
        timeout: int = DEFAULT_TIMEOUT, user_agent: str = "Mozilla/5.0",
        service: str = "the service"):
    """GET returning (status, body, response-headers).

    HTTP errors come back as a status so callers can read the API's own message;
    a dead network is fatal, because retrying it silently helps nobody.
    """
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace"), response.headers
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace"), error.headers
    except urllib.error.URLError as error:
        raise SystemExit(f"network error talking to {service}: {error.reason}")


def message(body: str) -> str:
    """The API's own error text when it sent JSON, else the first 200 chars."""
    try:
        return json.loads(body).get("message", body[:200])
    except json.JSONDecodeError:
        return body[:200]
