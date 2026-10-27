# D37: The seeds are not independent, so the list is drawn per scene

- **Status:** Accepted
- **Date:** 2026-10-24
- **Where it lives:** [`core/scenes.py`](../../core/scenes.py),
  [`policy.py`](../../policy.py) (`SCENE_SHARED_FLOOR`),
  [`stages/rank.py`](../../stages/rank.py) (`--by-scene`, `scene_labels`,
  `show_by_scene`)

## Context

[D22](D22-co-appearance-is-the-second-pipeline.md) is this project's thesis:
a person several of your artists independently chose is better evidence than
one your favourite chose repeatedly. `breadth` implements it by counting seeds,
and [D30](D30-a-remix-is-not-a-collaboration.md) already corrected one way that
count lies (two seeds billed on one record corroborate once).

**The independence itself does not hold, and that is what this ADR is about.**
Measured 2026-10-24: the 20 seeds fall into two real scenes plus ten isolated
ones, and **2 of 380 unheard candidates connect to more than one scene**. So
"4 of your artists made a record with this person" is, 378 times in 380, four
artists from the same scene who record together constantly.

The scenes also hand out co-signs at wildly different rates — Bad Bunny has
116 co-artists, Björk 15, El Gran Combo 9 — so a seed count means a different
thing in each. The visible symptom: `breadth`'s top six were all reached
through Karol G and Bad Bunny, while Jorge Drexler, the most-played seed at
6,447 listens, produced one row in the top 25, and Karol G at 476 listens
produced sixteen.

Two attempts to fix this by weighting were measured and rejected — see
Evidence. The problem is not the weight on the count. It is that two counts
from different scenes were put in one ordering at all.

## Options

1. **Weight a seed's vote by `1/co-artists`.** Rejected on measurement: it
   discards corroboration outright. A single co-sign from El Gran Combo (9
   co-artists) outranks Ozuna's four seeds, and 7 of the top 11 become one
   seed's co-artists.
2. **The same on a log scale (IDF).** Modest and defensible — 17 of the top 25
   unchanged, Papo Lucca 8th → 2nd, eight reggaeton rows displaced — but
   Ozuna still leads and the scales are still mixed. Worth having later as a
   rival strategy; it is not this decision.
3. **Collapse a scene to one vote.** Corroboration becomes the number of
   distinct scenes. Rejected: it makes almost every candidate a 1, because
   only 2 rows span scenes. It deletes the signal rather than rescaling it.
4. **One ranked list per scene.** Changes the shape of the output rather than
   the arithmetic. Costs nothing — the grouping is a `GROUP BY` over data
   already in the store — and no comparison is made that the data cannot
   support.

## Decision

Option 4. `./stages/rank.py --by-scene` prints one ranked list per scene,
largest first, each ordered by whichever strategy was asked for.

Separate lists and not one list with a scene column, which was the tempting
middle: a column invites exactly the cross-scene comparison this exists to
stop. The strategies are untouched, so every logged `breadth` run stays
comparable ([D29](D29-strategies-are-hypotheses-and-the-log-judges-them.md)).

A candidate who reaches two scenes appears in both lists, and the run prints
them by name at the end. Those rows are the only direct evidence D22's thesis
has, so they are named rather than counted.

## Evidence

Measured 2026-10-24 over 20 seeds and 380 unheard candidates, offline.

**The scenes, at `SCENE_SHARED_FLOOR = 4`:**

| scene | seeds | co-signs handed out |
|---|---|---|
| Bad Bunny | + C. Tangana, Kali Uchis, Karol G, ROSALÍA, Residente | 116 for Bad Bunny alone |
| Celia Cruz | + Héctor Lavoe, Rubén Blades, Willie Colón | 66 |
| ten isolates | Björk, Little Simz, Drexler, Lafourcade, Pérez Cruz, Sonora Ponceña, El Gran Combo, Bomba Estéreo, CHUWI, Nathy Peluso | 9–38 |

**Candidates by how many scenes they reach: 378 reach one, 2 reach two.** The
two are Papo Lucca (Sonora Ponceña + Celia Cruz) and Reykon (Willie Colón +
Karol G). Conociendo Rusia becomes a third at this floor, through Nathy Peluso
and Drexler being separate scenes.

**The floor, chosen by what each value does to the grouping.** Linkage is
transitive, so this number decides whether a chain swallows everything:

| floor | result |
|---|---|
| 2 | one scene of 11 seeds — Björk joins Bad Bunny's via ROSALÍA, on one remix |
| 3 | Drexler + Lafourcade become a scene, Nathy Peluso joins urbano; salsa whole |
| **4** | both real scenes whole, no chain, 10 isolates |
| 5 | salsa breaks up: Celia Cruz and Rubén Blades fall out |

4 is the widest floor at which both scenes survive intact and the narrowest at
which nothing chains. 3 is the live alternative and moves two seeds; scenes are
derived, so trying it costs a rerun and no requests.

**What the weighting options scored**, for the record, because option 2 may
come back: inverse weighting left 7 of `breadth`'s top 25 in place, IDF left
17.

## Consequences

- **The salsa list is readable and was invisible before.** Yomo Toro, Papo
  Lucca and Johnny Pacheco y Su Charanga lead a 77-candidate scene that had
  three rows in the global top 25.
- **Nothing about the ranking changed**, so `data/shown.json` stays
  comparable. `--by-scene` is a view; `--log` still records the global order.
- **The seed count is still not a fair number WITHIN a scene.** Bad Bunny and
  Karol G share 21 co-artists, so two votes inside the urbano scene are still
  partly one. Option 2 is what addresses that, and it is now a smaller
  question asked inside a scene rather than across them.
- **It makes two data defects visible by giving them small lists to sit in**,
  both already in [../../todo.md](../../todo.md): the seeds reappear as their
  own candidates under variant names ("La Sonora Poncena" ranks 2nd in Sonora
  Ponceña's own scene, which is [D35](D35-the-seeds-own-band-is-its-own-reason.md)
  generalising past its hand list), and CHUWI's merged Qobuz id puts Henny
  Montana, from a Russian single, 2nd in a scene of two.
- **A scene of one or two candidates is noise**, and the output prints it
  anyway. No floor on scene size, because the sizes are what tell a reader
  which seeds are isolated — and an isolated seed is a fact worth seeing
  before spending 50 requests on another one.
- **What would reopen it:** cross-scene candidates arriving in numbers. If a
  later walk produces thirty rows spanning scenes rather than two, the global
  list is measuring something again and the per-scene split becomes a view
  rather than the main output.
