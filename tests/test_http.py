"""The retry policy, which moved out of core/qobuz.py into the transport."""

from __future__ import annotations

import core.http as http


def test_retries_5xx_and_429_but_not_404():
    """Why these: Qobuz 500s under sustained load, and a weekly job hitting one
    host ninety times in a row is exactly what earns a 429. A 404 is an answer,
    not a failure, so retrying it only wastes the budget."""
    retry = http.SESSION.get_adapter("https://example.com").max_retries
    assert retry.is_retry("GET", 500)
    assert retry.is_retry("GET", 502)
    assert retry.is_retry("GET", 503)
    assert retry.is_retry("GET", 429)
    assert not retry.is_retry("GET", 404)
    assert not retry.is_retry("GET", 400)
    assert not retry.is_retry("GET", 200)


def test_only_idempotent_methods_are_retried():
    retry = http.SESSION.get_adapter("https://example.com").max_retries
    assert not retry.is_retry("POST", 503)


def test_a_status_is_returned_not_raised():
    """The callers read the API's own error text out of the body, so a 4xx has
    to come back as data. raise_on_status would turn it into an exception and
    core.qobuz.get_json's three outcomes would collapse to two."""
    retry = http.SESSION.get_adapter("https://example.com").max_retries
    assert retry.raise_on_status is False
    assert retry.respect_retry_after_header is True
    assert retry.total == http.RETRIES
    assert retry.backoff_factor == http.BACKOFF


def test_connection_is_pooled():
    """One TLS handshake for a run of ~90 sequential requests, not ninety."""
    adapter = http.SESSION.get_adapter("https://example.com")
    assert adapter.poolmanager.connection_pool_kw.get("maxsize", 1) >= 4


def test_message_reads_the_apis_own_error():
    assert http.message('{"message": "nope"}') == "nope"
    assert http.message("not json at all") == "not json at all"
    assert len(http.message("x" * 500)) == 200
