# Working in this repo

Pointers and traps only. The layout is in `README.md`, the reasoning in
`docs/architecture.md`, the backlog in `todo.md` — **do not restate them here.**
This file is for what those do not say and what a first read gets wrong.

## Invariants

- `policy.py` holds every contestable number, in one visible file at the root.
  A threshold inside the module that consumes it is the bug this project was
  reorganised to prevent — `docs/architecture.md` has the argument.
- `core/` never imports `policy`. Plumbing takes a threshold as an argument;
  judgement lives one layer up.
- `core/` is pure and offline. `stages/` and `radars/` are where the network
  and the printing go.
- Decisions get extracted into pure functions and then tested, rather than left
  wedged between a fetch and a print. `stages/writing.py` and
  `stages/resolve_discogs.py` are what that looks like when it is done.

## Measuring

The thresholds here are calibrated against real listening, so a number arrives
with evidence or not at all.

- Use the **full export**, never `listenbrainz_sample.zip`. It is 1% of the
  data and shadowed the real file for a while, which made every number wrong
  by 95×.
- Name the artists a threshold was measured against, in the comment beside it.
  `MIN_WRITING_SHARE`, `M24_FLOOR` and `EMERGING_PLAYS` all do.
- When two signals disagree about one artist, check whether they are separate
  axes before reconciling them. If they are, **flag rather than reclassify** —
  `COVERS_MILL_HINTS` and `writing_tier`'s `lyrics_only` are the precedent.
- A doc that states a number nothing verifies will drift. `docs/store.md` said
  190,196 listens for months while the store held 2,000.

## Traps

- **`--dry-run` is not "make no calls".** On `stages/favourites.py` it skips the
  file write and still spends one Qobuz search per unresolved name.
- **`core.listens` resolves its month directory per call**, from module
  globals. A test must redirect `SEEDED` *and* `SNAPSHOTS`; `conftest.py` now
  does it for every test, because patching one of them wrote fixtures into real
  data and overwrote two months of listening.
- **`cache/` is disposable; `data/` is ignored except where it is named.**
  `favourites.json`, `data/ci/` and `data/listens_months/` are un-ignored, and
  the `.gitignore` comment on each says why that file cannot be regenerated.
  Read them before adding another.
- **`ruff format` is advisory here.** `.pre-commit-config.yaml` runs it with
  `--diff` only, because the aligned columns in `policy.py` and the
  comment-per-value `SCHEMA` in `stages/load.py` are deliberate. Do not
  reformat them.
- **Tests are offline.** Every network call is stubbed at the seam in
  `tests/conftest.py`. Add a seam rather than a live call.

## Checks

    pytest -q                 # must pass
    ruff check . && ty check  # must be clean
