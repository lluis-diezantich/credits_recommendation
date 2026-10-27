# D41: Main is the known-artist radar alone; the credits pipeline is archived on a branch

- **Status:** Accepted
- **Date:** 2026-10-27
- **Where it lives:** the `ranking` branch (everything removed here is reachable
  from it), [`../../README.md`](../../README.md),
  [`../../CLAUDE.md`](../../CLAUDE.md),
  [`../../pyproject.toml`](../../pyproject.toml) (`packages`, `coverage.run`),
  [`../../.gitignore`](../../.gitignore), the index in [README.md](README.md),
  and the absence of `stages/` and `policy.py`

## Context

Two scheduled jobs ran here. The known-artist radar opens an issue every
Friday and is the one output that gets read. The credits pipeline — seeds,
discover, the two resolvers, writing, load, rank, ubiquity, baseline, scenes —
produces a ranked list whose recommendations are, in the owner's judgement,
not good enough to keep building on. The monthly listening snapshot had already
been disabled by hand before this decision.

So the repository was carrying twenty-six modules, twenty-four test files,
seven docs and a 70 KB `policy.py` for a pipeline nobody is iterating on, and
the radar's eleven files sat inside it. The cost is not disk. It is that
`README.md`, `CLAUDE.md` and this directory all describe the pipeline as the
main subject, so every read of the repo starts by orienting around paused work,
and every invariant in `CLAUDE.md` is about a file the radar never imports.

The pipeline is paused, not abandoned. Nothing about it was concluded to be
wrong; the recommendations are not yet worth the weekly attention.

## Options

1. **Leave it all on main, document the pause.** Costs nothing today. The docs
   keep describing two products, and "which half is live" becomes something a
   reader has to infer from the workflow directory.
2. **Delete it, rely on git history.** Smallest main. Recovering it means
   knowing which commit to look in, and a commit nobody has a name for is one
   nobody finds in six months.
3. **Branch at the current commit, delete forward on main.** Both refs point at
   the same commit, so nothing is copied and nothing is lost; `ranking` is a
   name for the state of the world on 2026-10-27, and main walks away from it.
   Costs a one-off rewrite of the shared files, and divergence if both branches
   ever move.
4. **Two repositories.** Clean separation, and it duplicates `core/http.py`,
   `core/names.py`, `cache/` and the CI hygiene immediately.

## Decision

Option 3. `ranking` is pushed at `e4568b0`, which is the commit that landed
D36–D40. Main keeps the three remaining workflows, the eight `core/` modules
the radars reach, all six radars, twelve test files, `data/favourites.json`,
`data/ci/`, and the eight ADRs that govern files main still holds.

`stages/` goes whole, including `profile.py` and `favourites.py`: with the
snapshot job off, the watchlist is frozen by choice, and a stage that cannot
be fed is worse on main than a stage that is absent.

The other three radars stay even though only Qobuz is scheduled. They import
nothing beyond what the Qobuz radar already needs — `core/{favourites, http,
paths, radar, names, state}` — so keeping them costs three files and three
tests, against fishing them back out of a branch when the next radar lands.

## Evidence

Not measured, and this is a scope decision rather than a threshold, so there is
no number that would have settled it. What was counted:

| | before | main after |
| --- | --- | --- |
| `core/` modules | 17 | 8 |
| `stages/` | 13 | 0 |
| radars | 6 | 6 |
| test files | 34 | 12 |
| tests passing | 1018 | 174 |
| `docs/*.md` | 10 | 3 |
| ADRs | 40 | 9 |
| scheduled workflows | 2 | 1 |

The dependency closure was checked rather than assumed: nothing main keeps
imports anything main dropped, and `policy.py` is not reachable from any radar.

The judgement the decision actually rests on — that the ranked list is not good
enough to keep building on — is unmeasured, and that is the point of
D29 (on `ranking`): the shown-log
exists precisely because nothing here had settled which strategy works. It has
not accumulated enough runs to settle it. Pausing is therefore a decision taken
*without* the evidence that was supposed to inform it, which is the honest
reason this is reversible by design and not a conclusion about the thesis.

## Consequences

- **Nothing is lost, and nothing was moved.** `git show ranking:policy.py` works,
  and `git checkout ranking` restores the whole tree. The branch is a name for a
  commit, not a copy.
- **Three files on disk are not protected by the branch**, because they were
  never tracked: `cache/` (85 MB, the source of truth per
  [D7](D7-cache-is-the-corpus.md), and not backed up), `data/music.db`, and the
  generated `data/*.json`. Deleting tracked files left them alone. A fresh clone
  of either branch will not have them.
- **`data/shown.json`, `data/aliases.json` and `data/listens_months/` are
  tracked on `ranking` only.** The `.gitignore` lines that un-ignored them are
  gone from main, with a comment saying where they went. All three are
  un-regenerable, which is why those lines existed; the branch is what keeps
  them.
- **The listening snapshot gap grows.** `range=month` cannot be asked again, so
  every month from 2026-11 on is recoverable only by downloading a fresh export
  by hand. Accepted knowingly; the alternative was keeping one workflow alive
  for a pipeline nobody is running.
- **The eight kept ADRs still link to archived files.** D32 points at
  `../roadmap.md`, several point at `../../todo.md`. Those links dangle on main
  and resolve on `ranking`. They are **not** being edited: the rule in
  [README.md](README.md) is that an accepted decision is never rewritten, and a
  dangling link is a smaller lie than a retouched record of what was decided.
- **The backlog is on `ranking`.** `todo.md` was 71 KB and almost all of it was
  pipeline work. Main has no backlog file; the radar's open questions live in
  D32's consequences.
- **Divergence is the real risk.** Both branches hold `core/http.py`,
  `core/names.py`, `core/radar.py` and the CI hygiene. A fix to any of those on
  main will not reach `ranking`, and reviving the branch means a merge whose
  conflicts are exactly the six files rewritten here. Cheap while main only
  gains radars; expensive the longer both move.
- **Reviving it** is `git merge ranking` plus restoring `stages` and
  `py-modules = ["policy"]` in `pyproject.toml` and the three `.gitignore`
  lines. The comments at each of those sites say so.
- **What would reopen this:** wanting the credits pipeline back, or a second
  radar growing enough shared code that the branch's copy of `core/` is a
  liability rather than an archive.
