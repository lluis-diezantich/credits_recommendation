# D20: Everything the funnel is made of reaches the store, keyed by seed

- **Status:** Accepted
- **Date:** 2026-10-20
- **Where it lives:** the `seeds`, `co_artists` and `co_artist_albums` tables,
  `releases.seed_qobuz_id` and `person_albums.provenance` in
  [`stages/load.py`](../../stages/load.py); the funnel queries in
  [../store.md](../store.md)

## Context

Asking "what did this pipeline actually do for Drexler, and what survived each
filter" needed a Python script: the bottom half came from `releases`, and the
top half — 63 albums walked, 48 his own, 15 guest spots, 278 people, 37
co-artists — existed only inside `discovery_*.json`.

Worse, two things were silently missing from the store altogether:

- **`co_artists`**, the output with the best measured hit rate in the project
  (59% artists already played against the crew graph's 13%,
  [D14](D14-co-appearance-is-its-own-output.md)), had no table at all.
- **`releases` carried no seed.** Both pool files record which seed they came
  from and it was dropped, so two seeds' pools in one table were
  indistinguishable in SQL — the same defect
  [D19](D19-person-seed-is-the-grain.md) had just fixed for `people`, in the
  table that actually feeds the recommendations.

## Options

1. **Keep reading the JSON** for the top half: no schema change, and every
   question about discovery needs a script rather than a query.
2. **Store the funnel counts** as a table of steps: one query answers it, and
   the numbers go stale the moment a filter changes, which is how a doc came to
   claim 190,196 listens over a 2,000-row store.
3. **Store the facts the funnel is computed from**, and let the query do the
   counting.

## Decision

Option 3. Three tables and two columns, all per-seed:

| | grain |
|---|---|
| `seeds` | one row per seed walked |
| `co_artists` | (seed, person) |
| `co_artist_albums` | (seed, person, album) |
| `releases.seed_qobuz_id` | which graph a candidate came from |
| `person_albums.provenance` | own or guest, per album |

`co_artists.person_key` is `normalise(name)`, the key `people` and
`listens.artist_key` already use, so the 59% list can be joined to the credit
graph and to real listening rather than living in a separate namespace.

## Evidence

The data was already on disk — no requests. The build gained `seeds` (2 rows),
`co_artists` (67) and `co_artist_albums` (85), and `person_albums` now splits
939 own against 82 guest.

The funnel, now one query per half, Drexler 2026-10-20: 1,255 pool rows -> 383
not the referrer's own record -> 271 player-or-producer referrals -> 215
unheard -> 208 since 2015 and streamable -> 38 capped. The side-credit cut
removes 872, which is two thirds of the pool in one condition.

## Consequences

- Both seeds' discovery files load, but only Drexler has been resolved into a
  pool, so `releases.seed_qobuz_id` is 41620 everywhere today. It stops being a
  constant the first time `resolve_qobuz` runs on another seed, which is
  exactly when it would have been needed and missing.
- `co_artists` is stored but still unused by anything that recommends. It is
  now one join away, which is the point.
- 25 tables, 19 keyed, 53 indexes. `seeds` keys on `INTEGER PRIMARY KEY`, which
  aliases the rowid and creates no index — a test says so, since the counts are
  asserted.
- Row counts in [../store.md](../store.md) drift as pools are regenerated.
  `meta` is the authoritative copy, which is why that doc now says so.
