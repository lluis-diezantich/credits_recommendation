# credits_recommendation

Credits-based music discovery. Start from one artist, read who actually made
their records — producers, engineers, players — then find what else those people
made. The premise is that a collaborator graph carries signal a genre model
cannot: sharing a producer means something, sharing a mastering house does not.

Restructured from `lluisgists/fresh-releases`, which stays where it is. Behaviour
is unchanged: the pure functions were diffed against the originals across the
whole corpus (94 role strings, 278 people) and `--explain-gate` / `--list-roles`
produce byte-identical output.

## Layout

    policy.py          scoring judgement calls - ONE copy, at the root, on purpose
    core/              plumbing that had already drifted between scripts
      http.py            one GET, one timeout (was 30 in one file, 40 in two)
      names.py           one normalise() (was in three files under two spellings)
      credits.py         one performers-string parser (was in two, and they had drifted)
      qobuz.py           storefront cookies, app id, endpoints (was in four)
      discogs.py         throttle, artist lookup, credit paging
      state.py           the *_seen.json contract each radar re-invented
      favourites.py      the artists YOU play, one id per source, one list
      paths.py           ROOT / DATA / CACHE
    stages/            the pipeline, in order
      favourites.py      your LB top artists -> Qobuz ids -> favourites.json
      discover.py        seed artist -> credits -> people          [EXACT]
      resolve_qobuz.py   people -> Qobuz artist ids -> pool.json   [LOSSY]
      resolve_discogs.py the ones Qobuz cannot see -> pool_discogs  [LOSSY]
      writing.py         one person -> what they WROTE, anywhere   [CACHED]
      load.py            all of the above -> data/music.db         [DERIVED]
    radars/            new-release watchers, independent, own state each
      listenbrainz.py  itunes.py  qobuz.py  remezcla.py
    data/              generated JSON - gitignored
    cache/credits/     Qobuz credit responses, keyed store_albumid
    cache/search/      Qobuz track/search pages, keyed store_query_offset
    notebooks/         showcase.ipynb
    docs/favourites.md your own top artists -> the release radar, and its cadence
    docs/store.md      the store: table map, query cookbook, gotchas
    docs/duckdb.md     optional query layer over the store - measured, not quoted
    docs/disco-bahia.md one recommendation this project could not have made
    docs/sources.md    additional sources of discovery signals - a running list
    docs/architecture.md the module map, and the one module the rest waits on
    tests/             ./tests/run.py - stdlib asserts, no pytest, no network
    contrib/           qobuz_keys.py - vendored gist, not ours

## Running it

No install, no venv, no dependencies. Every script is standard library and runs
directly:

    ./stages/discover.py --help
    ./stages/resolve_discogs.py --explain-gate     # free, spends no API calls
    ./radars/qobuz.py

`python -m stages.resolve_discogs` works too. Each stage reads and writes JSON in
`data/`, so any stage can be rerun alone and `--pool-only` can resume a run that
died halfway through the Qobuz fan-out.

    ./tests/run.py                  # 7 files, ~40 cases, a few seconds

No pytest, for the same reason there are no runtime dependencies. Every test is
a plain script that stubs the network and writes only to a temp directory, so
the suite cannot reach Qobuz or damage `data/` — verified by hashing `data/`
before and after. `./tests/run.py dedup` runs a subset.

## The store

    ./stages/load.py        # 216k rows into data/music.db in 2s, fetches nothing

Because most of what is listed below is a JOIN, not a model — "people in 3+
discovery graphs", "did the graph built on listens to 2024 contain the artists
adopted in 2025" — and each is one SQL statement here against a page of Python.

Stdlib `sqlite3`, so still no dependencies. The DB is derived and disposable:
rebuilt every run, gitignored, never migrated, because `cache/` is the source of
truth. It adds no fields — there is no language column anywhere in this project,
since no source it reads has one.

It also reads `../listenbrainz_*.zip` if it finds one — 190,196 listens, the only
user-preference data the project has, and the reason a ranker is possible at all.
The export stays outside the repo.

`docs/store.md` for the tables and a query per recommendation below.
`docs/duckdb.md` for the optional query layer: build with sqlite (2s), attach
from DuckDB (0.03s aggregates over 190k listens). Do not build with DuckDB — it
takes 69s for the same rows.

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

## What can be recommended with what is already here

None of this is built. It is what the current data and functions actually
support. Cost is API requests, since that is the only scarce thing here — a query
over what is already on disk is free.

**Works exactly, today.**

| | | cost |
|---|---|---|
| other recordings of a song | `writing_*.json` already lists every performer per song, so "the other 19 versions of Al Otro Lado Del Río" is a lookup | free |

**Straightforward, low risk.**

| | | cost |
|---|---|---|
| a radar for PEOPLE, not artists | the repo's actual thesis and the one thing it cannot do: alert on records made by *people* you follow, not artists | 1 `album/get` per fresh release, cached |
| filters instead of ranking | `covers_mill`, selectivity band and `album_wide_credit` already name most of the noise; dropping rows needs no taste model | free |
| explanations | `via.signal` already holds enough for a sentence: "engineered 21 of the seed's albums and only 45 records in total" | free |

**Plausible, unproven — hypotheses about taste, not known signals.**

| | | cost |
|---|---|---|
| shared songbook | artists who record the same writers are linked; co-citation on repertoire rather than personnel | ~10 requests × 29 people |
| production posture | the SHAPE of the credits — one producer across ten albums vs a new one each record — is an axis no genre model has | free |
| bridges | the 123 `worked_with` edges name the people joining disjoint scenes: highest information, highest risk | free |
| more seeds | one seed reaches half the taste in the export (Drexler 6,447 plays, Tom Waits 3,677, Radiohead 2,573); keep people in 3+ graphs | a full `discover` run per seed |

