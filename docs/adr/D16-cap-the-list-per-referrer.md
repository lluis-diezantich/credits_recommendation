# D16: The shortlist keeps at most two rows per referrer

- **Status:** Accepted
- **Date:** 2026-10-20
- **Where it lives:** `MAX_PER_REFERRER` and `cap_per_referrer` in
  [`policy.py`](../../policy.py); the `capped` CTE in [../store.md](../store.md)

## Context

[D15](D15-filters-before-ranking.md) left 291 rows, and 212 once unheard,
streamable and since-2015 are asked for as well. They arrive through only 24
people, and the order is by how strong the referring credit was — so the top of
the list was nine Juan Campodónico records. A list like that tests one producer
rather than the graph, which is the opposite of what a credits-based recommender
is for.

## Options

1. **Leave it to the ranker**: a diversity term inside the score. Changes every
   row's score to fix a property of the list, and there is no ranker yet.
2. **Cap the rows per referrer** after ordering: a rule about the list, so no
   score changes and nothing is reordered.
3. **Nothing** — read the list and skip the repeats by eye: free, and it wastes
   the top of the only output a person actually reads.

## Decision

Option 2, at two rows per referrer, keyed on `via_name`.

## Evidence

Measured 2026-10-20 over the 212:

| cap | rows | distinct people in the top 20 |
|---|---|---|
| 1 | 24 | 20 |
| 2 | **38** | **12** |
| 3 | 52 | 8 |
| 5 | 80 | 7 |

2 is where the top of the list stops being one person without flattening it to
one row each. At 1 the strongest referral and the second strongest become
indistinguishable, which discards what the score is for; by 3 a single producer
is a third of the first ten again.

**The key is `via_name`, not `via_through`.** Both `todo.md` and `docs/store.md`
said to cap per `via_through`, and that column is NULL on all 1,470 Qobuz-path
rows — it records which of the SEED's people made the referral and only the
Discogs path writes it. Capping on it would have put the entire shortlist in one
group and left two rows in total. A test pins this.

## Consequences

- The cap is applied by whoever renders a list, which today is the query in
  [../store.md](../store.md). Nothing in the pipeline applies it, because
  nothing in the pipeline produces a list yet.
- Stated twice, like D15's filters: `policy.cap_per_referrer` and a
  `ROW_NUMBER() OVER (PARTITION BY via_name)` window. The predicate is
  authoritative.
- A dropped row is dropped from the *view* only. Raising the cap brings it back
  with no refetch and no rebuild.
- It makes the list look more diverse than the graph is. 24 referrers for 212
  rows is the real number, and the cap hides the concentration rather than
  fixing it — what would fix it is more seeds, or the Discogs path repaired
  instead of excluded ([D15](D15-filters-before-ranking.md)).
- Per-referrer is not per-artist: two rows from one referrer can still be two
  records by the same credited artist, since `via_name` is the catalogue they
  came out of and not who they are by.
