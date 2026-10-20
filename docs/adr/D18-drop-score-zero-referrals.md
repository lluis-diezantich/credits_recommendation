# D18: A referral scoring zero is dropped, and the resolver stops fetching one

- **Status:** Accepted
- **Date:** 2026-10-20
- **Where it lives:** `carries_signal` and `seed_albums_of` in
  [`policy.py`](../../policy.py), folded into `shortlisted`; the `--min-albums`
  gate in [`stages/resolve_qobuz.py`](../../stages/resolve_qobuz.py); the
  `sig_score > 0` clause in [../store.md](../store.md)

## Context

[D17](D17-fold-plausibility-into-the-score.md)'s regeneration computed
`embedded` from the seed's OWN albums for the first time, and five of the Qobuz
pool's 50 referrers came out at score 0.0: Chab, Susana San José, El David
Aguilar, Ulises Hadjis, Çantamarta. Each passed `--min-albums 2` on two albums,
and both albums were records the seed *guested* on — so they worked on none of
his. They still contributed their whole discography to the pool: 175 rows.

That is not a weak referral. The relationship the pool asserts does not exist,
and D14 already has the right home for these people — discovery's `co_artists`
block, where an artist the seed made a record *with* belongs.

## Options

1. **Leave them at 0.0 and let the order bury them:** nothing to change, and
   175 rows sit in every count and every unfiltered query, including the
   7,860-style totals this project keeps quoting.
2. **Drop them on read**, with the stored rows untouched: immediate, consistent
   with D13/D15/D16, and the resolver keeps spending requests on them.
3. **Drop them on read AND stop resolving them**, by counting own albums in the
   `--min-albums` gate: also saves the requests, and takes effect only on the
   next run.

## Decision

Option 3, both halves.

`policy.carries_signal` is a strict `score > 0`, folded into
`policy.shortlisted`. A **missing** score passes — an absence of evidence is
not a verdict of worthless, and the 6,390 unregenerated Discogs rows are in
exactly that state.

`--min-albums` now counts the seed's own albums, through `policy.seed_albums_of`
— one function reading D14's labelling, so the gate and `signal_for`'s score
cannot drift apart. The skipped people are printed with their names rather than
silently dropped.

## Evidence

Measured 2026-10-20 on the regenerated store and the committed discovery file:

| | |
|---|---|
| rows at score 0, Qobuz path | 175, through 5 referrers |
| the shortlist before `sig_score > 0` | 285 |
| after | 273 |
| people `--min-albums 2` would resolve, counting all albums | 122 |
| counting own albums | 110 |

The 12 no longer resolved are the five above plus Benito Casado Muñoz, Fernando
Grediaga, Kevin Johansen, Leonard Cohen, Luis "Luca" Ortega, Omar Roldán Molina
and Calequi. Leonard Cohen and Kevin Johansen are the check that this is right:
both are real connections to the seed, and neither worked on his records — Cohen
wrote a song Drexler covered, Johansen shares a billing. They are
`co_artists`, not crew.

## Consequences

- 12 fewer autosuggest lookups and 12 fewer discographies per `resolve_qobuz`
  run, which is 12 of the 57 artists it fetched.
- The read filter bites immediately; the gate only on the next regeneration, so
  until then the pool still holds the 175 rows and the query is what excludes
  them.
- `--min-albums` means something different from what it did, on the same flag.
  A discovery file written before D14's labelling falls back to the old total,
  and `signal_for` flags `unlabelled_albums` when it does.
- This is the first filter here that is NOT a taste judgement — the three in
  [D15](D15-filters-before-ranking.md) say what a credit is worth, this one says
  there is no credit. Worth keeping distinct: if the scoring changes so that a
  real referral can reach 0, this silently starts dropping real rows.
