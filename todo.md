# TODO

What is known to be missing, grouped by what kind of work it is. Moved out of
the README so the entry point stays an orientation rather than a backlog.

Not the same thing as [roadmap.md](docs/roadmap.md), which assesses this
project *as a recommender*, stage by stage. This file is work items.

## The product

The gap between "a credits database" and "recommends music".

- **A radar for people, not artists.** The thesis, and the one thing this cannot
  do: alert on records made by *people* you follow. The pools hold 7,860
  candidate releases and nothing consumes them. One `album/get` per fresh
  release, cached.
- **A ranker.** 7,860 candidates, each with an explainable `via.signal.score`,
  and no order.
- **Album identity.** `core/radar.Release` now normalises what the radars
  report, but it is a *reporting* record keyed on each store's own id: two
  editions of one album are still two rows, and nothing reconciles a Qobuz id
  with an MBID. The pools are untouched by it. See
  [architecture.md](docs/architecture.md).
- **Record what you played.** The weekly issue is already a dated log of what
  was *shown*; the other half is missing, and without it the evaluation in
  [roadmap.md](docs/roadmap.md) has nothing to score.
- **Unify the role-class vocabularies.** `discover.py` folds engineering into
  `production`, `resolve_discogs.py` splits it out. Both live in `policy.py`;
  unifying them rewrites `classes` in existing data.

## Correctness

Where the code can be wrong without anything noticing.

- **`policy.py` and `core/credits.py` are untested.** Zero coverage on the two
  files holding every judgement in the project — the role weights,
  `writing_tier`, `selectivity`, and the packed-segment heuristic in
  `parse_performers`. A ranker will be built directly on top of both, so this
  is the prerequisite rather than a chore. Hours, not days.
- **No indexes and no primary keys in `data/music.db`.** `stages/load.py`
  creates 20-odd tables and not one index, on a store whose stated purpose is
  joins — over 190k listens. See [store.md](docs/store.md).
- **Two hand-rolled retry loops are left.** `stages/resolve_discogs.py:120` and
  `stages/writing.py:194` still sleep `0.8 * (attempt + 1)` on a 5xx, which
  `core/http.py`'s adapter has done with jitter and `Retry-After` since the
  `requests` move.
- **A weaker copy of the autosuggest is left.** `resolve_discogs.py:96`
  `qobuz_find_artist` duplicates `core.qobuz.search_artists` + `pick`, but
  searches one spelling instead of every name variant and cannot report
  `ambiguous`.

## Infrastructure

- **Nowhere durable to keep state.** A runner has no disk between runs, so the
  Friday job passes `--all` and lets the date window do the filtering;
  `data/*_seen.json` only ever accumulates on one laptop, and `--run-log`
  writes a file that dies with the job. The cost today is a release appearing
  in two consecutive issues when `--days` exceeds seven. Cheapest fix: have the
  Action commit the seen file back, which also turns the history into a log of
  what was reported. This blocks every stateful radar, not just this one.
- **`cache/` exists in one copy, on one laptop.** Deleting `data/music.db`
  costs one rerun; deleting `cache/` costs the corpus. This is a backup
  problem, not an architecture problem, and `rclone sync` answers it in twenty
  minutes without touching any code.

## Build and CI

Each of these is under an hour, and each is something a reviewer would expect.

- **No type checker.** Everything is annotated and nothing verifies it; `ruff`
  is lint, not types. Add `ty` or `pyright` to the dev extra and a step to
  `tests.yml`.
- **No lockfile.** `requests>=2.32` is a floor, not a lock, so CI can break on
  somebody else's release rather than on a change here.
- **No `pre-commit`.** `ruff` currently runs after the fact, which is how a
  lint backlog accumulated once already.
- **Actions float on major tags.** `actions/checkout@v4` and friends are moving
  references; pin to SHAs and add `dependabot.yml` to bump them deliberately.
- **No coverage measurement.** 76 tests and no record of what they reach, which
  is how `policy.py` stayed untested without it being obvious.
- **Only one Python version is tested.** `requires-python = ">=3.11"`, CI runs
  3.12 alone, so the floor is a claim rather than a tested fact.

## Smaller things

- **Resolve Apple ids.** Every `itunes_id` in `favourites.json` is null, so
  `radars/itunes.py` falls back to its built-in list of one artist. It has
  everything else it needs since `core/radar.py` — `--json`, the broken-run
  guard — so scheduling it is a fifteen-line caller against `radar.yml`. The
  ids are the only thing missing.
- **Decide the storefront.** `gb-en` is the default and the watchlist leans
  Latin and Iberian; `--store es-es` is a different catalogue, not a different
  view of one.
- **Cross-check coverage.** `./radars/listenbrainz.py --days 20 --dry-run` reads
  a second source for the same 89 artists; anything it names that Qobuz missed
  is a gap nothing else would reveal.
- **`--review` cannot re-ask about a row that resolved `exact`.** A wrong id
  that looked confident can only be fixed by editing the JSON.
- **`README.md` says `65 cases`.** It is 76.

## Not yet, on purpose

Recorded so the deferral is a decision rather than an oversight.

| | until |
|---|---|
| an orchestrator — Dagster, Prefect, Airflow | pipeline #3 exists. Two scripts and a `Makefile` do not need a scheduler with a UI |
| Postgres | the ranker needs feedback state — dismissed, played, rated. That state is what defines the schema, so building it first means guessing |
| object storage, `UPath`, R2 | after `cache/` is simply backed up. The backup is the urgent half; the migration is not |
| `pipelines/<name>/` layout | `stages/` becomes a junk drawer. With the credits chain paused, it will not soon |
| a source registry, structured logging | the second and third radar are actually scheduled |
