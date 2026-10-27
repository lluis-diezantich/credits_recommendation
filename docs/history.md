# What used to be here

`main` is the Friday known-artist radar and nothing else. This file is where
the README's account of how it got that way lives, so the README can describe
only what is here now. It is background, not instructions —
[D41](adr/D41-main-is-the-radar-the-rest-is-a-branch.md) is the decision and
the thing to read before any change that wants a piece of the archive back.

## The credits half

Starting from one artist, reading who actually made their records — producers,
engineers, players — and finding what else those people made was the premise,
and the pipeline that did it works. Its recommendations were not good enough to
keep iterating on, so on 2026-10-27 all of it moved out of main's way onto the
**`ranking`** branch: `policy.py`, `stages/`, nine `core/` modules, the store,
the ADRs that govern them. Nothing was deleted — `git checkout ranking` is the
whole thing back, and D41 says what moved, why, and what it costs.

## The monthly listening snapshot

It is off, and it is not free to resume: it fed on ListenBrainz's
`range=month`, which answers about one past calendar month and cannot be asked
again, so every month from now on is recoverable only by downloading a fresh
export by hand. D41 took that cost knowingly.

## The archived docs

`architecture.md`, `roadmap.md`, `store.md`, `profile.md`, `sources.md`,
`duckdb.md`, `disco-bahia.md` and the 71 KB `todo.md` that tracked the backlog
are on `ranking`:

    git show ranking:docs/roadmap.md
    git show ranking:todo.md

The gaps in the ADR index are the archived decisions; IDs are not reused.
