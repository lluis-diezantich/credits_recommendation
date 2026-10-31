# D45: The label is reason enough for an album; the credit is what earns a single

- **Status:** Proposed
- **Date:** 2026-10-31
- **Amends:** [D44](D44-the-label-is-the-query-the-credit-is-the-judgement.md)
  on one point — what the radar reports by default. D44 is still Proposed, so
  this is a separate file rather than an edit only because D44's title is its
  decision; its scan, its gate and its judgement all stand.
- **Where it lives:** `core.labels.FEED_VERDICTS` and `FEED_KINDS`,
  `radars/labels.py` (`--feed`, `cap`)

## Context

D44 reported a release only when somebody you follow was credited on it: about
12 a week. Everything else was dropped after a request had already been spent
reading it.

But the labels were chosen because your artists release on them, so the rest of
what they put out is of interest too. Measuring it: those 212 labels released
**257 records in 14 days, 128 a week**, already-released and editions folded.
Too many to read, and unevenly spread — 126 labels released nothing at all and
10 labels made 35% of the volume.

## Options

1. **Report everything, drop the credit check.** Cheapest of all — it saves the
   `album_detail` per candidate — but the credits only arrive with that call, so
   there is no way to say which rows a producer you follow made.
2. **Report everything, keep the credit check.** Same cost as D44. `report.py`
   already tables rows with a `because` separately from rows without, so this
   needs no formatter work.
3. **Leave it at credited rows only.**

## Decision

Option 2, with the volume filters on the FEED rows alone:

- **Credited rows are reported whatever their kind**, uncapped by the feed's
  rules. A producer credit is a reason, and most of those rows are singles.
- **Feed rows are albums and EPs**, from the verdicts that still describe a real
  new release (`absent`, `writing`, `sideline`). `--feed all` takes singles too,
  `--feed off` is D44's behaviour.
- **The per-label cap applies to each group separately**, so a label having a
  busy week cannot push its one credited release out of the report.

Reissues and remixes stay out of both. They are old recordings on a new date,
which is what the window is for.

## Evidence

Measured 2026-10-31 over all 212 watched labels, 14-day window, pre-orders
excluded (D33) and editions folded:

| the feed would be | rows | a week | labels |
|---|---|---|---|
| everything | 257 | 128 | 80 |
| everything, cap 2 | 130 | 65 | 80 |
| **albums + EPs, cap 2** | **69** | **34** | **49** |
| albums only, cap 2 | 45 | 22 | 34 |
| albums + EPs, cap 1 | 49 | 24 | 49 |

Singles are the volume: 175 of the 300 releases in the raw window. Dropping
them halves the feed and keeps the breadth — 49 labels still contribute, where
tighter rules collapse it. Two that were tried and rejected: a catalogue gate
of 400 gets to 26 a week but gates the SCAN, so it would have cost Edgar
Barrera's row on Interscope (505 releases); requiring 2+ of your artists on a
label gets to 6 a week from 8 labels, which deletes the scene rather than
filtering it.

The first run of it, 14 days: **71 rows — 21 credited and 50 feed** (33
albums, 17 EPs, no singles), about 35 a week in two tables against the Friday
radar's 5.8.

That run also found a reporting bug worth recording, since it is the one D42
warned about: the summary said "103 on the feed" beside 50 printed rows,
because feed rows were counted before the per-label cap. Counted after it now,
and still an upper bound, because the runner drops pre-orders afterwards.

## Consequences

**Easy.** The dial is one flag, and the three settings were each measured. The
feed costs no extra requests — the catalogue read and the `album_detail` were
already being spent, and the rows were being thrown away.

**Hard.** This is the larger of the two weekly issues now, by a lot. If it goes
unread, `--feed albums` → `--feed off` returns to D44 exactly.

**What it rules out.** Option 1's saving. As long as the top table exists, every
candidate costs its `album_detail`.

**Follow-ups.** The 10 labels making 35% of the volume are distributor-ish
imprints under the 2,000 gate. Muting them by hand in `data/labels.json` is the
intended fix, and whether a lower gate plus a hand-kept exception list beats it
is unmeasured.
