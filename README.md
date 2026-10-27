# music_recommendation

New releases from the artists you already listen to, as a GitHub issue every
Friday. One watchlist, four sources, no ranking.

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

    ./radars/qobuz.py --days 90            # what came out, from Qobuz
    ./radars/qobuz.py --find "Name"        # the Qobuz id for a name
    ./radars/itunes.py --days 30           # the same question, Apple's catalogue
    ./radars/listenbrainz.py --days 30     # and MusicBrainz's
    ./radars/remezcla.py                   # a blog, not an id namespace
    pytest -q                              # the suite, offline

`python -m radars.qobuz` works as well as `./radars/qobuz.py`. Each radar
writes JSON, `radars/report.py` turns that into the markdown the issue carries,
and `docs/radars.md` is what you need to write another one.

## Layout

    core/              plumbing - http, names, favourites, qobuz, radar,
                       state, paths
    radars/            new-release watchers, one thin source each - docs/radars.md
      qobuz.py  listenbrainz.py  itunes.py    core/radar.py drives these three
      remezcla.py        a blog, not an id namespace - its own script
      report.py          a radar's JSON -> markdown, for the weekly issue
    tests/             pytest, offline - every network call stubbed at the seam
    data/              favourites.json is the watchlist, committed and
                       hand-edited; data/ci/ is the runner's own seen-state.
                       Everything else in here is generated and ignored
    cache/             API responses - the source of truth, never regenerated
    .github/workflows/ radar.yml runs any radar; one caller per schedule
                       tests.yml: ruff, ty, pytest --cov on 3.11/3.12/3.13
    requirements*.lock hashed pins for CI - generated, see their headers

Deleting `cache/` costs a refetch and, for anything Qobuz has edited since, the
ability to reproduce an old output exactly. It is 85 MB and is not backed up
anywhere; `docs/adr/D7-cache-is-the-corpus.md` is the decision.

## Docs

| | |
|---|---|
| [favourites.md](docs/favourites.md) | the watchlist: what is in it, and how to edit it by hand |
| [radars.md](docs/radars.md) | what a radar is, and how to write another one |
| [history.md](docs/history.md) | what used to be on main, where it went, and what that cost |
| [adr/](docs/adr/README.md) | one file per decision, with the option it was weighed against and the measurement it rests on |

`main` is the radar and nothing else; the credits pipeline and its docs are
on the `ranking` branch. [history.md](docs/history.md) is that story.
