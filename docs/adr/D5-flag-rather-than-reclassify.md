# D5: When two signals disagree about one artist, flag it rather than reclassify

- **Status:** Accepted
- **Date:** 2026-10-18
- **Where it lives:** `policy.burst`, `COVERS_MILL_HINTS` and `writing_tier`'s
  `lyrics_only` in [`policy.py`](../../policy.py)

## Context

Three places where two signals point opposite ways about the same artist:

- an artist with few recent months but intense ones (Omar Rodríguez-López: 5
  months, 163 plays) reads as decayed to a months-based verdict;
- a writer credited only as lyricist may have co-written the song or only
  translated it (Drexler on "Waka Waka");
- a performer whose catalogue is mostly other people's songs may be a covers
  mill or may be an interpreter.

## Options

1. **Reconcile into one verdict** — promote the burst artist, or rule the
   lyricist a writer: one clean label per artist, and the rule has to be right.
2. **Flag the disagreement** and leave the verdict alone: the consumer sees both
   and the output gains a column instead of a wrong label.

## Decision

Option 2, whenever the two signals turn out to be separate axes rather than two
measurements of one thing. Reconcile only when they are the same axis.

## Evidence

Every promotion rule tried on bursts also promoted Interpol, judged cooled by
hand — intensity is a third axis, not a correction to recency. The lyricist case
is asymmetric by example rather than by count: ROLE_CLASS called translating a
song identical to composing it.

## Consequences

- Verdicts stay comparable across artists, and doubt is visible instead of
  averaged away. The "watched but lapsed" line says how many of its names are
  doubtful.
- Nothing downstream is obliged to read a flag, so a flag can be ignored
  silently — which is how `single_token_name` sat in the pools unused while the
  score promoted the rows it marked ([D13](D13-match-plausibility-on-read.md)).
- `policy.match_confidence` returns 1.0 for an unknown flag on purpose, so
  adding a flag cannot change an order by accident.
