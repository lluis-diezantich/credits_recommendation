# D22: Co-appearance becomes the second pipeline, and more seeds is now the point

- **Status:** Accepted
- **Date:** 2026-10-20
- **Supersedes:** [D8](D8-one-pipeline-for-now.md) ("the Friday known-artist
  radar is the whole product for now")
- **Where it lives:** [`stages/discover.py`](../../stages/discover.py),
  [`stages/co_artists.py`](../../stages/co_artists.py), the plan in
  [../../todo.md](../../todo.md)

## Context

[D8](D8-one-pipeline-for-now.md) narrowed the project to one pipeline on two
measurements, and one of them has since turned out to be wrong.

It said *growing the credit graph is expensive, using it is nearly free*, and
therefore *the thing to avoid is more seeds*. That was measured on the full
chain — credits per album, then a resolve per person, then a discography per
person, ~160 requests a seed — and it is still true of the POOL path.

But the pool path is not where the signal is. Measured 2026-10-20
([D14](D14-co-appearance-is-its-own-output.md)), the artists a seed is *billed
with* hit 59% and 40% already-played against 13-16% for the crew graph the
pool is built from. And that list comes off the discovery walk alone: one
`album/get` per release, about 50 requests for a seed, once, with the credits
then cached forever.

So the cheap half of the pipeline outperforms the expensive half by 3-4x, and
the expensive half is the one that is still untrustworthy
([D15](D15-filters-before-ranking.md)).

## Options

1. **Hold D8**: one pipeline, no new seeds, wait for the pool to be fixed. The
   better signal stays stuck at two seeds, where its intersection is 2 of 67
   co-artists and no ranking has any range.
2. **Scale seeds on both paths**: ~210 requests a seed, and most of it buys
   rows from the path that does not work yet.
3. **Scale seeds on the co-appearance path only**, leave the pool at Drexler
   until its name matching is fixed, and rank across seeds.

## Decision

Option 3. Co-appearance is a pipeline in its own right, not a by-product of
discovery, and seeds are the thing to add rather than avoid — on that path.

The Friday radar remains the only thing that runs unattended. This is a second
pipeline, not a replacement, and the pool path stays paused on its own merits.

## Evidence

| | per seed | what it buys |
|---|---|---|
| discovery walk (co-appearance) | ~50 requests, once, then cached | the 59%/40% list |
| resolve + pool (crew graph) | ~160 requests | the 13-16% list, still filtered down to 38 rows |

Seed pool: `profile.json` names 80 `core` artists — PJ Harvey at 91 active
months, Björk 87, Tom Waits 77, Nine Inch Nails 76, The Mars Volta 68. Drexler
(68) and Pérez Cruz (50) are 6th and 11th, so the two seeds chosen by hand are
already from the top twelve and the list extends well past them.

Eight more seeds is ~400 requests, about four weeks of the Friday radar's own
traffic, paid once.

What is NOT yet known, and is the reason step 2 of the plan is a probe rather
than a commitment: whether this works outside one scene. Both current seeds sit
in the Iberian/Latin cluster, where guest culture is dense and Qobuz's credits
are good. Tom Waits and PJ Harvey are the test.

## Consequences

- `todo.md`'s ordering changes: more seeds moves from "avoid" to "do next",
  for one path only. The file says so, dated, rather than quietly reordering.
- Ranking becomes possible and is the next real decision. Its inputs are the
  evidence already stored — seeds shared, records each way, direction, roles,
  recency — plus a ubiquity penalty, because `selectivity()` exists for exactly
  the person who appears everywhere.
- A ranker here must keep its sentence. The project's advantage over a
  similar-artist list is that the reason is checkable
  ([D21](D21-explanations-name-what-the-person-did.md)), and a score with no
  sentence throws that away.
- Nothing scores what the list showed, so every weight in that ranking will be
  guesswork until an impression log exists. The radar solved this with a
  committed state file and this path has no equivalent.
- D8's other conclusions still hold: no orchestrator, no `pipelines/` layout,
  and the pool stays paused.
