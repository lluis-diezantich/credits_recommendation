# D23: Ask MusicBrainz which names the seed is credited under, and fold editions by title

- **Status:** Accepted
- **Date:** 2026-10-20
- **Where it lives:** `musicbrainz.names` in
  [`core/musicbrainz.py`](../../core/musicbrainz.py), `favourites.mbid_for`,
  `seed_names` and `fold_editions` in
  [`stages/discover.py`](../../stages/discover.py)

## Context

Two of the three defects the [D22](D22-co-appearance-is-the-second-pipeline.md)
probe found, both of which corrupt every count the ranker would use:

- **The seed is credited under a legal name.** `discover.py` dropped
  `normalise(seed_name)` only, so "Björk Guðmundsdóttir" — 120 of her 148 own
  albums — was the biggest collaborator in Björk's own graph, and "Simbiatu
  Ajikawo" held 20 of Little Simz's 44.
- **Editions inflate co-appearance counts.** "WE PRAY" is one Coldplay single
  stored as five album ids, so four artists each scored five co-appearances off
  one song. Björk: 141 ids for 99 titles.

## Options

For the seed's names:

1. **A share threshold** — "whoever holds most of the seed's catalogue is the
   seed". **Measured and rejected:** Björk's legal name holds 81% and the next
   person 17%, which looks decisive, but Little Simz's holds 45% against a real
   producer at 42%. Three points is not a threshold, and the producer is Carles
   Campi Campón on the Drexler seed, so the rule would have deleted a genuine
   collaborator.
2. **Require `MainArtist`** — "the seed is billed, a collaborator is not".
   **Measured and rejected:** neither legal name holds MainArtist at all. Both
   are filed as Composer, which is also how Sjón and Inflo are filed.
3. **Substring matching** — "Björk Guðmundsdóttir" contains "Björk". Catches
   Björk, misses Simbiatu Ajikawo entirely, and `find_artist` refuses fuzzy
   matching for exactly this reason.
4. **Ask MusicBrainz**, which records both aliases and `is person`
   relationships.

For editions: fold on a release-group id (Qobuz returns none here), on title,
or leave them.

## Decision

Option 4, the same stance as [D10](D10-ask-musicbrainz-who-stopped.md) took for
dormancy: ask the source that records the fact rather than inferring it from
behaviour. One request per seed, cached, with the mbid coming off
`data/favourites.json`, which already carries one per artist.

Aliases alone are not enough — Little Simz has no alias for her legal name and
is linked to it by an `is person` relationship — so `names()` reads the
aliases, the sort-name and the far side of that relationship, all on the one
request.

Editions fold on `normalise(title)`, coarsely and on purpose.

## Evidence

| | before | after |
|---|---|---|
| top of Björk's own crew graph | **Björk Guðmundsdóttir** (120 alb) | Nellee Hooper (25 alb) |
| people in Björk's graph | 149 | 147 |
| people in Little Simz's graph | 181 | 180 |
| Coldplay, Burna Boy, Elyanna, tINI co-appearances with Simz | 5 each | **1 each** |
| Obongjayar, who really made two | 2 | 2 |

Names MusicBrainz supplied: Björk 3 credited spellings dropped, Little Simz 2,
Pérez Cruz 4 (accent variants), Drexler 1 — he is credited under his performing
name, which is why none of this showed in the first two seeds.

## Consequences

- **A spelling nobody recorded still survives.** "Simbiatu Abisola Abiola
  Ajikawo" (5 albums) and "Simbi Ajikawo" (4) are in no MusicBrainz field, so 9
  of Simz's 29 self-credits remain in her graph. `discover.py` prints a CHECK
  line when the top person holds half the seed's catalogue, which catches a
  Björk-sized residue and not a 5-album one. The honest position is that this
  is reduced, not solved, and the fix is an edit at MusicBrainz.
- **Collaborator aliases are NOT fixed.** Sjón is still four people, Arca two,
  Inflo two. The same lookup would resolve them at one request *per person* —
  180 to 287 people per seed — so it needs a budget decision and a target
  (the top N by albums) rather than a blanket fetch. Open in
  [../../todo.md](../../todo.md).
- **Folding by title merges genuine reissues.** "Granada" appears twice in the
  Pérez Cruz corpus with 15 and 21 tracks. For counting who someone made
  records with, those are one record; for anything that needs the track list,
  they are not, and this function is used only for the former.
- `ARTIST_URL` now requests `inc=aliases+artist-rels`. Entries cached before
  this lack both, and `ended()` still reads them, because life-span is in both
  shapes.
- `album_billing` takes a SET of seed keys, not one. A record billed to a legal
  name is the seed's own record, and reading only the performing name filed it
  as a guest spot.
