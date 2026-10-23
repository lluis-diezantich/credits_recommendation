# D33: The Qobuz radar drops releases dated after the run, and does not record them

- **Status:** Accepted
- **Date:** 2026-10-23
- **Where it lives:** [`core/radar.py`](../../core/radar.py) (`verdict`'s
  `horizon`, `Radar.keep_upcoming`, and the record ordering in `execute`),
  [`radars/qobuz.py`](../../radars/qobuz.py) (`keep_upcoming = False`)

## Context

The Qobuz radar answers one question — what came out that I have not been told
about — and Qobuz's catalogue includes pre-orders, which carry a release date in
the future. Until now they were reported and badged `*(upcoming)*`.

In issue #24, 3 of 21 rows were dated after the run: Newen Afrobeat (2026-10-30),
Ana Lua Caiano (2026-11-06) and Björk (2026-11-27). Two of the three were also
flagged `not streamable`, which is the same fact arriving twice: there is
nothing there to play yet.

The complication is `record_scanned`, which is true for this radar. It banks
every id a run *scans*, not just the ones it reports, so that a release cannot
resurface as new the week it falls out of the date window. Applied to a
pre-order it does the opposite of what it is for.

## Options

1. **Keep badging them.** A dated row you cannot hear, in a list whose whole
   claim is that it is what you can play now. Worse once state returns: the
   pre-order is banked on the day it is announced, so it is reported early,
   once, and never in the week it actually comes out.
2. **Drop them in `radars/report.py`.** The issue gets what we want and the run
   still records the id, so with state on the album is reported in no issue at
   all. The quietest of the three failures.
3. **Drop them in `verdict`, and do not record them.** The filter sits where
   the other three filters already are, and the id stays unbanked so the
   release returns on its own in the week it is released.

## Decision

Option 3, on this radar only. `verdict` takes a `horizon` — the run's date,
passed in rather than read from a clock, so the function stays pure and
testable — and returns `upcoming` above it. `Radar.keep_upcoming` defaults to
True, so `radars/itunes.py` and `radars/listenbrainz.py` are unchanged;
`QobuzRadar` sets it False.

The recording clause is the load-bearing half. `execute` now takes the verdict
*before* deciding whether to record, and skips `upcoming`.

## Evidence

A count, not a threshold: 3 of 21 rows in issue #24 (2026-10-23) were dated
after the run, the furthest five weeks out. Two carried `not streamable`.

No measurement says whether a pre-order is useful to see early — this is a
judgement about what the list is for, and it is reversible in one attribute.

## Consequences

- **Every row in a Qobuz issue is playable now.** That is the claim the
  report's headline already made and did not quite keep.
- **A pre-order reappears by itself** in the week it is released, because it
  was never recorded. This is only true while the non-recording clause holds;
  anyone removing it reintroduces option 1's silent loss.
- **It is counted, not hidden.** `run.upcoming` goes into `runs.jsonl` and not
  into the issue, so a filtered category stays countable without adding noise
  to what you can play. The same stance `shared` takes, in the other
  direction.
- **The other radars keep pre-orders**, and for `listenbrainz` that matters:
  its source IS a fresh-releases window rather than a catalogue, so an
  announcement is the only form some releases arrive in.
- **The `upcoming` key stays** in the JSON report shape and
  `radars/report.py` still renders the badge, for those sources.
- **Interacts with [D32](D32-the-known-artist-radar-reports-the-whole-week.md).**
  Nothing is recorded at all today, so the dangerous half is dormant; it is
  written now so that turning state back on does not need this argument
  rediscovered.
- **What would reopen it:** wanting a "coming soon" list. That is a second
  report with its own cadence, not a badge in this one.
