# credits_recommendation

Credits-based music discovery. Start from one artist, read who actually made
their records — producers, engineers, players — then find what else those people
made. The premise is that a collaborator graph carries signal a genre model
cannot: sharing a producer means something, sharing a mastering house does not.

## What runs on a schedule

| | | |
|---|---|---|
| new releases from artists you already know | `radars/qobuz.py` over `data/favourites.json` | Fridays, as a GitHub issue |
| the test suite | `pytest` | every push and pull request |

Everything else is a script you run by hand.

## Install

    python3 -m venv .venv && ./.venv/bin/pip install -e ".[dev]"

`requests` for connection pooling and retries, since a radar run makes ~90
sequential calls to one host; `beautifulsoup4` for the one radar that reads
HTML. `pytest` and `ruff` are dev-only.

## Running it

    ./stages/favourites.py --user <lb-user>    # your top artists -> Qobuz ids
    ./stages/favourites.py --review            # fix what did not resolve cleanly
    ./radars/qobuz.py --days 10                # what came out
    ./stages/load.py                           # everything on disk -> data/music.db
    pytest -q                                  # 65 cases, offline

`python -m stages.favourites` works too. Each stage reads and writes JSON in
`data/`, so any stage can be rerun alone, and `resolve_discogs.py --pool-only`
resumes a run that died partway through its fan-out.

## Layout

    policy.py          scoring judgement calls - ONE copy, at the root, on purpose
    core/              plumbing - http, names, credits, qobuz, discogs, favourites,
                       state, paths
    stages/            the pipeline, in order
      favourites.py      ListenBrainz top artists -> Qobuz ids -> favourites.json
      discover.py        seed artist -> credits -> people          [EXACT]
      resolve_qobuz.py   people -> Qobuz artist ids -> pool.json   [LOSSY]
      resolve_discogs.py the ones Qobuz cannot see -> pool_discogs  [LOSSY]
      writing.py         one person -> what they WROTE, anywhere   [CACHED]
      load.py            all of the above -> data/music.db         [DERIVED]
    radars/            new-release watchers, independent, own state each
      qobuz.py  listenbrainz.py  itunes.py  remezcla.py
      report.py          a radar's JSON -> markdown, for the weekly issue
    tests/             pytest, offline - every network call stubbed at the seam
    data/              generated JSON, gitignored except favourites.json
    cache/             API responses - the source of truth, never regenerated
    .github/workflows/ the weekly issue, and the tests
    contrib/           qobuz_keys.py - vendored gist, not ours

`data/music.db` is derived and disposable: `./stages/load.py` rebuilds 216k rows
in 2s and fetches nothing. Deleting it costs one rerun; deleting `cache/` costs
the corpus.

## Docs

| | |
|---|---|
| [favourites.md](docs/favourites.md) | the watchlist and the release radar, and why their cadences differ |
| [architecture.md](docs/architecture.md) | the module map, and the one module the rest waits on |
| [roadmap.md](docs/roadmap.md) | what this is and is not as a recommender, stage by stage |
| [store.md](docs/store.md) | `data/music.db` — table map, query cookbook, gotchas |
| [duckdb.md](docs/duckdb.md) | optional query layer over the store — measured, not quoted |
| [sources.md](docs/sources.md) | other discovery signals, and what each was tested to carry |
| [disco-bahia.md](docs/disco-bahia.md) | one recommendation this project could not have made |

## TODO

- **A radar for people, not artists.** The thesis, and the one thing this cannot
  do: alert on records made by *people* you follow. The pools hold 7,860
  candidate releases and nothing consumes them. One `album/get` per fresh
  release, cached.
- **`core/model.py`.** No normalised `Release`, so album identity is unresolved
  and two editions of one record are two rows. See
  [architecture.md](docs/architecture.md).
- **A ranker.** 7,860 candidates, each with an explainable `via.signal.score`,
  and no order.
- **Resolve Apple ids, or delete `radars/itunes.py`.** Every `itunes_id` in
  `favourites.json` is null, so that radar silently falls back to its built-in
  list of one artist.
- **Record what you played.** The weekly issue is already a dated log of what
  was *shown*; the other half is missing, and without it the evaluation in
  [roadmap.md](docs/roadmap.md) has nothing to score.
- **Decide the storefront.** `gb-en` is the default and the watchlist leans
  Latin and Iberian; `--store es-es` is a different catalogue, not a different
  view of one.
- **Cross-check coverage.** `./radars/listenbrainz.py --days 20 --dry-run` reads
  a second source for the same 89 artists; anything it names that Qobuz missed
  is a gap nothing else would reveal.
- **`--review` cannot re-ask about a row that resolved `exact`.** A wrong id
  that looked confident can only be fixed by editing the JSON.
- **Unify the role-class vocabularies.** `discover.py` folds engineering into
  `production`, `resolve_discogs.py` splits it out. Both live in `policy.py`;
  unifying them rewrites `classes` in existing data.
