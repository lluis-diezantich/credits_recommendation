# D39: A seed is ordered by the scene it would join, and the scene is predictable before the walk

- **Status:** Accepted
- **Date:** 2026-10-24
- **Where it lives:** [`stages/seeds.py`](../../stages/seeds.py)
  (`scene_of_seeds`, `scene_for`, `known_genres`, the sort in `candidates`),
  [`core/scenes.py`](../../core/scenes.py) (`linked_pairs`, `joins`),
  [`core/musicbrainz.py`](../../core/musicbrainz.py) (`genres`)

## Context

[D38](D38-scenes-from-credits-listening-and-a-genre-veto.md) grouped the seeds
into two scenes and left **eight of twenty standing alone**. Each isolated
seed produces its own ranked list of 2–20 candidates, which is a list nobody
reads.

[D26](D26-seeds-by-rule.md) picks seeds on months played and lifetime plays,
and orders them by whether the candidate is already a co-artist of a walked
seed. Neither knows about scenes, so the rule that chose the eight isolated
seeds will keep choosing more of them: of the 11 remaining candidates, D26's
order led with Ca7riel, whose nearest scene is nothing.

The asymmetry that makes this worth fixing: **another isolated seed buys a
list of its own, while a seed that joins an existing scene buys range in a
list that already has 85 rows in it.**

## Options

1. **Add "joins a scene" to `policy.seedable`.** Rejected for D26's own
   reason: a rule that only admits seeds near the existing graph grows the
   corpus along links it already knows, which is the opposite of discovery.
   The rule stays about whether an artist is worth 50 requests.
2. **Order by the scene it would join.** The same stance D26 took for
   intersections — the rule says who is worth walking, the order says which
   50 requests to spend first.

## Decision

Option 2, ranked **above** `intersects`, because a co-artist of a walked seed
is one row and a scene is a whole list.

The scene is predicted with D38's rule minus its credit term: a candidate has
not been walked, so it has no credit graph, but co-listening and the genre
veto need no requests at all. `core.scenes.joins` asks the same
`policy.scene_link` of a candidate that `linked_pairs` asks of a seed, so
there is one rule rather than two that drift. Largest scene wins when a
candidate would join two.

Genres are the one thing a candidate may be missing, and this stage is
offline, so `--fetch-genres` is an explicit opt-in: one MusicBrainz request
per candidate the store has no genre for. Without it a candidate's genres are
empty, which means the veto can never confirm its links, and the stage says so
on stderr rather than silently reporting "new cluster".

## Evidence

Measured 2026-10-24 over 11 unwalked candidates, after 11 genre requests.

| candidate | joins | why |
|---|---|---|
| Calle 13 | Bad Bunny | played together 32.9× chance (hip hop) with Residente |
| Doechii | Bad Bunny | 18.1× (hip hop/pop rap) with Residente |
| Massive Attack | Little Simz | 17.3× (hip hop) with Little Simz |

3 of 11, and the first is a check on the method rather than a recommendation:
**Calle 13 is Residente's own band**, which the co-listening signal found at
32.9× chance without being told. The other eight are ordered as before.

**Two bugs this exposed, both mine, both silent:**

1. **The session denominator moved with the question.** `sessions()` counted
   only sessions holding a wanted key, so adding 11 candidates took the total
   from 3,177 to 14,109, multiplied every lift by 4.4 and changed which SEEDS
   were one scene. Fixed by counting every session, which makes lift a
   property of the pair. `SCENE_LIFT_FLOOR` moved 3.0 → 14.0 to keep the same
   cut (3.0 × 4.44 = 13.3), and the grouping is unchanged: 10 scenes before
   and after.
2. **Candidates had no sessions at all** in the first version, because they
   were left out of the key set entirely. Every one reported "new cluster",
   which is what the old order said anyway, so nothing looked wrong.

Both failed by agreeing with the previous behaviour, which is the failure mode
to expect here and the reason the stage now prints the lift and the tag behind
every claim.

## Consequences

- **The next three walks deepen two lists instead of starting three**, and the
  reason is printed, so a wrong grouping is arguable rather than hidden.
- **`policy.seedable` is unchanged**, so no artist became walkable or stopped
  being walkable. Only the order moved, which is what D26 reserved the order
  for.
- **`--fetch-genres` makes an offline stage conditionally online.** Stated in
  the docstring rather than hidden behind a default, the same shape
  `favourites.py --check-matches` has.
- **Three candidates have no MusicBrainz genre at all**, so no co-listening
  link of theirs can ever be confirmed and they can only ever read as a new
  cluster. Genres are user-voted; asking again will not fix it.
- **Óscar D'León — a salsa artist, with the salsa scene sitting right there —
  reads as a new cluster, and that is a different bug.** His listens are keyed
  `oscar d'leon` and his profile name keys to `oscar dleon`, because
  `core.names.normalise` drops a typographic apostrophe and keeps a straight
  one. Four artists lose their play history this way. Not fixed here because
  it changes the project's identity model (D25) and deserves its own decision
  — [../../todo.md](../../todo.md) has the measurement.
- **What would reopen it:** the scene prediction being wrong about a walk.
  After Calle 13 is walked, whether it actually lands in the urbano scene by
  credits is a check on this whole method, and the first one available.
