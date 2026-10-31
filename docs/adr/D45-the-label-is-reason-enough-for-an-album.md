# D45: The label is reason enough for an album; the credit is what earns a single

- **Status:** Accepted
- **Date:** 2026-10-31
- **Amends:** [D44](D44-the-label-is-the-query-the-credit-is-the-judgement.md)
  on one point — what the radar reports by default. Its scan, its gate and its
  judgement stand.
- **Where it lives:** `core.labels.FEED_VERDICTS` and `FEED_KINDS`,
  `radars/labels.py` (`--feed`, `cap`)

## Context

D44 reported a release only when somebody you follow was credited on it, about
12 a week, and dropped the rest after paying to read it. But the labels were
picked because your artists release on them, so the rest is of interest too —
and there is a lot of it: **257 records in 14 days, 128 a week**, unevenly
spread, with 126 labels releasing nothing and 10 making 35% of the volume.

## Options

1. **Report everything, drop the credit check.** Cheapest — it saves the
   `album_detail` per candidate — but the credits arrive with that call, so
   nothing could say which rows a producer you follow made.
2. **Report everything, keep the credit check.** Same cost as D44, and
   `report.py` already tables rows with a `because` apart from those without.
3. **Leave it at credited rows only.**

## Decision

Option 2, with the volume filters on the feed rows alone:

- **Credited rows come through whatever their kind.** A producer credit is a
  reason, and most of those rows are singles.
- **Feed rows are albums and EPs** from the verdicts that still describe a real
  new release. `--feed all` takes singles, `--feed off` is D44.
- **The cap applies per group**, so a busy week cannot push a label's one
  credited release out of the report.

Reissues and remixes stay out of both: old recordings on a new date is what the
window is for.

## Evidence

212 labels, 14 days, pre-orders excluded (D33), editions folded, 2026-10-31:

| the feed would be | rows | a week | labels |
|---|---|---|---|
| everything | 257 | 128 | 80 |
| everything, cap 2 | 130 | 65 | 80 |
| **albums + EPs, cap 2** | **69** | **34** | **49** |
| albums only, cap 2 | 45 | 22 | 34 |

Singles are the volume: 175 of 300 in the raw window. Dropping them halves the
feed and keeps the breadth, where tighter rules collapse it — a catalogue gate
of 400 reaches 26 a week but gates the SCAN, so it would have cost Edgar
Barrera's row on Interscope (505 releases), and requiring two of your artists
per label reaches 6 a week from 8 labels.

First run: **71 rows, 21 credited and 50 feed** (33 albums, 17 EPs), ~35 a week
against the Friday radar's 5.8.

That run also found the reporting bug D42 warns about: the summary said "103 on
the feed" beside 50 printed rows, because feed rows were counted before the
cap. Counted after it now, and still an upper bound, since the runner drops
pre-orders afterwards.

## Consequences

**Easy.** One flag, three measured settings. The feed costs no extra requests:
the rows were already being read and thrown away.

**Hard.** This is now the larger of the two weekly issues by a lot. If it goes
unread, `--feed off` returns to D44 exactly.

**Ruled out:** option 1's saving. While the credited table exists, every
candidate costs its `album_detail`.

**Follow-up.** The 10 labels making 35% of the volume are distributor imprints
under the 2,000 gate. Muting them in `data/labels.json` is the intended fix;
whether a lower gate plus an exception list beats it is unmeasured.
