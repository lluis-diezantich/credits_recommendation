# D30: A remix is not a collaboration, and two seeds on one record corroborate once

- **Status:** Accepted
- **Date:** 2026-10-22
- **Where it lives:** `policy.remix_only`, `policy.why_not_a_co_artist`,
  `policy.rank_breadth`; `core.rank.features`'s `albums` and `corroboration`;
  the read-side filters in `stages/rank.py` and `stages/co_artists.py`.

## Context

The first thing [D29](D29-strategies-are-hypotheses-and-the-log-judges-them.md)'s
ranker put at the top of the list was wrong, in two independent ways, and both
were visible in one row:

```
1. Conrad Taylor   [2 | 3.41]
   via ROSALÍA, Björk
```

**His two seeds are one record.** ROSALÍA and Björk are both billed on
"Berghain (Remix)", so the same album counts under both of them and `seeds`
reads 2. D22's thesis is that several of your artists *chose* this person;
two artists who chose each other chose once. `breadth` leads on that number,
so the one row in the corpus where it is wrong was ranked first by it.

**And he is the remixer.** His only credit beyond the billing is `Re-Mixer`.
He reworked a finished record, plausibly without meeting either artist, and the
sentence the list printed about him — *"has made 2 records with 2 artists you
play"* — is false. [D27](D27-the-class-fallback-gets-rules.md) decided a
remixer passes `billed_as_musician` because they did touch the record, and that
stands: "worked on the same record" and "made a record together" are different
claims, and only the co-appearance list makes the second.

## Options

For the remix half:

1. **Drop a remix-only candidate** from the co-appearance list, the stance
   D24 and D27 took for a channel and an illustrator.
2. **Penalise it**, the stance [D13](D13-match-plausibility-on-read.md) took
   for a shaky name match: keep the row, let it lose its place.
3. **Treat the remix album as its own provenance**, a fourth value beside
   own/guest/compilation, and let each consumer decide.

For the corroboration half:

4. **Count distinct albums alongside seeds** and have `breadth` lead on the
   smaller of the two.
5. **Leave it**, since it is 1 row in 287 — and accept that the one row is
   ranked first.

## Decision

**Option 1 and option 4.**

`policy.remix_only(roles)` is true when a candidate holds roles beyond the
billing and every one of them is a remix credit. Dropped on read in both
`rank.py` and `co_artists.py`.

Dropped rather than penalised because **a penalty is right when the evidence is
weak, and here the claim is wrong**. No weight makes a false sentence true.
Option 3 was rejected as more machinery than the fact needs: a remix album is
not a different kind of record, it is a different kind of CREDIT, and the role
already says so.

`core.rank.features` gains `albums` — distinct shared records across all seeds —
and `corroboration`, the smaller of it and `seeds`, bounded by both because a
person cannot be corroborated by more artists than chose them nor by more
records than exist. `rank_breadth` leads on `corroboration` instead of `seeds`.

`policy.why_not_a_co_artist` now holds all three read-side filters in one
place, because the output had started reporting them as each other: a single
"dropped as not an artist" line was saying that about Gesaffelstein, who is one.

## Evidence

Measured 2026-10-22 over the ten-seed store:

| | |
| --- | --- |
| multi-seed candidates | 20 |
| ...whose seeds share fewer albums than seeds | **1** — Conrad Taylor, 2 seeds from 1 album |
| candidates with any role | 287 |
| ...holding nothing beyond billing but a remix | **3** — Conrad Taylor, Gesaffelstein, Joe Claussell |
| shared albums with "remix" in the title | 5 of 251 |

Both defects are tiny and sharply defined. The reason they matter is where they
landed: 1 of 287 rows and 3 of 287 rows, and one of them was the top
recommendation under the default strategy.

After: 165 candidates become 162, and the list leads with Conociendo Rusia on a
genuine two seeds and two records.

## Consequences

**The corroboration fix currently changes no order.** The only row it would
have demoted is dropped by the remix filter anyway, so it is an invariant held
against future seeds rather than a visible improvement today — and it is tested
on a constructed store rather than on the corpus, which is stated here because
`test_rank_stage.py` is the only place it can be seen working.

**The cost of dropping is named.** Gesaffelstein is a real artist reached only
by remixing, and he leaves the list. He returns the moment he plays on
something, and he stays in the crew graph throughout, which is where a remixer
belongs.

What this does not do:

- **It does not find the inverse case.** A seed who remixes somebody else's
  record is still a co-appearance in that person's favour, and nothing checks
  whether your artist's contribution was the remix. The same test on the seed's
  side would catch it.
- **It does not touch `albums` in `co_artists`.** That column still counts
  every record the two are printed on, per seed; `corroboration` is computed
  on read in the ranker. A per-seed consumer that wants the same correction
  has to make it itself.

What would reopen it: a remix that is a genuine collaboration — two artists
remixing each other's work back and forth is a real relationship, and this
drops both directions of it. If the corpus ever shows one, the role is not
enough and option 3's provenance becomes the better answer.
