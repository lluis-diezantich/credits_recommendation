# D32: The known-artist radar reports the whole week, late on Friday, and records nothing

- **Status:** Accepted
- **Date:** 2026-10-23
- **Where it lives:** [`.github/workflows/releases-known-artists.yml`](../../.github/workflows/releases-known-artists.yml)
  (`cron`, `stateless: true`), the `stateless` input in
  [`.github/workflows/radar.yml`](../../.github/workflows/radar.yml),
  [`core/radar.py`](../../core/radar.py) (`--all`, and the state write at the
  end of `execute`)

## Context

Two things went wrong on 2026-10-23, the first Friday the cron was due, and
both are facts about when the radar looks rather than about how it reports.

GitHub's scheduler is best-effort. The 04:17 UTC slot did not fire at 04:17; it
fired at 09:20, 5h03m late, and nothing in the repo caused that.

More importantly, 04:17 is the wrong hour. Friday *is* global release day, and
Qobuz ingests through the morning, so an early-Friday run reports Thursday and
calls it a week. A manual run at 06:12 scanned 7272 ids; the scheduled run at
09:20 found 6 more, three of them dated that same Friday, plus one backdated to
the Thursday.

The two runs also showed what [D11](D11-radar-state-in-ci.md) costs when a week
has two runs in it. The 06:12 run banked all 7272 ids it *scanned* — not the 21
it reported, because `record_scanned` is true — so the 09:20 run subtracted
them and opened an issue with 4 rows. Two issues with the same title, one of
them the real one, and nothing to say which from the outside.

## Options

1. **Move the cron only, keep state.** Fixes the hour. Leaves a week's news
   split across whichever runs happen, and leaves the thin-issue trap.
2. **Move the cron and pass `stateless: true`.** One issue per week holding the
   whole window, repeats included. Costs the state file: `--all` does not just
   ignore it, it also declines to write it, so the impression log freezes.
3. **Decouple reporting from recording in `core/radar.py`.** Report everything
   and still record what was scanned, which keeps the log AND gives a full
   week. A behaviour change inside the shared radar loop, affecting three
   radars to serve one.

## Decision

Option 2, as a "for now". The weekly issue being complete is worth more today
than it being duplicate-free, and repeats were explicitly acceptable.

The cron moves to `17 20 * * 5` — 20:17 UTC, 21:17 CET or 22:17 CEST. Not
later: the runner's clock is UTC and both the issue title (`date -u +%F`) and
the date window (`dt.date.today()`) flip at midnight, so with a scheduler that
has already slipped five hours once, a 22:17 slot would land on Saturday's
date. 20:17 leaves the slack.

## Evidence

Measured, on the two 2026-10-23 runs of this radar:

| run | event | window | reported | ids recorded |
| --- | --- | --- | --- | --- |
| 06:11 (issue #24) | `workflow_dispatch` | last 7 days | 21 | 7272 |
| 09:20 (issue #25) | `schedule`, 5h03m late | last 10 days | 4 | 7278 |

The 6-id delta over three hours is what puts the cron at the end of Friday. The
21-versus-4 split is what puts `stateless: true` in the caller.

The two windows differing is a separate bug, fixed in the same change: the
caller read `days: ${{ inputs.days || '10' }}` while the `workflow_dispatch`
input defaulted to `"7"`, so every scheduled run had silently been a 10-day
window and only hand-triggered runs were 7.

## Consequences

- **`data/ci/qobuz_seen.json` is frozen** at 7278 ids. [D11](D11-radar-state-in-ci.md)'s
  mechanism is untouched and still used by any other caller; this radar simply
  stops feeding it. The git history of that file is no longer a dated log of
  what was reported, which is the impression data
  [../roadmap.md](../roadmap.md) wants before anything can be evaluated. That
  is the real price here, and it is why this is a "for now".
- **Turning state back on costs one duplicate issue**, covering everything
  released since the freeze. One-line change: drop `stateless: true`.
- **Last Friday appears in every issue.** The cutoff is inclusive
  (`release.date < cutoff`), so `days: 7` spans eight days. `days: 6` would
  give a clean Saturday-to-Friday week if the overlap ever stops being
  tolerable.
- **No weekly bot commit**, so `main` stops diverging every Friday and a plain
  `git pull` works again.
- **The late-run problem is not fixed**, only made cheaper: a run that slips
  stays inside Friday UTC instead of landing in a half-reported day. A
  scheduler that skips entirely still skips, and
  [../../todo.md](../../todo.md) keeps an orchestrator deferred until pipeline
  #3 exists.
- **What would reopen this:** wanting the impression log back, which is
  Option 3 rather than a revert.
