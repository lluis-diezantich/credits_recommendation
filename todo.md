# TODO

What is known to be missing, grouped by what kind of work it is. Moved out of
the README so the entry point stays an orientation rather than a backlog.

Not the same thing as [roadmap.md](docs/roadmap.md), which assesses this
project *as a recommender*, stage by stage. This file is work items.

## Where this is going (decided 2026-10-17)

**One pipeline for now.** The Friday known-artist radar is the whole product
and stays that way for a while, to see how it behaves in use. Features get
added afterwards one at a time, and small — not a stage at a time.

That is a deliberate narrowing, so the backlog below is a backlog and not a
plan. Two things settle how the rest of it is ordered, and both were measured
rather than guessed:

**Growing the credit graph is expensive; using it is nearly free.** One
`discover` run on one seed produced 278 people and 7,860 candidate releases,
and that fan-out — credits per album, then a resolve per person, then a
discography per person — is the part that multiplies. Adding a second seed
means paying it again. But querying what is already on disk costs nothing, and
a radar over the people already resolved would be **68 `artist/get` per run**,
which is SMALLER than the 91 the Friday job already makes without complaint.
So the thing to avoid is more seeds, not more features over the one graph.

**The pool is not trustworthy yet, and that is the real blocker** — not API
cost. See the entry under Correctness. Nothing credits-based is worth building
on top of it until that is fixed, and fixing it costs no requests.

## The product

The gap between "a credits database" and "recommends music".

- **~~Profile the watchlist, instead of trusting a play count.~~** Done, and
  documented in [profile.md](docs/profile.md): `core/listens.py`,
  `stages/profile.py` and three floors in `policy.py`, at 100% coverage.

  Two numbers, no ratio — lifetime active months and months in the last 24 —
  which puts 80 artists in `core`, 113 in `lapsed` and names 140 deep artists
  the ListenBrainz ranking never surfaced. Radiohead lands `lapsed` on 73
  lifetime months against 3 recent, confirmed by hand.

  **What is still open**, and it is the half that changes behaviour: nothing
  writes a verdict back into `data/favourites.json`, so the radar still watches
  whatever ListenBrainz ranked. Two things block a clean write, both measured:

  - `emerging` is 2,006 artists, because the currency test scales to a short
    history and three recent months out of three qualifies. Right as a verdict,
    useless as a list. It needs a floor nobody has set.
  - a burst reads as decay. Omar Rodríguez-López has 3 recent months and 154
    plays inside them, last played this month, and lands `lapsed`.

  It also has two answers to "how many artists do I watch". 93 entries are
  un-muted but the radar watches **91**, because `favourites.ids_for` keys on
  `qobuz_id` and two pairs share one: `j milo`/`Milo j`, and `Rita Indiana`/
  `Rita Indiana y Los Misterios`. Harmless today — the collapse is silent and
  correct — but a profile that reports per-artist numbers has to pick which
  grain it means, and duplicate spellings are the first thing it should surface.

  The numbers that used to be in this entry came from `listenbrainz_sample.zip`,
  1% of the export, and two of them were wrong: `load.py` takes
  `sorted(glob)[-1]`, and "sample" sorts after the real export, so the sample
  had been shadowing 190,131 listens. `--seed` picks the largest file instead;
  **`load.py` still has the defect.** The tracks-against-plays rule also did not
  survive contact with the full file — every artist sits between 0.50 and 1.0
  tracks per play, so it discriminates nothing.

- **A radar for people, not artists.** The thesis, and the one thing this cannot
  do: alert on records made by *people* you follow. The pools hold 7,860
  candidate releases and nothing consumes them. One `album/get` per fresh
  release, cached.

  Costed since: **68 `artist/get` per run** for the 68 people in the graph
  carrying a Qobuz id, against the 91 the Friday radar already makes. Cheap.
  Blocked on the pool being trustworthy, not on the budget — see Correctness.
  It also lags by construction, because credits are often registered days
  after a release.

- **A ranker.** 7,860 candidates, each with an explainable `via.signal.score`,
  and no order.

  Do not build this yet. `sig_score` currently ranks the name collisions
  FIRST: "Morgan" carries 323 releases at a score of 1.0, the maximum. Ordering
  a list whose top is wrong makes the wrongness more prominent, not less.
  Filtering comes first.
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

