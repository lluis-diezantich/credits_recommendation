# D38: A scene is credits or co-listening, with genre as a veto and never a link

- **Status:** Accepted
- **Date:** 2026-10-24
- **Where it lives:** [`core/scenes.py`](../../core/scenes.py) (`sessions`,
  `lift`, `group_links`), [`policy.py`](../../policy.py)
  (`SCENE_SESSION_GAP`, `SCENE_LIFT_FLOOR`, `SCENE_MIN_SESSIONS`,
  `SCENE_BROAD_GENRE_SHARE`, `broad_genres`, `scene_link`),
  [`core/musicbrainz.py`](../../core/musicbrainz.py) (`genres`),
  the `artist_genres` table and `seeds.mbid` in
  [`stages/load.py`](../../stages/load.py),
  [`stages/rank.py`](../../stages/rank.py) (`scene_links`)

Extends [D37](D37-one-list-per-scene.md), which decided the output shape. This
decides how a scene is found. D37's conclusion stands; only its grouping rule
is replaced.

## Context

D37 grouped seeds on shared co-artists alone and produced **12 scenes, 10 of
them a single seed** — so for most of the output "per scene" meant "per seed",
which is not a grouping. The complaint was immediate and correct.

The cause is not a badly chosen floor. The credit graph can only group seeds
that *work with the same people*, and the salsa seeds do not: El Gran Combo
and Sonora Ponceña share no co-artist with any other seed. Only 2 of 190 seed
pairs clear D37's floor of 4, and almost every other pair shares exactly one
person, which is noise. **There is no cut in that distribution to find** —
lowering the floor to 2 chains 11 seeds into one scene through a single Björk
remix.

## Options

1. **Size-normalised credit overlap** (Jaccard, overlap coefficient). Rejected
   on measurement: the values run smoothly from 0.39 down to 0.03 with no gap,
   so every threshold is arbitrary and the one-shared-person noise is still
   there.
2. **Co-listening.** Two seeds are close if you play them in the same
   sessions. Works where credits cannot, and the data is already here — 190k
   listens with timestamps. Alone it links by listening habit: Little Simz
   (UK rap) joined Latin urbano through Bomba Estéreo and CHUWI.
3. **MusicBrainz genre as a third link.** Rejected on measurement, and this is
   the one worth recording: it put **18 of the 20 seeds in a single scene**.
   The tags are user-voted and mostly broad, so Björk reached Willie Colón
   through "jazz" and "pop", and transitivity did the rest.
4. **Genre as a veto on a co-listening link.** A shared tag can only confirm a
   link, never create one, so it cannot chain.

## Decision

Options 2 and 4 together, with D37's credit floor kept as the first test:

    link if shared co-artists >= 4
    or if shared sessions >= 10 and lift >= 3.0 and a non-broad genre in common

A **credit link is never vetoed.** Two artists who worked with the same five
people are connected whatever a tag says, and most of these artists carry one
or two votes per genre — too thin to overrule a measurement.

Lift rather than raw co-occurrence: Bad Bunny is in 551 of 3,177 seed
sessions, so a raw count called him close to every seed.

"Broad" is computed as a share of the seeds, not kept as a hand list, because
the right answer moves as seeds are added.

## Evidence

Measured 2026-10-24 over 20 seeds, 14,109 listening sessions (3,177 holding a
seed), and 97 MusicBrainz genre rows.

| grouping | scenes | single-seed |
|---|---|---|
| credits only (D37) | 12 | 10 |
| credits + co-listening | 7 | 5 |
| credits + co-listening + genre as a **link** | 3 | 2 — and meaningless |
| **credits + co-listening, genre as a veto** | **10** | **8** |

The chosen rule has *more* single-seed scenes than option 2 alone, and is
still the right one: the two scenes it produces are coherent, and the three
seeds the veto removed were shuffle adjacency rather than a scene. A scene
that mixes Little Simz with Karol G produces a list whose candidates are not
comparable, which is the disease D37 exists to cure.

**What co-listening found that credits could not** — the salsa scene, six
seeds, none of which the credit graph could group:

| pair | lift | shared co-artists |
|---|---|---|
| Héctor Lavoe / Sonora Ponceña | 7.4 | 0 |
| Rubén Blades / Sonora Ponceña | 7.1 | 0 |
| Celia Cruz / Sonora Ponceña | 6.5 | 1 |
| El Gran Combo / Sonora Ponceña | 6.3 | 0 |

The salsa list went from 77 candidates to 85, and from four seeds to six.

**`SCENE_BROAD_GENRE_SHARE = 1/2`**, which matters more than it looks. The
distribution has a gap — "latin" is held by 13 of 20 seeds (0.65), the next
tag is "salsa" at 6 (0.30), nothing between — so both 1/3 and 1/2 exclude
exactly "latin" today. 1/2 is chosen because at 1/3 the ceiling is 6.7 and
**one more salsa seed would make "salsa" broad and dissolve the salsa scene**,
whose links that tag confirms. At 1/2 it would take eleven.

**The floors are not independently measured.** `SCENE_LIFT_FLOOR = 3.0` and
`SCENE_MIN_SESSIONS = 10` were read off one distribution and chosen to
separate the salsa pairs (3.4–7.4) from the shuffle pairs (2.0–2.9). That is a
gap, not a validation, and it is one dataset.

## Consequences

- **Two coherent scenes covering 12 of 20 seeds**, each with a list worth
  reading, and the scene reasons printed so a wrong grouping can be seen.
- **Eight seeds still group with nobody**, including Björk, Drexler, Nathy
  Peluso and Little Simz. The output puts them after the real scenes rather
  than hiding them: an isolated seed is a fact worth seeing before 50 requests
  are spent on another one.
- **Jorge Drexler cannot be grouped by this method at all**, and it is
  structural rather than a tuning problem: he is in 917 of 3,177 seed sessions
  (29%), so nothing co-occurs with him more than chance predicts. The most
  played seed is invisible to lift. [../../todo.md](../../todo.md) has it.
- **Two seeds have no genre at all** (Nathy Peluso, CHUWI), so no co-listening
  link of theirs can ever be confirmed. They can only be grouped by credits.
- **It reads the listening history, so `rank.py` now depends on the export
  being loaded.** `--no-listens` leaves `listens` empty, every lift is 0, and
  the grouping silently falls back to credits alone. Stated here because the
  failure is quiet.
- **This is the project's first use of listening data to shape the OUTPUT
  rather than to measure it**, and the line it does not cross is worth naming:
  listening decides which lists are drawn, credits still decide who is in
  them. Ranking candidates by taste similarity is what
  [D31](D31-the-baseline-is-the-opponent.md)'s opponent already does, and
  doing it here would dissolve the question `roadmap.md` asks.
- **What would reopen it:** a seed set where the scenes are not two. The floors
  were fitted to this one, and the honest test is whether they still separate
  anything after the next four walks.
