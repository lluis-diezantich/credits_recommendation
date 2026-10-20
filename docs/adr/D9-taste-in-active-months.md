# D9: Taste is measured in active months, not play counts

- **Status:** Accepted
- **Date:** 2026-10-18
- **Where it lives:** [`core/listens.py`](../../core/listens.py),
  [`stages/profile.py`](../../stages/profile.py), three floors in
  [`policy.py`](../../policy.py), [`../profile.md`](../profile.md)

## Context

The watchlist came from a ListenBrainz top-artists ranking, which is a play
count. A play count cannot tell an artist played constantly for ten years from
one binged for a fortnight, and the radar watches whatever it ranked.

## Options

1. **Play counts**, as ranked: one number, already available, no history.
2. **A recent-to-lifetime ratio**: one number, and it collapses two different
   artists — a long catalogue with a quiet year and a new favourite — onto the
   same value.
3. **Two numbers, no ratio**: lifetime active months and months active in the
   last 24, kept separate.

## Decision

Option 3. Each month of listening is snapshotted and committed, so the history
accumulates rather than being re-derived from a single export.

## Evidence

Over the full export (190,196 listens, [D4](D4-measured-against-real-listening.md)):
80 artists in `core`, 113 `lapsed`, and 140 deep artists the ListenBrainz
ranking never surfaced. Radiohead lands `lapsed` on 73 lifetime months against 3
recent, confirmed by hand.

## Consequences

- `emerging` is 2,006 artists, because the currency test scales to a short
  history and three recent months out of three qualifies. Right as a verdict,
  useless as a list, and it needs a floor nobody has set — which is why nothing
  yet writes a verdict back into `data/favourites.json`.
- A burst still reads as decay, flagged rather than corrected ([D5](D5-flag-rather-than-reclassify.md)).
- The profile has two answers to "how many artists do I watch": 93 un-muted
  entries against 91 watched, because `favourites.ids_for` keys on `qobuz_id`
  and two pairs share one. Harmless today, but a per-artist number has to pick
  which grain it means.
