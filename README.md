# music_recommendation

Personal project for recommending music.

## Features

- New releases for known artists

## Install

    python3 -m venv .venv && ./.venv/bin/pip install -e ".[dev]"
    ./.venv/bin/pre-commit install

## Running it

    ./radars/qobuz.py --days 90            # what came out, from Qobuz
    ./radars/qobuz.py --find "Name"        # the Qobuz id for a name
    ./radars/itunes.py --days 30           # the same question, Apple's catalogue
    ./radars/listenbrainz.py --days 30     # and MusicBrainz's
    ./radars/remezcla.py                   # a blog, not an id namespace
    pytest -q                              # the suite, offline

Each radar writes JSON, `radars/report.py` turns that into markdown.

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

`radars/remezcla.py` is the only thing here that reads `cache/`, and
`cache/remezcla` is 84 MB of issues it treats as cached forever — a published
issue never changes, so deleting them costs a refetch of every issue the blog
still serves. The other subdirectories are the archived pipeline's corpus, not
this radar's. None of it is backed up anywhere;
`docs/adr/D7-cache-is-the-corpus.md` is the decision.

## Docs

| | |
|---|---|
| [favourites.md](docs/favourites.md) | the watchlist: what is in it, and how to edit it by hand |
| [radars.md](docs/radars.md) | what a radar is, and how to write another one |
| [history.md](docs/history.md) | what used to be on main, where it went, and what that cost |
| [adr/](docs/adr/README.md) | one file per decision, with the option it was weighed against and the measurement it rests on |

`main` is the radar and nothing else; the credits pipeline and its docs are
on the `ranking` branch. [history.md](docs/history.md) is that story.
