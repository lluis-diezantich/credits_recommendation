"""One GET, one timeout, one connection pool, one retry policy.

Built on requests with an explicit urllib3 Retry, replacing the hand-rolled
urlopen wrapper and the hand-rolled 5xx loop that used to sit in
core/qobuz.py. What that buys, in order of how much it matters here:

  pooling    a radar run makes one request per watched artist -- ~90 of them,
             sequentially, to the same host. A Session reuses the connection,
             so it is one TLS handshake instead of ninety.
  retries    backoff with jitter, and Retry-After honoured when the server
             sends it. The loop this replaces slept 0.8s then 1.6s and
             ignored the header.
  one place  three radars and core/discogs.py each built their own
             urllib.request.Request. The module docstring claimed "one GET"
             while four files disagreed; now they go through here.

The return shape stays (status, body, headers) rather than a Response. Every
caller already destructures that, including radars/remezcla.py, and widening
the seam is a separate change from putting a real client behind it.
"""
from __future__ import annotations

import json

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT = 40
RETRIES = 3
BACKOFF = 0.8                    # 0.8s, 1.6s, 3.2s, plus urllib3's jitter


def _session() -> requests.Session:
    """A Session whose adapter retries 5xx and 429 on idempotent reads.

    `respect_retry_after_header` is the point: when a service says how long to
    wait, guessing is worse. 429 is included because a weekly job hitting one
    host ninety times in a row is exactly what earns one.
    """
    retry = Retry(
        total=RETRIES,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
        backoff_factor=BACKOFF,
        respect_retry_after_header=True,
        raise_on_status=False,       # hand the status back, do not raise
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=4)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


SESSION = _session()


def get(url: str, headers: dict[str, str] | None = None,
        timeout: int = DEFAULT_TIMEOUT, user_agent: str = "Mozilla/5.0",
        service: str = "the service"):
    """GET returning (status, body, response-headers).

    HTTP errors come back as a status so callers can read the API's own
    message; a dead network is fatal, because retrying it silently helps
    nobody. 5xx and 429 have already been retried by the adapter before a
    status reaches you, so a 503 here means it stayed broken.
    """
    try:
        response = SESSION.get(
            url,
            headers={"User-Agent": user_agent, **(headers or {})},
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.RequestException as error:
        raise SystemExit(f"network error talking to {service}: {error}") from error
    return response.status_code, response.text, response.headers


def message(body: str) -> str:
    """The API's own error text when it sent JSON, else the first 200 chars."""
    try:
        return json.loads(body).get("message", body[:200])
    except json.JSONDecodeError:
        return body[:200]
