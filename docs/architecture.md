# The architecture

The module map, and the one module everything else waits on.

`README.md` lists what is missing as a flat set of tasks, then regroups it by
recommender stage. This doc takes the second grouping seriously and asks where
the code for each stage should live — because four of those stages do not exist
yet, and the order they get built in is not free.

## What this doc is, and what it is not

It **is** a target layout and a build order, argued from the shapes the data
already has. Every number below was measured against `data/` on 2026-09-13.

It is **not** a refactor plan for what exists. `core/`, `stages/`, `radars/` and
`policy.py` are where they should be. The proposal is mostly about naming the
boxes that are currently empty, plus one rename (`radars/` -> `sources/`) that
can wait until there is a second kind of source worth grouping.

## Why by stage, not by source

A source-shaped tree (`qobuz/`, `discogs/`, `listenbrainz/`, `remezcla/`) puts
the same judgement in four places. The project already paid for that once: two
copies of the scoring policy diverged on nine role spellings, always upward,
always for the credits deserving least weight. `policy.py` exists because that
bug was cheaper to prevent structurally than to remember.

Stage-shaped, each judgement has one home, and a source is a plug-in that knows
nothing about the others.

## The map

| stage | module | have |
|---|---|---|
| cross-cutting | `policy.py` — contestable numbers | **yes** |
| cross-cutting | `core/` — http, names, credits, state, paths | **yes** |
| cross-cutting | `core/model.py` — one record shape | **no — everything waits here** |
| taste | watchlist — listens -> artists worth watching | **yes** — see below |
| taste | affinity — plays -> weight, with temporal decay | **yes** — see below |
| retrieval | `graph/` — the credits thesis (today's `stages/`) | **yes** |
| retrieval | `sources/fresh_releases.py` — what came out this week | **partial** — `radars/listenbrainz.py` watches one hardcoded MBID |
| retrieval | `sources/remezcla.py`, `songmess.py`, `kexp.py`, `nts.py` | **1 of 4** — `radars/remezcla.py` |
| cross-cutting | `resolve/` — names -> identifiers, in one place | no |
| filtering | `filters/seen.py` — never suggest what you already played | no |
| filtering | `filters/quality.py` — covers mills, tribute acts | **partial** — flags exist, nothing drops |
| ranking | `rank/` — one score per candidate | no |
| post-processing | `report/` — issue, markdown, rss, push | no |
| feedback | `eval/` — impression log, then time-split scoring | no |
| store | `store/load.py` — the queryable view | **yes** |

## The tree

    policy.py
    core/          http names credits qobuz discogs state paths listens model
    taste/         watchlist affinity      -- built, but NOT here; see below
    graph/         discover resolve_qobuz resolve_discogs writing
    sources/       fresh_releases itunes qobuz remezcla songmess kexp nts
    resolve/       names -> mbid, one hit rate, one place to improve
    filters/       seen quality
    rank/
    report/
    eval/
    store/         load
    data/ cache/ docs/ notebooks/

## Where taste/ actually landed, and why not in taste/

Both taste rows are done. Neither is in a `taste/` package, and that is a
deviation from this doc rather than an accident:

    policy.py            RECENT_WINDOW, M24_FLOOR, DEEP_FLOOR, band()
    core/listens.py      export + monthly snapshots -> months per artist
    stages/profile.py    --seed / --month / the table

The proposed split put the thresholds inside `taste/affinity.py`, which
contradicts the reason `policy.py` exists at all — see *Why policy.py is not in
core/* below. A band floor is a contestable number, so it belongs in the one
visible file, not in the module that consumes it. With the floors out, what
remained was one pure counter and one CLI, which are already what `core/` and
`stages/` mean here. A package for two files would have been the folder, not the
structure.

It also came out smaller than the two rows imply: `affinity` is not a weight
with temporal decay. A decay coefficient was tried and dropped — it produces a
number nobody can argue with, and policy.py's stance is bands over formulas. The
verdict is two counts and a lookup table. [profile.md](profile.md) has the
measurements.

So the open question is not "build `taste/`" but "does a third taste feature
appear". If it does, these three files move together; until then the rename is
the same bet as `radars/` -> `sources/`, which this doc already says can wait.

## core/model.py — the keystone

The README calls this "no normalised `Release`, so the pools never converge".
That undersells it. There are currently **four incompatible notions of the same
thing**, and every empty box above needs them to be one.

### The four shapes, as they are on disk

| file | rows | identity | grain | fields |
|---|---|---|---|---|
| `pool.json` | 1,470 | `album_id` (Qobuz store id) | album | `album_id title artists date tracks hires streamable label genre via` |
| `pool_discogs.json` | 6,390 | `album_id` (Qobuz store id) | album | identical 10 keys — feature parity, done 2026-09-02 |
| `remezcla_picks.json` | 3,779 | none at all | **track** | `date curator artist track issue` |
| `radars/listenbrainz.py` | — | `release_mbid` | album | **persists no rows** — only `seen.json` keys |
| `core/radar.Release` | — | each store's own id | album | `id date kind artist title source tracks hires streamable url` — a REPORTING record, shared by the three id-based radars since 2026-10. Not album identity: it normalises the shape, not the entity, so two editions are still two rows and no Qobuz id is reconciled with an MBID |

Three things follow immediately.

**There is no shared identifier.** Neither pool carries an `mbid` or an `isrc`
(checked: the fields do not exist). The radar keys on `release_mbid`. Remezcla
carries a name and a track title. So "is this the same record?" cannot be
answered between any two of them, which is why `filters/seen.py` cannot be
written: suppressing what you already played means matching a candidate against
190,196 listens that key on `recording_mbid`.

**The grain differs.** The pools are albums; the curator picks are tracks;
listens are recordings. A model that does not say which grain a row is will
silently compare an album to a song.

**The radar writes nothing down.** It prints, then records a dedup key. So
`eval/` has nothing to score even in principle — the impressions were never
stored in a comparable shape. This is why rule 6 below puts impression logging
in on the same day as `report/`.

### The provenance fields have already drifted

Both pools carry `via`, and both carry `via.signal.score`. Underneath:

| | `pool.json` | `pool_discogs.json` |
|---|---|---|
| `via` | `qobuz_id name classes top_role seed_albums signal` | `qobuz_id name path through through_roles signal` |
| `via.signal` | `role_weight seed_albums embedded score flags` | `role_weight selectivity selectivity_band person_seed_albums embedded score flags` |
| `score` | `weight * embedded` (`resolve_qobuz.py:73`) | `weight * selectivity * embedded` (`resolve_discogs.py:465`) |
| observed range | 0.05 .. **0.80**, median 0.16 | 0.05 .. **1.00**, median 0.18 |

Note `seed_albums` and `person_seed_albums`: the same quantity under two names,
which is the first move in the drift that produced the `policy.py` bug.

The scores are worse. `resolve_qobuz.py:53` calls its output "a comparable
score" — true within a pool, false across two. Measured: concatenate both pools
and sort by `via.signal.score`, and **the top 200 rows are 200 from
`pool_discogs.json` and 0 from `pool.json`**, though the Qobuz pool is 19% of
the corpus. Different formulas, different ceilings, so the merged ordering is an
artifact of which resolver found the row.

A ranker built before this is fixed would inherit that artifact and look like it
was working.

### What the model has to decide

Not a dataclass wishlist — four questions, each of which is currently answered
differently in different files:

1. **Identity.** Which key is authoritative, and what happens to a row that has
   none. Remezcla rows will never have one; they still need to be rankable.
2. **Grain.** `album` or `track` or `recording`, named on the row. Song identity
   is the cheaper one to get right first: listens carry `recording_mbid`, and
   Qobuz returns an `isrc` the cache currently drops.
3. **Provenance.** One shape for "why is this here", so `report/` can write a
   sentence and `rank/` can read a number. `via.signal` is close; it needs the
   two names merged and the score made comparable or explicitly not-comparable.
4. **Confidence.** Whether a field was resolved, guessed, or absent. The
   project already has the failure mode: a missing key in one policy copy fell
   back silently to `INSTRUMENT_WEIGHT`, and `radars/remezcla.py` sets 996 items
   aside rather than guess a name from a video embed title. Make that explicit
   in the type instead of per-caller.

### What unblocks when it exists

`filters/seen.py` becomes possible at all. `rank/` gets one axis instead of two
incomparable ones. `resolve/` has somewhere to put an MBID once it finds one.
`eval/` can log an impression and recognise the same record later. `sources/`
becomes pluggable, because a new source is then a function returning a known
type rather than a new JSON dialect.

## Cadence, and why it decides the hosting

Two speeds, and the split is not cosmetic:

| | runs | may depend on |
|---|---|---|
| **slow** — the taste files, `graph/`, `store/` | occasionally, locally, by hand | anything: pandas, parquet, DuckDB |
| **fast** — `sources/` -> `filters/` -> `report/` | weekly, unattended | **stdlib only** |

The fast path must stay dependency-free because that is what makes free hosting
trivial: a GitHub Actions job with no install step, ~30s a week, about 2 minutes
a month against a 2,000-minute allowance. The zero-dependency property in the
README is load-bearing infrastructure, not aesthetics — and the boundary is the
file the slow path writes and the fast path reads.

## The two-repo boundary

`listenbrainz_top` stays its own poetry project with pandas and parquet. It
writes a plain JSON watchlist. `credits_recommendation` reads that JSON and
never learns what parquet is.

They exchange **files, not imports**. Importing across would drag pandas into
the weekly job and cost the property above. `MIN_PLAYS = 50` lives on that side
and must not travel: it belongs to ranking, it conflates play count with
usefulness-as-a-graph-edge, and 6,922 of 7,533 artists (91.9%) sit below it.
`core/listens.py` carries `plays` as a field and `policy.band()` filters on
months, never on plays — which is the same lesson, honoured rather than quoted.

## Build order

1. `core/model.py` — everything above is blocked on it, and every day it does
   not exist, a new JSON dialect gets written
2. ~~the taste files — turn the radar from a rank-ordered list into a measured
   one~~ Half done. The measurement exists (`core/listens.py`,
   `stages/profile.py`, [profile.md](profile.md)); nothing yet writes a verdict
   back into `data/favourites.json`, so the radar still watches whatever
   ListenBrainz ranked. That wiring is the remaining half, and it is where the
   duplicate-`qobuz_id` grain in todo.md has to be settled
3. `filters/seen.py` — cheap, and it is what makes the output trustworthy
   enough to read weekly
4. `report/` **and** impression logging, together, per rule 6
5. `rank/` last. It is the most interesting and the least useful while four
   stages upstream of it are missing

## Numbers here that disagree with the README

The README says "7,860 releases across the two pools". Still true: 1,470 +
6,390. It also says the pools "never converge" — as of the 2026-09-02 feature
parity run their top-level keys are identical, so the divergence has moved down
into `via` and `via.signal`, where it is harder to see and more expensive to
merge.

## Why policy.py is not in core/

`core/` is plumbing: if it changes, behaviour should not. `policy.py` is the
opposite — nothing but contestable numbers (a producer credit is worth 1.0, a
mastering credit 0.15) — so it belongs somewhere you trip over it.

Merging the two copies that used to live in the resolve stages surfaced a real
bug. They never disagreed on a shared key, but each lacked keys the other had,
and a missing key falls back silently to `INSTRUMENT_WEIGHT` (0.8). Nine
spellings diverged that way, always upward, always for the credits deserving
least weight: `mastered by` scored 0.15 in one file and 0.8 in the other.

## One open decision

**The role-class vocabularies still differ, deliberately.** `discover.py` folds
every engineering role into `production`; `resolve_discogs.py` splits
`engineering` out. That is why `discovery_41620.json` carries no `engineering`
class while `--list-roles` reports 16 engineers. Both live in `policy.py`
(`DISCOVERY_ROLE_CLASSES` vs `ROLE_CLASS`), unchanged because unifying them
rewrites `classes` in existing data. Worth deciding on purpose.
