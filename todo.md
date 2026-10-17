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

- **~~`policy.py` and `core/credits.py` are untested.~~** Done: both at 100%,
  94 cases in `tests/test_policy.py` and `tests/test_credits.py`. The three
  disagreeing role vocabularies are now pinned against each other, so unifying
  them fails a test rather than quietly rewriting a column of existing data.

- **Two files are still at zero coverage.** Overall 34% → 67%. Done:
  `core/discogs.py`, `radars/itunes.py` and `radars/listenbrainz.py` at 100%,
  `stages/load.py` 99%, `stages/writing.py` 55%,
  `stages/resolve_discogs.py` 28%.

  Still at 0%: **`stages/discover.py`** (121 statements) and
  **`stages/resolve_qobuz.py`** (112). They are the same shape as the two below
  — one long `main()` with the decisions wedged between a fetch and a print —
  so they want the same treatment: extract, then test. `discover.py` is the
  more valuable of the two, being the stage the whole credit graph comes out
  of. `radars/remezcla.py` is at 41% and is the other soft spot.

  The last two needed their decisions extracted before they could be tested at
  all, which is done: `classify_rows`, `flag_album_wide_credits`, `fold_songs`
  and `pages_needed` in `writing.py`; `gate_verdict`, `select_targets`,
  `signal_of`, `known_totals` and `role_census` in `resolve_discogs.py`. All
  pure, all tested, and the refactor is verified behaviour-preserving —
  `writing.py` reproduces the committed `writing_jorge-drexler.json` byte for
  byte from `cache/` alone, and both of `resolve_discogs.py`'s offline modes
  print identical output.

  What is still uncovered in those two is the orchestration: `main()`,
  `build_pool()` and the fetch-and-print middle of `run_one()`. That is now
  what those functions ARE, the decisions having moved out. Covering them means
  stubbing Discogs plus the filesystem and asserting on printed output, which
  buys much less than the 65 decision tests did — worth doing when
  `build_pool` next changes, not before.

- **`collapse()` never merges two titles of the same length.** Found while
  testing it. The fuzzy pass skips any candidate that is not *strictly* longer
  (`len(other) <= len(target)`), so equal-length spellings never meet however
  similar they are. `writing.py`'s own docstring offers "orcuridad" as a caught
  typo and it is exactly this case: 24 characters against 24, similarity 0.958
  against a 0.92 floor, no merge.

  Not a one-line fix, which is why it is recorded rather than done: choosing a
  canonical form between two equal-length keys is a new decision (first seen?
  alphabetical? most frequent?), and the longest-wins rule exists so the fuller
  title survives. A test states the current behaviour so the choice is
  deliberate when it is made.

- **~~No indexes in `data/music.db`.~~** Done: 45 of them, created after the
  bulk load so the rebuild stays under a second. Every join and filter in
  [store.md](docs/store.md) now uses one instead of scanning the table.

- **~~The loader inserted duplicate rows.~~** Fixed. `load_people` assembles
  six junction tables by appending from several files, and only three went
  through a dedup; all six now go through one `deduped()` helper.
  `person_roles` 923 → 722, `person_albums` 777 → 563, and all six are now
  distinct on the full tuple.

  `dict.fromkeys`, not the obvious `sorted(set(...))`, and that is not a style
  choice — sorting these tuples *raises*. They carry `None` wherever a source
  file omits a column (an album with no date, an edge with no release count,
  and `n`, which is `None` for `watchlist.json`'s bare-list role form and an
  int everywhere else), and Python will not compare `None` with `str` or `int`.
  The fix that looks right turns a silently duplicated row into a failed build.

- **~~No primary keys in `data/music.db`.~~** Done: 15 of the 21 tables carry
  one, and the build got *faster* — 0.77s to 0.23s — because a key is itself a
  unique index, so 15 single-column indexes it now subsumes were dropped (45
  indexes to 30).

  `Loader.insert` turns a violation into a message naming the table and the
  offending row, because sqlite's own wording names the constraint and not the
  row, and a 216k-row build is not a place to go looking.

  Six tables have no key, each for a stated reason rather than by omission:

  | | |
  |---|---|
  | `person_roles` | needs a merge decision, not a constraint: 722 rows against 612 distinct `(person_key, role)`, because the same role arrives with a count from one file and `NULL` from another. Ruling that a count beats an absence is source precedence |
  | `song_performers` | `album_title` is NULL *by design* — `load_songs` iterates `perf["albums"] or [None]`. Today's corpus has an album for every performer, which is not the same as the column being non-null |
  | `tracks`, `credits` | still genuinely duplicated (910/906 and 11,926/9,516). The duplicates are inside the cached pages, so deduping means deciding which cached copy wins — a question about the corpus |
  | `listens`, `meta` | no natural key. `listens` is an append-only log and `listened_at` is nullable |

  Two caveats worth keeping, both now in tests:

  - SQLite will not say this: in a rowid table a PK column may still be NULL,
    and NULLs count as distinct. Each key protects rows whose key columns are
    all present — all of them today — and silently protects nothing on a row
    where a source file omitted a field. This is also where the engines
    diverge: DuckDB follows the standard and refuses NULL in a key, so a
    `song_performers` key would build under sqlite and fail under duckdb.
  - `person_albums (person_key, album_id)` rests on an empirical fact, not a
    structural one. Two files describe those albums and nothing makes them
    agree; measured, there are 214 shared `(person, album)` pairs and zero
    disagreements, because `appearances` derives from the same discovery pass.
    If that ever breaks, the build stops and names the row — which is the right
    failure, since the alternative is a count that silently double-counts.

