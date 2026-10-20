# D10: Ask MusicBrainz who has stopped, rather than guessing from release dates

- **Status:** Accepted
- **Date:** 2026-10-18
- **Where it lives:** `./stages/favourites.py --check-active`,
  `core/musicbrainz.py`, `favourites.ids_for`, [../favourites.md](../favourites.md)

## Context

The Friday radar fetches a discography per watched artist. Some of those artists
cannot produce a new release at all, and each one spends a request every week.

## Options

1. **Infer from the release dates** already being fetched: free, no new source.
2. **Ask MusicBrainz for `life-span.ended`** per watched artist: one source
   more, and an explicit answer.

## Decision

Option 2, because the obvious test fails on exactly the artists it is for: a
dead artist keeps putting out compilations, so "no release in N years" never
fires for them. The verdict is stamped into `data/favourites.json` as `ended`,
which `favourites.ids_for` skips alongside `watch: false`.

## Evidence

Six of 93 watched artists were found ended — four dead, two split — so the
radar had been spending six of its 91 weekly requests on artists who cannot
produce a row. [../favourites.md](../favourites.md) names them.

## Consequences

- The living artist who never formally stopped and has quietly finished is still
  watched. Only the release dates can see that, and the radar currently fetches
  every one and discards it into a bare id list — recorded in
  [../../todo.md](../../todo.md).
- `ended` is written into a file that is generated but hand-edited, so a rerun
  must not clobber the hand edits — which is why that file is one of the few
  un-ignored things in `data/`.