Caveats worth keeping: the people radar lags, because credits are often
registered days after release. Explanations are only as true as Qobuz's credits,
which mislabel mastering engineers as composers. Shared songbook only works where
songwriting credits are well recorded, which is patchy. More seeds broadens
coverage without improving picks within a scene.

## What is missing to make it a recommender

Candidate generation works: 7,860 releases across the two pools, each with an
explainable `via.signal.score`. What does not exist:

| | | cost |
|---|---|---|
| a ranker | nothing turns candidates + taste into an ordered list | design, not requests |
| `core/model.py` | no normalised `Release`, so the pools never converge and album identity is unresolved. Song identity is cheaper — listens carry `recording_mbid`, and Qobuz returns an `isrc` the cache drops | design |
| language | no source here has it. Qobuz's raw response carries no language field; MusicBrainz *works* do | re-cache for `isrc` (10 requests), then ~910 MB lookups at 1/s |
| evaluation | no way to tell whether a recommendation was good, and the obvious method is a trap | free, but needs discipline |

The same list grouped by pipeline stage is at the end of this file, which is
where the ranker, `core/model.py` and evaluation rows above come from.

~~**feature parity**~~ — DONE 2026-09-02. `resolve_discogs.py:486` copies `label`
and `genre`, and the re-run happened: both pools carry both fields on all rows.
The reasoning still applies to the next field that goes missing, because the
featureless rows were exactly the ones reached only through people with no Qobuz
page — a filter on a partly-populated field silently discards the hardest-won
candidates.

**Why evaluation is a trap.** Scoring candidates against the listen export
measures whether the system would have named what was ALREADY found, which is
anti-correlated with the point — a perfect score means it surfaced nothing new.
That is exposure bias: an unplayed release is an unknown, not a rejection. The
usable version splits on time instead: build the graph on listens up to one year
end, ask whether it contains the artists adopted independently the next year.
Those were genuinely unknown at prediction time, so a hit is novelty rather than
memorisation. Treat it as a lower bound, never a score. Do not split on 2021 — it
holds 26 listens against 13,715 in 2022, so it is a missing year, not a thin one.
The only honest measure is prospective: keep each week's list, mark it later,
accept the small sample. `docs/store.md` has the query and the definition
ambiguity it depends on.

## The missing mechanisms, by stage

The section above lists what is missing as a flat set of tasks. Grouped by the
stage a conventional recommender puts them in, the shape is clearer: this project
is one retrieval source and very little else. Retrieval is the stage where
running several mechanisms at once matters, because each fails differently — a
popularity prior misses obscure records, collaborative filtering misses new ones,
and content-based retrieval misses anything whose attributes nobody wrote down.

| stage | | | have |
|---|---|---|---|
| retrieval | content-based retrieval | records resembling what you like by their attributes; here, by who made them | **yes** — the whole project |
| retrieval | popularity prior | how famous a thing is, in absolute terms | — |
| retrieval | collaborative filtering | people who like what you like also like this | — |
| retrieval | item-item similarity | for one band, which bands sit next to it | — |
| retrieval | freshness source | what came out this week, independent of taste | — `radars/` collect it, nothing consumes it |
| retrieval | co-occurrence | things that keep appearing on the same playlists | — |
| retrieval | follow graph | artists explicitly followed, separate from play counts | — |
| filtering | seen filter | never suggest a release already in the listen history | — |
| filtering | quality / spam filtering | drop karaoke, tribute acts, covers mills | **partial** — `COVERS_MILL_HINTS` flags, nothing drops |
| ranking | ranker | one score per candidate, so they can be sorted | — |
| ranking | implicit-feedback confidence | a play is not a rating; how much does one play prove | — |
| ranking | temporal decay | 2013 taste should not weigh what last month weighs | — |
| post-processing | diversification / capping | not ten records by the same producer | — |
| post-processing | explanations | say why each row is here | **yes** — `via.signal` |
| feedback loop | impression logging | write down what was shown, and when | — |
| feedback loop | explicit negative feedback | somewhere to record "no, not this" | — |
| feedback loop | evaluation | check guesses against what was adopted later | — designed above, nothing writes the data |
| cross-cutting | entity resolution | one identity per artist and release across MusicBrainz, Deezer, Spotify, Qobuz | — this is `core/model.py` |
| cross-cutting | item cold-start | how to surface a record the databases barely know about | — |

### The stages

- **retrieval** — come up with a longlist of things worth considering at all.
- **filtering** — drop the candidates that are valid but useless.
- **ranking** — put the longlist in order, best first.
- **post-processing** — fix problems with the list as a whole, not row by row.
- **feedback loop** — write down what was suggested, so it can be checked later.
- **cross-cutting** — plumbing every stage leans on, mostly knowing when two
  records are the same record.

`MIN_PLAYS = 50` in `listenbrainz_top/notebooks/top.ipynb` belongs to ranking and
is a confidence-weighting bug rather than a threshold: it treats play count and
usefulness-as-a-graph-edge as one number. Prune the first, never the second.
6,922 of 7,533 artists in the export (91.9%) sit below it.

Scorecard: 1 of 7 retrieval sources, 1 of 2 filters, 0 of 3 ranking mechanisms,
1 of 2 post-processors, 0 of 3 feedback mechanisms. The one retrieval source that
does exist is the rare one, so the gap is not that the thesis is thin — it is
that four stages downstream of it do not exist.

`docs/disco-bahia.md` works one recommendation through in full: what each source
knew, and which three rows above it lands on.
