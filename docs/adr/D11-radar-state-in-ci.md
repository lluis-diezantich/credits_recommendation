# D11: Radar state lives in `data/ci/`, committed by the workflow after the issue opens

- **Status:** Accepted
- **Date:** 2026-10-17
- **Where it lives:** [`core/radar.py`](../../core/radar.py) (`--state PATH`),
  `.github/workflows/radar.yml`, `data/ci/<radar>_seen.json`

## Context

A radar must not report the same release twice, so it needs somewhere durable to
remember what it has already shown. The run happens on a GitHub runner, which
keeps nothing between runs.

## Options

1. **Stateless, filtered by a date window**: nothing to store, and a release
   reappears whenever the window moves.
2. **State in the repo, committed by the workflow**: durable, versioned, and the
   git history of that file becomes a dated log of what was actually reported.
3. **An external store** (a gist, a bucket): no commits in the repo, and
   credentials plus a dependency for one JSON file.

## Decision

Option 2, with `--state PATH` on `core/radar.py` so the path is the caller's
choice; `stateless: true` remains for a backfill.

## Evidence

Not a measurement. The log it produces is the impression data the evaluation in
[../roadmap.md](../roadmap.md) needs, and that was the deciding factor. Expect
the first stateful commit to be ~136 KB, because `record_scanned` is true for
Qobuz — a run records every id it *scanned*, which is what stops an old release
resurfacing the week it falls out of the date window.

## Consequences

Four things here are load-bearing rather than incidental, and are recorded in
[../../todo.md](../../todo.md) so nobody tidies them:

- **`data/ci/`, not `data/<radar>_seen.json`.** A runner's "already reported"
  must not arrive on a laptop and silence the radar there. `.gitignore`
  un-ignores this directory alone.
- **The record step runs after the issue is opened.** Losing state costs one
  duplicate; losing the issue costs the week.
- **The caller needs `contents: write` too.** A called workflow can never hold
  more permission than its caller grants, so leaving the caller at `read` makes
  only the push 403 while every other step succeeds — the quietest way to lose
  the state.
- **`concurrency` is queued, not cancelled.** A cancelled radar run is a missed
  week.
