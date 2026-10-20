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

## What the run then showed (2026-10-20, same day)

The Qobuz half was regenerated: `discovery_41620.json` first, then
`resolve_qobuz.py` (122 of 278 people, 66 resolved, 1,496 releases from 57
artists) and `load.py`. No row came out `unlabelled_albums`, so the own-album
half took effect everywhere.

**The guest-spot fix is worth more than expected.** 10 of 50 referrers lost
albums, and five — Chab, Susana San José, El David Aguilar, Ulises Hadjis,
Çantamarta — went to **zero** own albums and therefore score 0.0. They never
worked on a Drexler record at all: they are artists he guested alongside, which
is what [D14](D14-co-appearance-is-its-own-output.md)'s `co_artists` block is
for. Juan Campodónico went 7 albums to 6, which took the shortlist's second row
from 0.70 to 0.60.

**Catalogue size does NOT separate a collision from a real match**, so the
hypothesis this decision made testable is now tested and refused for the Qobuz
path:

| | albums held by the matched artist |
|---|---|
| flagged `single_token_name` (6 people) | 4 to 309, mean 214 |
| unflagged (44 people) | 1 to 483, mean 126 |

Caetano Veloso holds 483 albums and is a correct match; "Calequi" holds 4 and is
flagged. A big catalogue is normal among correct matches, so size alone cannot
be a filter. What the original argument wanted was a *comparison* — the matched
artist's catalogue against the number of releases the credits put the person on —
and the Qobuz path has only one of those two numbers. That comparison still
needs the Discogs path, which needs a token.

## Consequences

- **The Discogs half is still unregenerated** (no `DISCOGS_TOKEN`), so
  `sig_match_confidence` is NULL on its 6,390 rows and the query in
  [../store.md](../store.md) still applies the penalty conditionally on that.
  The branch goes when that half is run.
- The regeneration is roughly 1 request per seed for discovery, ~59 for
  `resolve_qobuz`, and the 128-person Discogs fan-out, which is cached.
  `DISCOGS_TOKEN` is needed for the last one.
- `discovery_*.json` must be regenerated FIRST, or every row is flagged
  `unlabelled_albums` and the own-album half of this decision does nothing.
- A row's score is no longer comparable across generations. That is what
  `sig_match_confidence` being NULL marks, and it is the reason the column
  exists rather than the factor being folded invisibly.
