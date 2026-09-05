# The recommendation this project could not have made

One worked example, reverse-engineered. It names three rows of the mechanism
table in the README at once: freshness, implicit-feedback confidence, and item
cold-start.

## What happened

Spotify Release Radar surfaced Disco Bahía
(`850c8ef9-9359-46bf-ace9-35e7ad3a916a`) on 2026-09-04, triggered by the single
`Antesala`, released 2026-08-29.

## The path

Reconstructed from Deezer's related-artists graph and MusicBrainz:

    Daniel, Me Estás Matando  1,040 plays, 2022-05 → 2026-02  the anchor
      Ramona                      3 plays, 2024               reciprocal edge to the anchor;
                                                              9 of 20 neighbours shared with Disco Bahía
      Little Jesus                1 play,  2025-12            direct neighbour of Disco Bahía

Ramona is the pivot: it is #2 in the anchor's related list and the anchor is #7
in Ramona's, and it shares nine of twenty neighbours with Disco Bahía - Bandalos
Chinos, Daniela Spalla, Dromedarios Mágicos, Esteman, Little Jesus, Molinette
Cinema, Surfistas Del Sistema, Technicolor Fabrics, Young Tender. Identity
checked: the three Ramona plays are `Amargura` and `Tristes Ojos`, both on Deezer
artist 186726, so it is that Ramona and not a namesake.

## What each source knew

Only Deezer carried anything usable.

| source | what it had |
|---|---|
| Deezer | the whole neighbourhood, plus `nb_fan` 573 and the 2026-08-29 single |
| MusicBrainz | a stub - no area, tags, genres, country or member relations; three streaming URLs; newest release group 2025-09-26, eleven months stale |
| ListenBrainz popularity | 613 listens across 117 users |
| ListenBrainz labs `similar-artists` | `[]` |
| the credits pool | nothing - all 16 neighbourhood names checked against `releases`, `release_artists`, `people` and `via_name` |

The credits pool misses because the Drexler session-musician network and
self-produced Latin American indie are disjoint components. That is a
reachability boundary, not a scoring failure.

## Why it is worth keeping

**Freshness.** The trigger release is invisible to every source here except
Deezer, and `radars/` collect releases without joining them to taste.

**Implicit-feedback confidence.** The two artists that make the path short hold
four plays between them. `MIN_PLAYS = 50` deletes both and keeps the 1,040-play
anchor, which on its own leads nowhere.

**Item cold-start.** At 573 Deezer fans there is almost nothing for a ranker to
work with, so no amount of ranking would have helped.

## Caveat

This reconstructs the structure the recommendation must have followed, using
Deezer's collaborative filtering as an independent view of the same co-listening
data. It is not Spotify's own computation, which is not visible from outside.
