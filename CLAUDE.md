# Working in this repo

Pointers and traps only. The layout is in `README.md`, how to write a radar in
`docs/radars.md`, the watchlist in `docs/favourites.md`, and what was decided
against which alternative in `docs/adr/` — **do not restate them here.** This
file is for what those do not say and what a first read gets wrong.

## This is half a repository, on purpose

`main` is the Friday known-artist radar and nothing else. The credits pipeline
— `policy.py`, `stages/`, nine `core/` modules, the store, the ranking — is
archived on the **`ranking`** branch, and `docs/adr/D41-*.md` is the decision.
Read it before any change that looks like it wants a piece of that back.

Three consequences that bite:

- **Do not re-add an archived module to main.** If something here needs
  `core/listens.py` or a threshold from `policy.py`, that is a sign the change
  belongs on `ranking`, or that D41 should be superseded. Copying one file
  across is how both branches end up with a different version of it.
- **`core/` is shared with that branch.** `core/http.py`, `core/names.py`,
  `core/radar.py` and the CI hygiene exist on both. A fix here does not reach
  `ranking`, and the longer both move the worse the eventual merge. Worth
  knowing; not worth avoiding a fix over.
- **A kept ADR may link to a doc that is not here.** `D32` points at
  `../roadmap.md`, several point at `../../todo.md`. Those resolve on
  `ranking`. **Do not fix them** — an accepted decision is never rewritten,
  and D41's consequences say so explicitly.

## Invariants

- `core/` is pure and offline. `radars/` is where the network and the printing
  go. Plumbing takes its numbers as arguments.
- A decision that shapes what this reports gets an ADR in `docs/adr/`, with the
  option it was weighed against and the measurement it rests on. Write it as
  the change is made, not afterwards, and never rewrite an accepted one —
  supersede it, because the reason it went the other way is the point of
  keeping it. `docs/adr/README.md` says how; D41 is the shape to copy. IDs are
  not reused, and the gaps in the index are the archived ones.
- Decisions get extracted into pure functions and then tested, rather than left
  wedged between a fetch and a print. `core/radar.py`'s `verdict` is what that
  looks like when it is done: one function deciding report/skip/record, tested
  directly, with the fetch loop around it knowing nothing.
- A doc that states a number nothing verifies will drift. The number in
  `.pre-commit-config.yaml` ("23 of 26 files") and the 7278 in
  `releases-known-artists.yml` are both there to be re-measured, not quoted.

## Traps

- **The watchlist is hand-edited and nothing regenerates it.** `stages/favourites.py`
  went to `ranking` with everything else, so `data/favourites.json` is a
  committed file you edit. Adding an artist is `./radars/qobuz.py --find
  "Name"` and a new entry with `"qobuz_match": "manual"`. It is un-ignored in
  `.gitignore` for a reason the comment there states.
- **The Friday radar is stateless and reports repeats on purpose.** D32. Last
  Friday appears in consecutive issues because the cutoff is inclusive, and
  `data/ci/qobuz_seen.json` is frozen at 7278 ids. This is not a bug to fix;
  turning state back on is dropping one line in the caller, and it costs one
  duplicate issue covering everything since the freeze.
- **A radar records everything it SCANNED, not what it printed** — that is
  `record_scanned`, and it is why a first run absorbs the back catalogue past
  `--days` silently. `False` where the source is a window rather than a
  catalogue (`radars/listenbrainz.py`), because there, recording an unmatched
  release would hide it for good if you later watched that artist.
- **`--dry-run` is "record nothing", not "make no calls".** It still spends
  every request the run would have spent.
- **`core/radar.py` drives three of the four radars.** A behaviour change
  there to fix one of them changes the other two; D32's option 3 was declined
  for exactly that reason. Prefer a field on the `Radar` subclass, as `record_scanned` and
  `guard_empty_run` already are.
- **`cache/` is the corpus, not a cache.** 85 MB, not backed up, and D7 is the
  decision. `data/` is ignored except where it is named — `favourites.json` and
  `data/ci/` are un-ignored, and the `.gitignore` comment on each says why.
- **`ruff format` is advisory here.** `.pre-commit-config.yaml` runs it
  `--diff` and `stages: [manual]`, because layouts like the dict in
  `Release.row` are deliberate. Do not reformat them.
- **Tests are offline.** Every network call is stubbed at the seam in
  `tests/conftest.py`. Add a seam rather than a live call.

## Checks

    pytest -q                 # must pass
    ruff check . && ty check  # must be clean
