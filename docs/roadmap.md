# What this is, and is not, as a recommender

Candidate generation works. Four of the five stages a recommender needs do
not exist. This is the list, by stage, with what each would cost — API
requests, since that is the only scarce thing here.

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

The same list grouped by pipeline stage is below, which is where the ranker,
`core/model.py` and evaluation rows above come from.

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
| retrieval | freshness source | what came out this week, independent of taste | **yes, for known artists** — `radars/qobuz.py` weekly; the pools are not wired to it |
| retrieval | co-occurrence | things that keep appearing on the same playlists | — |
| retrieval | follow graph | artists explicitly followed, separate from play counts | — |
| filtering | seen filter | never suggest a release already in the listen history | — |
| filtering | quality / spam filtering | drop karaoke, tribute acts, covers mills | **partial** — `COVERS_MILL_HINTS` flags, nothing drops |
| ranking | ranker | one score per candidate, so they can be sorted | — |
| ranking | implicit-feedback confidence | a play is not a rating; how much does one play prove | — |
| ranking | temporal decay | 2013 taste should not weigh what last month weighs | — |
| post-processing | diversification / capping | not ten records by the same producer | — |
| post-processing | explanations | say why each row is here | **yes** — `via.signal` |
| feedback loop | impression logging | write down what was shown, and when | **partial** — the weekly issue is a dated record of what was shown; nothing records what was played |
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

Scorecard: 2 of 7 retrieval sources, 1 of 2 filters, 0 of 3 ranking mechanisms,
1 of 2 post-processors, 0.5 of 3 feedback mechanisms. The one retrieval source that
does exist is the rare one, so the gap is not that the thesis is thin — it is
that four stages downstream of it do not exist.

`docs/disco-bahia.md` works one recommendation through in full: what each source
knew, and which three rows above it lands on.
