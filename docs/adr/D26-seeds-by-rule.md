# D26: A seed is chosen by rule from the profile, and walked in the order that feeds the ranker first

- **Status:** Accepted
- **Date:** 2026-10-22
- **Where it lives:** `policy.seedable`, `SEED_RECENT_FLOOR` and
  `SEED_PLAYS_FLOOR`; `stages/seeds.py`.

## Context

[D22](D22-co-appearance-is-the-second-pipeline.md) made more seeds the point of
the co-appearance pipeline, and the three identity fixes that blocked it are
done (D23, D24, D25). The next ~400 requests go on seeds 5–12, and the four
already walked were picked by hand.

Hand-picking has already cost something measurable. Measured 2026-10-22 over
the store: of 99 co-artists across the four seeds, **97 connect to exactly one
seed**. The only two that connect to two are Lau Noah and Salvador Sobral, both
on Drexler and Pérez Cruz, both already played. Little Simz and Björk intersect
with nothing — not with each other, not with the Iberian pair.

That is the column a cross-seed ranker is built on: *how many of your artists
made a record with this person*. It is 1 for 97 of 99 rows, so step 3 of
`todo.md` has nothing to rank, and adding two more hand-picked seeds could
easily leave it that way.

## Options

1. **Keep picking by hand**, now informed by the intersection measurement.
   No new numbers to defend. But the rule for "worth 50 requests" stays in
   somebody's head, which is what D1 exists to prevent, and it is how two of
   four seeds ended up isolated.
2. **`core` band plus a recent-months floor**, which is what `todo.md`
   proposed. Reuses `band()` untouched.
3. **`core`, or `emerging` with a lifetime-plays floor**, plus the same
   recent-months floor.
4. **Fold the intersection test into the rule** — prefer artists already seen
   as a co-artist, so every new seed is guaranteed to connect.

## Decision

**Option 3 for the rule, and option 4 as the walk ORDER rather than the rule.**

`policy.seedable(band, recent, plays)` is two tests: at least
`SEED_RECENT_FLOOR` of `RECENT_WINDOW`'s 24 months, and then either `core` or
`emerging` with at least `SEED_PLAYS_FLOOR` lifetime plays. `lapsed` never
qualifies.

Option 2 was rejected on one case: **it does not select Little Simz**, who is
`emerging` only because 21 lifetime months is three short of `DEEP_FLOOR`, and
who is the seed that proved the method generalises outside the Iberian cluster.
A rule that excludes her excludes everyone like her — played constantly, short
history. `todo.md` has said since the profile was built that `emerging` needs a
floor nobody has set; this is that floor, at seed scale. It is a different
question from `EMERGING_PLAYS`, which asks whether an artist is worth watching
for new releases; this one asks whether a discography is worth 50 requests.

Option 4 stays out of the rule because a rule that only picks artists already
in the graph grows the corpus along links it already knows, which is the
opposite of discovery. As an ordering it costs nothing and buys a lot:
`stages/seeds.py` sorts the five guaranteed intersections first, so the ranker
gets a column with range after two or three walks instead of after eight, and
the ranking can be tested before the remaining requests are spent.

## Evidence

**The month floor is 17, validated against the seeds already walked.** Measured
2026-10-22 over `data/profile.json`'s 265 artists:

| floor | of the 4 walked seeds it selects |
| --- | --- |
| 18 | 3 — misses Sílvia Pérez Cruz |
| **17** | **4** |

Pérez Cruz sits at exactly 17/24, and her walk produced the 40%
already-played rate and the 16 unheard names that D14 and D22 rest on. A floor
that excludes a seed already known to be good is one month too high. Months
rather than plays is D9's argument: a month says you came back, a play count
says you had it on.

**The plays floor is 500, and the gap around it is real.** Of the 24 `emerging`
artists above the month floor, it keeps 7 and cuts 17:

| | |
| --- | --- |
| kept | 526 (KAROL G) to 4,356 (Bad Bunny), including Little Simz at 1,327 |
| cut | 104 to 389 (Frankie Ruiz) |

The nearest values either side are 389 and 526, so any floor in (389, 526]
selects the same seven; 500 is the round number inside it. Same stance as
`OWN_ALBUM_MAIN_SHARE` — the value is stated as untested within the gap rather
than implied to be precise.

**What the rule selects now:** 31 artists, 4 of them already walked, **27 to
go, 5 of which are guaranteed intersections** (ROSALÍA, Natalia Lafourcade,
Residente, C. Tangana, Rubén Blades). The pool is two tight clusters — salsa
(El Gran Combo, Celia Cruz, Willie Colón, Sonora Ponceña, Oscar D'León, Héctor
Lavoe) and contemporary Latin (Nathy Peluso, Kali Uchis, ROSALÍA, Ca7riel, Paco
Amoroso, C. Tangana) — which is where intersections should come from, since the
two seeds that intersect today are the two in one scene.

## Consequences

`./stages/seeds.py --next 8` prints the eight `discover.py` commands and the
cost, and ends by naming the step between a walk and a ranking that must not be
skipped: read the alias report and add to `data/aliases.json` (D25).

The rule is 27 candidates deep, which is more than the 6–8 planned. That is
deliberate: the rule says who is *worth* 50 requests and the order says which
50 to spend first, so the pool can outlast this round of walks.

What this does not do:

- **It does not decide when to stop.** Nothing measures whether seed 9 earned
  its requests, because nothing logs what was shown — `todo.md` step 5, and the
  reason every weight in step 3 is still guesswork.
- **It inherits the profile's defects.** `data/profile.json` is from 2026-10-18
  and is regenerated by hand, so the counts age. It also splits identities the
  alias map would merge: "Frankie Ruiz" and "Frankie Ruiz y su Orquesta" are
  two rows at 389 and 384 plays, and either might clear 500 merged. D25's map
  applies to credits, not to the profile.
- **It says nothing about a non-Latin cluster.** Walking the five
  intersections and then down the recent-months list keeps the corpus inside
  two scenes. Björk and Little Simz are the only seeds outside them, and they
  are the two that intersect with nothing — which is the finding, not a flaw in
  the rule.

What would reopen it: the first ranked list. If the intersection column still
has no range after the five guaranteed ones, the rule is selecting the wrong
axis and the thing to vary is the scene rather than the month count.
