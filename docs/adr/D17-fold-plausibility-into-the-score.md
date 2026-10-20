# D17: The resolvers fold match plausibility and own-album counts into the stored score

- **Status:** Accepted
- **Date:** 2026-10-20
- **Where it lives:** `signal_for` in [`stages/resolve_qobuz.py`](../../stages/resolve_qobuz.py),
  the `signal` dict in `build_pool` in
  [`stages/resolve_discogs.py`](../../stages/resolve_discogs.py),
  `sig_match_confidence`, `via_albums_count` and `via_discogs_releases` in
  [`stages/load.py`](../../stages/load.py)

## Context

Three debts had accumulated against the stored pool scores, each recorded with
its own entry and each needing the same thing — the pools regenerated:

- [D13](D13-match-plausibility-on-read.md) applied the match penalty on read
  and named folding it into `sig_score` as the better fix. Any consumer reading
  `sig_score` directly still ranked the collisions first.
- [D14](D14-co-appearance-is-its-own-output.md) labelled guest albums but left
  `person_seed_albums` counting them, so a referrer's embedding was still
  inflated by records the seed did not make.
- [D15](D15-filters-before-ranking.md) found that the only corroboration
  available for a name match — the size of the catalogue it was matched to —
  was being fetched by the autosuggest call and then dropped.

## Options

1. **Fix them one at a time**, as each becomes annoying: three regenerations of
   both pools, which is three times the API bill for one outcome.
2. **Fix all three in the resolvers now and regenerate once:** one bill, and
   every row in the store changes at the same moment.
3. **Keep applying everything on read** and never regenerate: no requests, and
   every reader has to know three corrections — which is how the "Morgan at
   1.00" row survived being known about for two days.

## Decision

Option 2.

- Both resolvers multiply the score by `policy.match_confidence(flags)` and
  store the factor as `match_confidence` beside it, so the discount is visible
  and reversible rather than baked in.
- `seed_albums` and `person_seed_albums` prefer the discovery file's
  `own_albums`. Where the file predates labelling, the row is flagged
  `unlabelled_albums` rather than falling back silently — the silent fallback
  is the old inflated number, and nothing downstream could tell.
- `via.albums_count` (how many albums the matched Qobuz artist holds) and
  `via.discogs_releases` (how many releases the Discogs credits put the person
  on) are kept.

## Evidence

The three measurements this rests on are already recorded: 3,673 of 7,860 rows
flagged and "Morgan" at the maximum 1.00 (D13), 15 of 62 albums mislabelled as
the seed's own (D14), 72 flagged rows still inside the 291-row shortlist (D15).

**What is NOT yet measured, and must not be claimed:** whether catalogue size
actually separates a collision from a real match. It cannot be measured from the
pools on disk, because neither size was ever stored — that is what this change
fixes. Two cheaper corroborations were tried on 2026-10-20 and both failed, so
the hypothesis is open, not confirmed:

| | result |
|---|---|
| a real match shares another person with the graph | 0/459 for Henry Mancini and 0/120 for Zahara, who is real — no discrimination |
| a real match's dates overlap the referrer's career | disjoint for nobody: Qobuz artist pages aggregate reissues, so Mancini reads 1956-2026 |

## Consequences

- **Nothing changes until the pools are regenerated.** The code is in place and
  the data on disk still carries the old scores, so `sig_match_confidence` is
  NULL for every row today and the query in [../store.md](../store.md) applies
  the penalty conditionally on that. Once both pools are rebuilt, that branch
  can go.
- The regeneration is roughly 1 request per seed for discovery, ~59 for
  `resolve_qobuz`, and the 128-person Discogs fan-out, which is cached.
  `DISCOGS_TOKEN` is needed for the last one.
- `discovery_*.json` must be regenerated FIRST, or every row is flagged
  `unlabelled_albums` and the own-album half of this decision does nothing.
- A row's score is no longer comparable across generations. That is what
  `sig_match_confidence` being NULL marks, and it is the reason the column
  exists rather than the factor being folded invisibly.
