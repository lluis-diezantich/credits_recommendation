# D19: Albums and tracks are per (person, seed), and `people` sums them

- **Status:** Accepted
- **Date:** 2026-10-20
- **Where it lives:** the `person_seeds` table, the discovery loop in
  `load_people`, and `people.albums` / `own_albums` / `tracks` / `seeds` in
  [`stages/load.py`](../../stages/load.py)

## Context

`load_people` merges five files into one row per person. For each
`discovery_*.json` it called `row.update()` with that file's `stats`, so with
two seeds on disk the **last file won**: Fred Kevorkian's 13 Drexler albums
were replaced by the 1 he has on a Sílvia Pérez Cruz record, silently. 14 of
the 551 people are in both files.

The cause is a grain mismatch, not a merge bug. "Albums" means *how many of the
seed's records this person worked on* — a fact about a (person, seed) pair —
and it was being stored in a table with one row per person. There was nowhere
for the second seed's number to go.

## Options

1. **Sum into `people` and leave it there:** one number per person, and "how
   embedded in this seed's catalogue" — which is what `embedded` and every
   score mean — becomes unanswerable.
2. **Keep the last file's numbers** (the behaviour): one seed's facts, labelled
   as if they were the person's.
3. **A `person_seeds` junction at the real grain**, with `people` holding a
   defined aggregate: both questions answerable, one more table.

## Decision

Option 3, which is how the rest of this schema already works — `person_roles`,
`person_albums` and `person_sources` are all junctions for the same reason.

- `person_seeds (person_key, seed_qobuz_id, …)` keeps `albums`, `own_albums`,
  `tracks`, `top_role` and the dates per seed.
- `people.albums`, `own_albums` and `tracks` are **summed** across seeds, and
  `people.seeds` says how many were summed. `first_seen` and `last_seen` span
  all of them, and `top_role` comes from the seed where the person did the most
  — what they mainly are, rather than whichever file sorted last.
- `watchlist.json` stays first-wins, not summed: it is *derived* from a
  discovery file, so adding its counts would double that seed.

## Evidence

Measured on the 2026-10-20 build: 14 of 551 people appear in both discovery
files, and before this they carried only the Pérez Cruz numbers, because
`discovery_656411.json` sorts after `discovery_41620.json`. Kevorkian now reads
14 albums across 2 seeds in `people`, and 13 / 1 in `person_seeds`.

The defect was invisible from the table itself — `sources` listed both files
all along, which is the only reason it could be spotted at all.

## Consequences

- `people.albums` has changed meaning for 14 rows. Anything quoted from that
  column before 2026-10-20 was one seed's number wearing a person's name.
- The scoring does not read this table — `signal_for` works from the discovery
  file directly — so no score changes. That is luck rather than design, and it
  is why `person_seeds` exists before anything starts ranking from the store.
- One more table, 16 keyed tables and 49 indexes.
- This does not touch the identity model, which has its own known limit: a
  person is `normalise(primary name)`, so two different Diego Drexlers would
  still collide. `people`'s own docstring says so.