- **~~Two hand-rolled retry loops are left.~~** Done: both deleted.
  `stages/writing.py` goes through `core.qobuz.get_json` now, so the adapter's
  jitter and `Retry-After` apply, and the "5xx after 3 tries" warning went
  with the loop that produced it.
- **~~A weaker copy of the autosuggest is left.~~** Done, and it was hiding a
  real defect. `qobuz_find_artist` is replaced by `core.qobuz.find_artist`,
  which reports `ambiguous`, keeps `error` apart from `not_found`, and tries
  **every** spelling — which matters more than it sounds: those names come
  straight out of Discogs credit rows, so `"Valeria Castro*"` and `"Mauro (5)"`
  were being matched verbatim and failing. `search_artists` keeps its lossy
  shape for the two interactive callers. `stages/resolve_qobuz.py:140` still
  has the old blindness — a one-line change whenever that stage next matters.

## Infrastructure

- **~~Nowhere durable to keep state.~~** Done. `core/radar.py` takes
  `--state PATH`, and `radar.yml` derives `data/ci/<radar>_seen.json`, runs
  against it, and commits it back — so the Friday radar is stateful and the git
  history of that file is a dated log of what was actually reported, which is
  the impression data [roadmap.md](docs/roadmap.md) needs before anything can
  be evaluated. `stateless: true` remains for a backfill.

  Four things that are load-bearing rather than incidental, recorded so nobody
  "tidies" them:

  - **`data/ci/`, not `data/<radar>_seen.json`.** The reason that file is
    gitignored still holds: a runner's "already reported" must not arrive on a
    laptop and silence the radar there. `.gitignore` un-ignores this directory
    alone.
  - **The record step runs AFTER the issue is opened.** If the issue fails and
    the ids are already recorded, that week's releases are marked seen and
    appear in no issue at all. Losing state costs one duplicate; losing the
    issue costs the week.
  - **The caller needs `contents: write` too.** A called workflow can never
    hold more permission than its caller grants, so leaving
    `releases-known-artists.yml` at `read` makes only the push 403 while every
    other step succeeds — the quietest possible way to lose the state.
  - **`concurrency` is queued, not cancelled.** Two runs racing means the
    loser's push is rejected; a cancelled radar run is a missed week.

  Expect the first stateful commit to be large (~136 KB): `record_scanned` is
  True for Qobuz, so a run records every id it *scanned*, not just what it
  reported — which is what stops an old release resurfacing the week it falls
  out of the date window. Later commits are small.

- **`cache/` exists in one copy, on one laptop.** Deleting `data/music.db`
  costs one rerun; deleting `cache/` costs the corpus. This is a backup
  problem, not an architecture problem, and `rclone sync` answers it in twenty
  minutes without touching any code.

## Build and CI

~~Each of these is under an hour, and each is something a reviewer would
expect.~~ All done.

- **~~No type checker.~~** `ty`, in the dev extra and a `tests.yml` step,
  configured in `pyproject.toml` so `ty check` means the same on a laptop.
  Clean now, and it found two real things on its first run: `radars/qobuz.py`
  overrode `add_arguments(self, ap)` against a base taking `parser`, so a
  keyword call broke on that one subclass, and `radars/remezcla.py` called
  `find(attrs=...)` in a form bs4's own overloads reject. Both fixed. The only
  rule suppressed in source is `unresolved-import`, for the optional `duckdb`
  that `stages/load.py` already guards with `try/except ImportError`.
- **~~No lockfile.~~** Two, hashed and universal, resolved for the 3.11 floor
  so one file serves the whole matrix: `requirements.lock` for the radar's
  runtime and `requirements-dev.lock` for CI. Installed with
  `--require-hashes`, then the project with `--no-deps` so the lock stays
  authoritative. A test-only package can no longer break the Friday job,
  because it is not in that job's environment at all.
- **~~No `pre-commit`.~~** `.pre-commit-config.yaml`, pinned to a rev.
  `ruff-format` is `--diff` only, never a rewrite: the aligned columns in
  `policy.py` and the comment-per-value `SCHEMA` in `load.py` are deliberate.
  `pytest` and `ty` stay out of it — both read the whole project, and a hook
  that runs the suite is a hook people pass `--no-verify` to, which costs the
  lint checks as well.
- **~~Actions float on major tags.~~** All three pinned to SHAs in both
  workflows, with `.github/dependabot.yml` bumping actions and pip weekly on
  Monday — grouped so a lint bump never blocks a security bump to `requests`.
- **~~No coverage measurement.~~** `pytest --cov`, into the job summary rather
  than a service, and no `fail_under` — the useful signal is per-file, and a
  global percentage averages `load.py` together with `policy.py` until neither
  means anything. It paid for itself immediately: see the zero-coverage entry
  under Correctness.
- **~~Only one Python version is tested.~~** 3.11, 3.12 and 3.13, with
  `fail-fast: false`. The floor is a tested fact now.

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
- **~~`README.md` says `65 cases`.~~** It says 187, which is what it is.

## Not yet, on purpose

Recorded so the deferral is a decision rather than an oversight.

| | until |
|---|---|
| an orchestrator — Dagster, Prefect, Airflow | pipeline #3 exists. Two scripts and a `Makefile` do not need a scheduler with a UI |
| Postgres | the ranker needs feedback state — dismissed, played, rated. That state is what defines the schema, so building it first means guessing |
| object storage, `UPath`, R2 | after `cache/` is simply backed up. The backup is the urgent half; the migration is not |
| `pipelines/<name>/` layout | `stages/` becomes a junk drawer. With the credits chain paused, it will not soon |
| a source registry, structured logging | the second and third radar are actually scheduled |
