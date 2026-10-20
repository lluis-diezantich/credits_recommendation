# D7: `cache/` is the source of truth for what an API said, and is not backed up

- **Status:** Accepted
- **Date:** 2026-10-17
- **Where it lives:** `cache/` (untracked), the rules in
  [`CLAUDE.md`](../../CLAUDE.md), the deferral in [../../todo.md](../../todo.md)

## Context

`cache/` holds what each API actually returned. It is what makes a rerun free —
one `discover` run on a cached seed costs a single request for the discography —
and it is the only record of a credit as it stood when it was read. Qobuz edits
credits; a refetch is not guaranteed to reproduce an old output.

## Options

1. **Treat it as disposable** and refetch when needed: nothing to maintain, and
   an edited credit is unrecoverable.
2. **Commit it to git**: durable and versioned, and 85 MB of third-party HTML in
   a repo whose point is the code.
3. **Sync it to object storage**: durable, and a dependency plus credentials for
   a laptop-sized directory.

## Decision

Option 1, measured rather than assumed. The exposure is a re-run, not a lost
corpus, so it is cheaper to refetch when relevant than to maintain a sync.

## Evidence

Measured 2026-10-17: of 85 MB, 84 MB is `cache/remezcla` — raw HTML of a blog
that is still online and re-scrapable. The part carrying real weight is 650 KB
across `cache/credits` (63 albums) and `cache/search` (10 pages), refetchable in
under a minute of requests. `cache/credits` now holds 107 albums and 500 tracks.

## Consequences

- The one thing a refetch cannot recover is a credit Qobuz has since edited or
  removed. `stages/writing.py`'s cache is what makes its output reproducible, so
  if that output ever has to be *defended* rather than regenerated, copy the
  650 KB first.
- `cache/` being untracked means tests cannot use it as a fixture ([D3](D3-offline-tests.md)).
- It also means a measurement over the corpus is not reproducible by anyone
  else, including a future session on another machine. Measurements therefore go
  into the ADR or the comment, not just the terminal.
- Object storage and `UPath` are deferred until `cache/` outgrows a laptop,
  which at 85 MB it has not.
