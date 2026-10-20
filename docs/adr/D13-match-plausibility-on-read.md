# D13: A shaky name match is penalised on read, not dropped

- **Status:** Accepted
- **Date:** 2026-10-18
- **Where it lives:** `MATCH_PENALTY`, `match_confidence`, `ranked_score` in
  [`policy.py`](../../policy.py); the shortlist query in [../store.md](../store.md)

## Context

`build_pool` in `stages/resolve_discogs.py` takes a collaborator name off a
Discogs credit row and exact-matches it in Qobuz. "Cooper" exact-matches a real
Qobuz artist — just not the right one — and that artist's whole discography
enters the pool. `find_artist` refuses *fuzzy* matches precisely to avoid this,
but an exact match on one common token is indistinguishable from a correct one
at that layer: the name is all the evidence there is.

Worse than the volume is the score. `sig_score` is computed entirely from the
referrer — role weight × selectivity × how embedded that person is in the seed's
catalogue — and says nothing about whether the person was matched to the right
artist. So a shaky resolve inherits a strong referrer's weight and the junk is
not merely present, it is ranked first.

## Options

1. **Drop every flagged row**: 47% of the pool gone, including the real
   collaborators who happen to have a one-word name.
2. **Penalise on read**: the row keeps its provenance and loses its place in the
   order; the committed pools are not rewritten.
3. **Fold plausibility into the stored `sig_score`**: the right fix, and it costs
   a full regeneration of both pools.

## Decision

Option 2, with option 3 named as the better fix deferred. A penalty rather than
a drop because the flag is suspicion, never proof — the same stance as
`COVERS_MILL_HINTS` ([D5](D5-flag-rather-than-reclassify.md)).

`MATCH_PENALTY` is 0.1, multiplicative, and an unknown flag is 1.0 so that
adding a flag cannot change an order by accident.

## Evidence

Measured 2026-10-17/18 on the committed pools: `single_token_name` flags 3,673
of 7,860 rows (47%), and the top six contributors are 1,887 rows (24% of the
pool). "Morgan" carries 323 rows at 1.00, the maximum. Henry Mancini carries 459
rows — the *Peter Gunn* soundtracks, 1958-60 — reached through a Spanish engineer
who worked on Drexler records and not on Peter Gunn.

0.1 puts the worst flagged row (1.00) below the best clean one (0.80) without
deleting anything, so a strong flagged match still outranks a weak clean one.

## Consequences

- The penalty exists in `policy.py` and in the `docs/store.md` query, and
  **nothing in the pipeline calls it yet** — the stored score is unchanged, so
  any consumer that reads `sig_score` directly still ranks the collisions first.
- Name collisions are not only single-token: "Alex Cooper", "Sexy Sadie" and
  "Solid Ice" all escape the flag and return electronic pop. The flag is a
  subset of the problem.
- A ranker stays deferred. Ordering a list whose top is wrong makes the
  wrongness more prominent; filtering comes first.
- The free filters that take 7,860 rows to 148 — musician/producer referrals,
  side credits, Qobuz-native — are measured and still not written down in code.
