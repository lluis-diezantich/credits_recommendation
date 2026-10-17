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

## Install

    python3 -m venv .venv && ./.venv/bin/pip install -e ".[dev]"
    ./.venv/bin/pre-commit install          # ruff before the commit, not after

CI installs from `requirements.lock` (runtime) and `requirements-dev.lock`
(plus the tooling) with `--require-hashes`, so a release somebody else ships
cannot turn the Friday radar red. Both are generated — regenerate with the
`uv pip compile` line in their headers after changing `pyproject.toml`.


## Running it

    ./stages/favourites.py --user <lb-user>    # your top artists -> Qobuz ids
    ./stages/favourites.py --review            # fix what did not resolve cleanly
    ./radars/qobuz.py --days 10                # what came out
    ./stages/load.py                           # everything on disk -> data/music.db
    pytest -q                                  # 187 cases, offline

`python -m stages.favourites` works too. Each stage reads and writes JSON in
`data/`, so any stage can be rerun alone, and `resolve_discogs.py --pool-only`
resumes a run that died partway through its fan-out.

## Layout

    policy.py          scoring judgement calls - ONE copy, at the root, on purpose
    core/              plumbing - http, names, credits, qobuz, discogs, favourites,
                       state, paths, radar (the shared radar run)
    stages/            the pipeline, in order
      favourites.py      ListenBrainz top artists -> Qobuz ids -> favourites.json
      discover.py        seed artist -> credits -> people          [EXACT]
      resolve_qobuz.py   people -> Qobuz artist ids -> pool.json   [LOSSY]
      resolve_discogs.py the ones Qobuz cannot see -> pool_discogs  [LOSSY]
      writing.py         one person -> what they WROTE, anywhere   [CACHED]
      load.py            all of the above -> data/music.db         [DERIVED]
    radars/            new-release watchers, one thin source each - docs/radars.md
      qobuz.py  listenbrainz.py  itunes.py    core/radar.py drives these three
      remezcla.py        a blog, not an id namespace - its own script
      report.py          a radar's JSON -> markdown, for the weekly issue
    tests/             pytest, offline - every network call stubbed at the seam
                       policy.py and core/credits.py are at 100%; six files are
                       at zero - `pytest --cov` names them
    data/              generated JSON, gitignored except favourites.json
    cache/             API responses - the source of truth, never regenerated
    .github/workflows/ radar.yml runs any radar; one caller per schedule
                       tests.yml: ruff, ty, pytest --cov on 3.11/3.12/3.13
    requirements*.lock hashed pins for CI - generated, see their headers
    contrib/           qobuz_keys.py - vendored gist, not ours

`data/music.db` is derived and disposable: `./stages/load.py` rebuilds 216k rows
in 2s and fetches nothing. Deleting it costs one rerun; deleting `cache/` costs
the corpus.

## Docs

| | |
|---|---|
| [favourites.md](docs/favourites.md) | the watchlist and the release radar, and why their cadences differ |
| [radars.md](docs/radars.md) | what a radar is, and how to write another one |
| [architecture.md](docs/architecture.md) | the module map, and the one module the rest waits on |
| [roadmap.md](docs/roadmap.md) | what this is and is not as a recommender, stage by stage |
| [store.md](docs/store.md) | `data/music.db` — table map, query cookbook, gotchas |
| [duckdb.md](docs/duckdb.md) | optional query layer over the store — measured, not quoted |
| [sources.md](docs/sources.md) | other discovery signals, and what each was tested to carry |
| [disco-bahia.md](docs/disco-bahia.md) | one recommendation this project could not have made |

## TODO

Moved to [todo.md](todo.md): the product gaps, what is untested, the
build-hygiene list, and what is deliberately deferred.
