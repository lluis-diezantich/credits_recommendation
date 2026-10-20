# D3: Tests stub the network at the seam, and never call a real API

- **Status:** Accepted
- **Date:** 2026-10-16
- **Where it lives:** [`tests/conftest.py`](../../tests/conftest.py)

## Context

Every source here is a third-party API with a rate limit and, for Qobuz, a
public app id that a test loop would abuse. The suite runs on every push and on
three Python versions.

## Options

1. **Record and replay** real responses (VCR-style): exercises the client, and
   the cassettes rot invisibly.
2. **Stub at the seam** — one fixture per source, patched over the function that
   makes the call: fast, free, and a source changing shape is invisible.
3. **Call the real APIs in CI**: finds breakage immediately, spends the rate
   limit on every push and makes a red build depend on someone else's uptime.

## Decision

Option 2. `tests/conftest.py` stubs `qobuz` and `listenbrainz` at the seam, and
anything that writes is pointed at `tmp_path`. A new source adds a seam rather
than a live call.

## Evidence

631 tests in about 5 seconds, offline, as of 2026-10-20. The fixture that
redirects `core.listens`' month directories exists because patching only one of
`SEEDED` and `SNAPSHOTS` wrote fixtures into real data and overwrote two months
of listening.

## Consequences

- A *source* changing shape is invisible: Qobuz renaming a field or Apple
  dropping `releaseDate` leaves every test green, and the first sign is an empty
  Friday issue. The canary that closes this is specified in
  [../../todo.md](../../todo.md) and deliberately kept out of `tests.yml` — a
  third party's change is news, not a broken commit.
- Tests cannot use `cache/` or `data/` as fixtures either, since neither is
  tracked. Fixtures are written inline.
