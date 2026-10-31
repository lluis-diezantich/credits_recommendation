# Decisions (ADRs)

One file per decision that shapes what this project recommends or how the repo
is laid out. IDs `D1`, `D2`, … are stable, and the code refers to them.

Why these exist alongside the other docs: `README.md` says what the layout IS
and `CLAUDE.md` lists the traps. Neither is a record of *what was decided,
when, against which alternative*. D1-D13 are backfilled from the code and the
history on 2026-10-20; D14 was written as the change was made, which is the
intended way round from here.

## Where the other thirty-one are

[D41](D41-main-is-the-radar-the-rest-is-a-branch.md) archived the credits
pipeline onto the **`ranking`** branch on 2026-10-27, and the ADRs that govern
files it took went with it. The full D1-D40 index is there:

    git show ranking:docs/adr/README.md

The IDs are not reused and not renumbered. What is listed below is the subset
that governs code `main` still holds, which is why the numbering has gaps. Some
of these files link to docs that now live only on `ranking` — those links
dangle here and resolve there, and they are left alone on purpose by rule 3.

## How to add or change one

1. Copy [template.md](template.md) to `D<next>-<short-name>.md`.
2. Add a row to the index below.
3. Never rewrite an accepted decision. Write a new one, and mark the old one
   `Superseded by DN` — the reason it was decided the other way is the point of
   keeping it. This holds for a decision whose file is on the other branch too.
4. A number in an ADR is a measurement with a date on it. If it was not
   measured, the Evidence section says so.

## Index

| ID | Decision | Status |
| --- | --- | --- |
| [D2](D2-pure-core-dirty-edges.md) | `core/` is pure and offline; `stages/` and `radars/` do the network and the printing | Accepted |
| [D3](D3-offline-tests.md) | Tests stub the network at the seam, and never call a real API | Accepted |
| [D7](D7-cache-is-the-corpus.md) | `cache/` is the source of truth for what an API said, and is not backed up | Accepted |
| [D8](D8-one-pipeline-for-now.md) | The Friday known-artist radar is the whole product for now | Superseded by D22 (seeds only), and true again under D41 |
| [D11](D11-radar-state-in-ci.md) | Radar state lives in `data/ci/`, committed by the workflow after the issue opens | Accepted |
| [D12](D12-hashed-locks-advisory-format.md) | CI installs from hashed lockfiles; `ruff format` is advisory | Accepted |
| [D32](D32-the-known-artist-radar-reports-the-whole-week.md) | The known-artist radar reports the whole week, late on Friday, and records nothing | Accepted |
| [D33](D33-a-pre-order-is-not-news.md) | The Qobuz radar drops releases dated after the run, and does not record them | Accepted |
| [D41](D41-main-is-the-radar-the-rest-is-a-branch.md) | Main is the known-artist radar alone; the credits pipeline is archived on the `ranking` branch | Accepted |
| [D42](D42-a-credit-is-a-release-you-would-have-missed.md) | The radar also reports what its artists are credited on, found by searching the track index | Accepted |
| [D43](D43-the-issue-body-is-the-records.md) | The issue body is the records; every count about the run is folded into the warnings block | Accepted |
| [D44](D44-the-label-is-the-query-the-credit-is-the-judgement.md) | The label is the query and the credit is the judgement: producers are found by scanning the labels they work for | Proposed, default amended by D45 |
| [D45](D45-the-label-is-reason-enough-for-an-album.md) | The label radar reports every album on a watched label, and names the credit when there is one | Proposed |
