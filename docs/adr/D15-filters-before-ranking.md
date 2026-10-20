# D15: The pool is filtered on read by three stored facts, before anything ranks it

- **Status:** Accepted
- **Date:** 2026-10-20
- **Where it lives:** the POOL FILTERS block, `REFERRAL_CLASSES`,
  `musical_referral` and `shortlisted` in [`policy.py`](../../policy.py);
  `via_referral_classes`, `via_is_first_artist` and `via_through_roles` in
  [`stages/load.py`](../../stages/load.py); the shortlist query in
  [../store.md](../store.md)

## Context

7,860 candidate releases, each with an explainable score, in no usable order.
[D13](D13-match-plausibility-on-read.md) stopped the name collisions being
ranked first, but it did not change what the pool CONTAINS, and three
measurements say most of it should not be in a list at all: 73% of the Discogs
pool's referrals arrive through mixing, 75% of all rows are the referring
person's own record rather than one they shaped, and the Discogs path is 81% of
the rows with every junk row traced to it.

`todo.md` had all three written down as "free and none is written down in code
yet" since 2026-10-18.

## Options

1. **Build the ranker and let the order sort it out:** ordering a list whose
   top is wrong makes the wrongness more prominent, which is the argument
   `todo.md` already made against it.
2. **Drop the rows when the pools are generated:** the smallest store, and a
   filter that turns out to be wrong costs a refetch — and the Discogs rows
   cost a 128-person fan-out to produce.
3. **Keep every row, store the facts the filters need, and filter in the
   query:** an excluded row stays queryable, a wrong filter costs a different
   WHERE clause, and the pools are never rewritten.

## Decision

Option 3, which is the same stance as [D13](D13-match-plausibility-on-read.md):
judgement applies on read, the stored row keeps its provenance.

`policy.shortlisted` is the predicate. Two facts had to reach the store for it
to be expressible in SQL at all — `via_is_first_artist`, which cannot be derived
in sqlite because the comparison is against `normalise()`, and
`via_referral_classes`. A third column, `via_through_roles`, was in
`pool_discogs.json` and in no column, so "which credit referred this" was
unanswerable from the store.

The composed verdict is **not** stored. It would go stale in the store the way
`sig_score` did, which is the defect D13 exists to work around.

## Evidence

Re-measured 2026-10-20 over `data/pool.json` and `data/pool_discogs.json`, no
requests, and reproduced in SQL against a rebuilt `data/music.db`:

| | rows |
|---|---|
| all | 7,860 |
| Qobuz-native (`source <> 'discogs'`) | 1,470 |
| side credits (not the first credited artist) | 1,998 |
| musician or producer referral | 2,778 |
| **all three** | **291** |
| of those, by artists never played | 220 |

**`todo.md`'s figure for this was 148, and it could not be reproduced.** Eight
compositions of the three filters were tried against the same two files, which
have not been regenerated since (2026-08-30 and 2026-09-02): the closest were
291 for the stated set and 161 for "production-referred only". The genres
`todo.md` reported for its top — Bolero, Classical — do not appear in the 291
either, so the difference is in the definition and not in the data. 291 is what
the predicate in `policy.py` yields, and it is now the number in both places.

Composition detail, measured rather than assumed: 815 rows mix a kept referral
class with a dropped one, every one of them on the Discogs path, so "any
qualifying role" and "all roles qualifying" return the same 291 today.

## Consequences

- **The Discogs path is excluded, not fixed.** 6,390 of the 7,860 rows are
  dropped by one clause, so the credits thesis currently rests on 1,470 rows
  from a 59-person fan-out. Fixing `build_pool`'s name matching is what would
  bring them back, and it is the open entry in
  [../../todo.md](../../todo.md).
- **Filtering does not escape the name problem.** 72 of the 291 carry
  `single_token_name` through five people, and "Mauro" alone contributes 42 —
  the Qobuz path resolves names through autosuggest too, so D13's penalty still
  has to apply inside the shortlist.
- **The predicate is stated twice**, once in `policy.py` and once as a WHERE
  clause in [../store.md](../store.md), because sqlite cannot call Python. The
  doc says which one is authoritative.
- **Nothing applies it automatically.** `resolve_qobuz.py` still writes every
  row, and no radar or report reads the shortlist — it is a query a person runs.
  That is the honest state: the pool is now readable, not yet consumed.
- **It does not diversify.** The 291 come through 30 people and the uncapped top
  is nine Juan Campodónico rows, so the list tests one producer rather than the
  graph. Capping per referrer is the next decision, and nothing makes it yet.
