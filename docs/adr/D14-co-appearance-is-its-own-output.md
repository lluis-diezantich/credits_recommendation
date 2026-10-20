# D14: An album in the seed's discography is labelled own or guest, and co-appearance is its own output

- **Status:** Accepted
- **Date:** 2026-10-20
- **Where it lives:** `core.credits.main_artists`, `policy.album_provenance` and
  `OWN_ALBUM_MAIN_SHARE`, `discover.album_billing`, the `co_artists` block in
  `data/discovery_*.json`, [`tests/test_discover.py`](../../tests/test_discover.py)

## Context

Qobuz files a guest spot inside the GUEST's own discography, so `artist/get` on
a seed returns records the seed did not make. `stages/discover.py` walked all of
them and credited everyone aboard as having worked on the seed's records — the
relationship inverted: they did not make his record, he sang on theirs.

The two rows that read as the best recommendations out of the Drexler graph, Lau
Noah and Salvador Sobral, arrived exactly that way: not as crew, but as the
artists he made a record with.

## Options

1. **Read the titles**: free, and it catches a third of the cases — only 5 of
   the 15 guest albums say "feat.".
2. **Drop the guest albums** from discovery: removes the wrong credits, and
   throws away the best signal in the file along with them.
3. **Label each album own or guest from the billing, and emit co-appearance as
   its own output**: keeps every row, separates the two relationships, costs no
   requests because `cache/credits` already holds the per-track performers.

## Decision

Option 3. The test is who holds `MainArtist` across the album's tracks, as a
*share* rather than "is the seed billed anywhere on it", because a various-artists
compilation bills the seed on one track of twenty and is not the seed's record.

Attribution itself is unchanged: a guest album's crew stays in the graph, now
labelled. `stats.albums` still counts both, so every number already in
`discovery_*.json` is unchanged, with `own_albums`/`guest_albums` beside it.

## Evidence

Measured 2026-10-20 over `cache/credits` (107 albums, 500 tracks), no requests.

| | Drexler | Pérez Cruz |
|---|---|---|
| albums walked | 62 | 44 |
| not the seed's record | 15 | 3 |
| of those, "feat." in the title | 5 | 0 |

Hit rate against real listening (7,357 distinct `listens.artist_key`):

| | Drexler | Pérez Cruz |
|---|---|---|
| MainArtist of a guest album | 10/15 (67%) | 0/3 |
| co-MainArtist on an own album | 13/23 (57%) | 12/28 (43%) |
| either — co-appearance | 22/37 (59%) | 12/30 (40%) |
| the crew graph, all credited people | 36/278 (13%) | 45/287 (16%) |

The second direction — guests billed *on* the seed's own records — was not in the
`todo.md` measurement and carries 23 and 28 more names at a comparable rate, so
`album_billing` returns it alongside the first.

`OWN_ALBUM_MAIN_SHARE` is 0.5 and its exact value is **untested**: across all 106
albums the seed holds `MainArtist` on every billed track or on none, never in
between, so any floor in (0, 1] labels them identically. A compilation is the
case that would tell two floors apart and there is not one yet.

Verified behaviour-preserving: both committed discovery files were rebuilt from
`cache/` alone and every person's roles, albums and stats are identical, with one
exception that is not caused by this change — `top_role` comes from
`Counter.most_common(1)`, so on a tie it depends on the order Qobuz returned the
discography (`luis eduardo aute`, three roles at 1 each; `juan falu`, four at 13).

## Consequences

- `resolve_qobuz.signal_for` still counts guest albums in `person_seed_albums`,
  so a referrer's weight is still inflated by the leak. Fixing it changes stored
  scores and needs a pool regeneration, same bill as
  [D13](D13-match-plausibility-on-read.md)'s option 3 — one entry in
  [../../todo.md](../../todo.md), to be paid once.
- `stages/load.py` has no column for `provenance`, `own_albums` or `co_artists`,
  so none of this is queryable from `data/music.db` yet.
- The co-artist list inherits the name problem: "Colors" (from *A COLORS SHOW*)
  and "Penelope Cruz" are among Pérez Cruz's 28, so it needs the same
  plausibility stance before anything ranks it.
- `stages/discover.py` went from 0% to 23% coverage: the extracted decision is
  covered, the orchestration is not ([D2](D2-pure-core-dirty-edges.md)).
- Both corpora have `albums_unbilled: 0`, so the "unknown" branch is a guard with
  no instance today.
