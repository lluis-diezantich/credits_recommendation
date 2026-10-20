# D8: The Friday known-artist radar is the whole product for now

- **Status:** Superseded by [D22](D22-co-appearance-is-the-second-pipeline.md)
  for the seed question. Its other conclusions (no orchestrator, no
  `pipelines/` layout, the pool stays paused) still hold.
- **Date:** 2026-10-17 (superseded 2026-10-20)
- **Where it lives:** [`radars/qobuz.py`](../../radars/qobuz.py),
  `.github/workflows/`, and the framing at the top of
  [../../todo.md](../../todo.md)

## Context

Two pipelines exist in outline: new releases from artists already known, and the
credits chain (discover → resolve → pool). The second is the project's actual
thesis and is the one that does not work yet.

## Options

1. **Build both**, since the credits chain is the interesting half.
2. **Ship the known-artist radar, and let it run for a while**, adding features
   to the one graph afterwards, one at a time and small.

## Decision

Option 2 — a deliberate narrowing, which is why `todo.md` is a backlog and not a
plan. The ordering rests on two measurements, both of which point at using what
is already on disk rather than fetching more.

## Evidence

Growing the graph costs requests; querying it does not. One `discover` run on
one seed produced 278 people and 7,860 candidate releases, and the fan-out —
credits per album, a resolve per person, a discography per person — is the part
that multiplies. A radar over the people already resolved would be 68
`artist/get` per run, *smaller* than the 91 the Friday job already makes.

Revised 2026-10-18: a seed costs less than that figure implied once the Discogs
path is dropped. Sílvia Pérez Cruz cost 45 requests and added 149 people.

The blocker is not cost. Nearly half the pool is name collisions and the score
ranks them first ([D13](D13-match-plausibility-on-read.md)), so nothing
credits-based is worth building on top of it yet.

## Consequences

- An orchestrator (Dagster, Prefect, Airflow) is deferred until pipeline #3
  exists; two scripts and a `Makefile` do not need a scheduler with a UI.
- A `pipelines/<name>/` layout is deferred until `stages/` becomes a junk
  drawer, which with the credits chain paused it will not soon.
- What the radar shows is logged by the committed state file ([D11](D11-radar-state-in-ci.md)),
  so the impression data for an evaluation accumulates while this holds.
- Reopen when the pool is trustworthy: the people radar and the ranker both
  become cheap the moment it is.
