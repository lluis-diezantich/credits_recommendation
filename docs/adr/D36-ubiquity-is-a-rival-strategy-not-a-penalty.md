# D36: Ubiquity is a rival strategy, and only an exact name match is believed

- **Status:** Accepted
- **Date:** 2026-10-24
- **Where it lives:** [`stages/ubiquity.py`](../../stages/ubiquity.py),
  [`core/discogs.py`](../../core/discogs.py) (`CACHE_DIR`, `total_releases`,
  the tie-break in `find_discogs_artist`), [`policy.py`](../../policy.py)
  (`UBIQUITY_TRUSTED_MATCHES`, `trusted_ubiquity`, `ubiquity_factor`,
  `rank_selective`), the `ubiquity` table in
  [`stages/load.py`](../../stages/load.py)

## Context

`policy.selectivity()` has existed since the pool was built and had no input
for the ranked list: **0 of 580 candidates carried a release count**, because
the only stage that ever fetched one (`resolve_discogs.py`) runs on people
Qobuz cannot see, and a co-artist is by definition someone Qobuz can.
[D29](D29-strategies-are-hypotheses-and-the-log-judges-them.md) named this the
strongest case for spending requests.

The complaint it was bought to fix: `breadth` led with six reggaeton features
— Ozuna, Arcangel, Jhayco, Tainy, Sech, Nicky Jam — all corroborated through
the same Karol G / Bad Bunny / ROSALÍA cluster, above Yomo Toro at 23 records
with Willie Colón and Héctor Lavoe.

**That diagnosis was wrong, and the measurement is what says so.** See
Evidence: those six are no more prolific than Yomo Toro, and every genuinely
ubiquitous candidate already sits at corroboration 1, which is where `breadth`
puts them anyway. The feature is still worth having — it is just not the fix
it was asked for, and this ADR exists partly to record that.

## Options

1. **Fold a penalty into `breadth`.** What was asked for. Rejected on two
   grounds: it would not change `breadth`'s top (Evidence), and
   `data/shown.json` already holds five logged `breadth` runs, so redefining
   `breadth` would make `--score` compare them against a different strategy
   under the same name — the thing D29's log must never do.
2. **One blended score with ubiquity as a term.** Rejected by D29 already:
   nothing scores this list yet, so a blend is an unmeasured weight wearing a
   measurement's clothes.
3. **A fifth strategy, `selective`.** `breadth`'s lexicographic shape with the
   tie-break multiplied by the factor. Competes with `breadth` by name, logs
   separately, and `--compare breadth selective` shows exactly what the claim
   buys.

## Decision

Option 3, and a trust rule beside it: **only an `exact` Discogs name match is
believed.** A number from an `ambiguous` match is discarded as if it had never
been fetched, and a person with no number gets a factor of **1.0 — no penalty
and no bonus**, not `selectivity()`'s 0.5 "unknown".

0.5 is right in the pool path, where the score is a referral's strength and an
unknown referrer genuinely is weaker evidence. Here the feature is a fact about
a person, and 0.5 would be a half-penalty on 204 people for a lookup *we*
failed.

## Evidence

Measured 2026-10-24 over the 580 filtered candidates, 1,160 Discogs requests,
all cached in `cache/discogs/`.

| | |
|---|---|
| asked | 580 |
| `exact`, believed | **376** (65%) |
| `ambiguous`, discarded | 134 |
| no number at all | 70 |
| releases: min / median / p90 / max | 1 / 54 / 859 / 9,796 |

**Why the match kind decides and not the value.** An ambiguous pick returns a
wrong *small* catalogue — 1 release each for Travis Scott, Sech and The Marías
— and small reads as scarce, so a trusted ambiguous row would be **promoted**
by the feature meant to demote it. 20% of ambiguous rows are under 10
releases, and so are 19% of exact ones, so the count cannot separate a real
small catalogue from a wrong match.

**Why this is not the fix it was asked for.** Every candidate over 600
releases sits at corroboration 1 — Snoop Dogg 9,796, Busta Rhymes 7,290,
Christina Aguilera 5,038, Ludacris 4,758 — and `breadth` gates on
corroboration first, so it already ranks them 300th and worse. Meanwhile the
six that led the list are *ordinary*: Ozuna 300, Tainy 276, Arcangel 272,
against Yomo Toro 337 and Papo Lucca 304. `selective` leaves all six in place.
Where ubiquity bites is the strategies that do not gate on corroboration:
`taste` ranked Jennifer Lopez 87th of 380 on 5,143 releases.

**What `selective` actually changes:** 365 of 380 candidates move, all
downward in the tail, led by Andrea Bocelli (81st → 369th) and Christina
Aguilera (104th → 372nd).

**A cost found while measuring, and not resolved.** The bands cannot tell a
long career from a session ubiquity. Pellín Rodríguez (51st → 300th), La
Sonora Ponceña (50th → 298th) and Hugo Fattoruso (139th → 353rd) have large
catalogues because they recorded for decades, not because they appear on
everything — and deep-catalogue Latin artists are what this corpus is best at
finding. `selective` demotes them. This is the main reason it is a rival
strategy and not a correction: the claim may well lose, and the log is what
should settle it rather than an argument here.

The bands themselves are `selectivity()`'s, reused rather than re-chosen, which
also means they were not fitted to this data. The median candidate has 54
releases and lands unpenalised at 1.0, so a typical number and a missing one
are worth the same — deliberate, so there is no bonus to win by failing a
lookup.

## Consequences

- **`selectivity()` finally has an input**, and the store carries it: the
  `ubiquity` table, one row per person, with `match` as a column because a
  query that read `total_releases` alone would believe Travis Scott has one
  release.
- **A wrong Discogs id now reads as a small catalogue, which the tie-break in
  `find_discogs_artist` partly fixes and partly does not.** Preferring the
  spelling as written over the lowest id corrected Maná from 21 releases to
  505. It cannot help where the right entry is spelled differently, which is
  what the 134 discarded rows are.
- **`resolve_discogs.py` shares that matcher**, so the pool it built may point
  at wrong Discogs artists — and there a wrong id injects a whole collaborator
  network rather than one number, which its own docstring warns about. Not
  re-run here; in [../../todo.md](../../todo.md).
- **The store builds without the file.** `load_ubiquity` returns on a missing
  `data/ubiquity.json`, and every reader goes through `ubiquity_factor`, which
  is neutral on None — so a fresh clone ranks exactly as before rather than
  needing 1,160 requests.
- **Coverage is 65% and will not improve by asking again.** Raising it means a
  better matcher, not more requests: MusicBrainz already holds an artist's
  Discogs URL as a relation, which would replace the name search with a
  lookup. That is the next thing worth measuring.
- **What would reopen it:** `--score` separating `breadth` from `selective`
  either way. If `selective` wins, the penalty belongs in the default and the
  deep-catalogue cost above was acceptable; if it loses, the bands were wrong
  for this corpus and the honest move is to delete the strategy rather than
  retune it, because nothing here was fitted to anything.