- **Nearly half the candidate pool is name collisions, and the score promotes
  them.** The most important open defect, and the reason nothing credits-based
  should be built yet. Measured 2026-10-17 on the committed pools:

  | | |
  |---|---|
  | `single_token_name` flagged | **3,673 of 7,860 rows (47%)** |
  | top 6 contributors | 1,887 rows (24% of the pool) |

  | via | rows | score | how it got in |
  |---|---|---|---|
  | Henry Mancini | 459 | 0.105 | via José María Rosillo |
  | Morgan | 323 | **1.00** | via Carles Campi Campón |
  | Arcángel | 309 | 0.18 | via Bori Alarcón |
  | Mama | 291 | 0.105 | via José María Rosillo |
  | Cooper | 261 | 0.21 | via José María Rosillo |
  | Francisco | 244 | 0.18 | via Bori Alarcón |

  Henry Mancini is the clearest: the releases reached through him are the
  *Peter Gunn* soundtracks, 1958-60. Rosillo is a Spanish engineer who worked
  on Drexler records and did not work on Peter Gunn. The others — "Morgan",
  "Mama", "Cooper", "Francisco" — are generic single tokens.

  The mechanism is `build_pool` in `stages/resolve_discogs.py`: it takes a
  collaborator NAME off a Discogs credit row and exact-matches it in Qobuz.
  "Cooper" exact-matches a real Qobuz artist — just not the right one — and
  that artist's whole discography enters the pool. `find_artist` refuses fuzzy
  matches precisely to avoid this, but an exact match on one common token is
  indistinguishable from a correct one at that layer: the name is all the
  evidence there is.

  Worse than the volume is the SCORE. "Morgan" sits at 1.0, the maximum,
  because the referring person is a selective producer and the signal is
  computed from the REFERRER, never from how plausible the match itself is.
  So the junk is not merely present, it is ranked first.

  What would fix it, in rough order of how much it buys:

  - drop or heavily penalise `single_token_name` — 47% of rows, and the flag
    already exists and is already stored. One judgement call in `policy.py`.
  - require more than a bare exact match for a single-token name: an album
    count, an overlap with the referrer's own catalogue, or a genre that is not
    a mid-century film score.
  - fold match plausibility into `sig_score`, so a shaky resolve cannot
    inherit a strong referrer's weight.

  All free — no requests. This is the "filters instead of ranking" row in
  [roadmap.md](docs/roadmap.md), and it reads as a nice-to-have there; the
  numbers above make it the prerequisite.

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
  buys much less than the 110 decision tests did — worth doing when
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

- **~~No indexes in `data/music.db`.~~** Done: 30 of them, created after the
  bulk load so the rebuild stays under a second. Every join and filter in
  [store.md](docs/store.md) now uses one instead of scanning the table. It was
  45 until the primary keys went on and subsumed 15 — see that entry below.

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

- **Nothing ever calls the real APIs except the Friday job.** The suite stubs
  every network call at the seam, which is correct — it is why the tests are
  offline, fast and free. The cost is that a *source* changing shape is
  invisible: Qobuz renaming a field, Apple dropping `releaseDate`, Discogs
  changing its pagination. Every test still passes, and the first anyone knows
  is a Friday issue that is empty or wrong.

  A canary closes it: one scheduled job that calls each source for real,
  asserts the handful of fields the radars actually read, and opens an issue
  when one is missing. `--dry-run` already exists on all three radars, so this
  is a caller plus a small assertion script, not new machinery. Under an hour,
  and it protects the only part of this that runs unattended.

  Deliberately separate from `tests.yml`: a canary fails when a third party
  changes something, which is news but not a broken commit, and wiring it into
  the commit checks would make every push red for a reason nobody pushed.

## Build and CI

~~Each of these is under an hour, and each is something a reviewer would
expect.~~ The original six are done. Two more have since become worth having,
both still under an hour.

- **No vulnerability scanning.** `dependabot.yml` bumps versions; it does not
  know which of them are vulnerable. `pip-audit` against the two lockfiles is
  one step and answers a different question.

- **No required status check on `main`.** There is no branch protection at all
  (the API returns 404). `tests.yml` says advisory-on-purpose, and at 76 tests
  that was reasonable; at 493 with `ruff` and `ty` gating as well, requiring
  the check on pull requests costs nothing and stops a red merge.

  Separately, and this is the sharper lesson: a `todo.md` conflict between two
  merged PRs was resolved in favour of the older text, silently reverting a
  correction. Branch protection would not have caught that. What would: either
  stop editing `todo.md` in every branch, or give it a union merge driver in
  `.gitattributes` so both sides survive a conflict instead of one winning.

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
- **"Who else recorded this song" is thinner than it sounds.**
  [roadmap.md](docs/roadmap.md) lists it as working exactly, today, and the
  lookup does work — but only **26 of 257 songs (10%)** have two or more other
  non-mill recordings. One song has 19 performers and one has 16; the long tail
  has one each. Worth building as a lookup, not as a feature anyone would
  notice. Measured 2026-10-17.
- **`--review` cannot re-ask about a row that resolved `exact`.** A wrong id
  that looked confident can only be fixed by editing the JSON.
- **~~`README.md` says `65 cases`.~~** It says 551, which is what it is. Worth
  a glance whenever a batch of tests lands — it has been wrong twice now.

## Not yet, on purpose

Recorded so the deferral is a decision rather than an oversight.

| | until |
|---|---|
| an orchestrator — Dagster, Prefect, Airflow | pipeline #3 exists. Two scripts and a `Makefile` do not need a scheduler with a UI |
| Postgres | the ranker needs feedback state — dismissed, played, rated. That state is what defines the schema, so building it first means guessing |
| backing up `cache/` | it is needed. Decided 2026-10-17: the 84 MB is `cache/remezcla`, raw HTML of a blog that is still online and re-scrapable, and the part that carries real weight is 650 KB across `cache/credits` (63 albums) and `cache/search` (10 pages) — refetchable in under a minute of requests. The exposure is a re-run, not a lost corpus, so it is cheaper to refetch when relevant than to maintain a sync. The one thing a refetch cannot recover is a credit Qobuz has since edited or removed; `writing.py`'s cache is what makes its output reproducible, so if that output ever needs to be defended rather than regenerated, copy the 650 KB first |
| object storage, `UPath`, R2 | `cache/` outgrows a laptop, which at 85 MB it has not |
| `pipelines/<name>/` layout | `stages/` becomes a junk drawer. With the credits chain paused, it will not soon |
| a source registry, structured logging | the second and third radar are actually scheduled |
