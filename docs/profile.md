# The profile

Who you still listen to, measured in **active months** rather than plays.

    ./stages/profile.py --seed              # once: compact the export zip
    ./stages/profile.py --month --user X    # monthly: 1 request, save the month
    ./stages/profile.py                     # anytime: print the table, free

Not to be confused with `data/favourites.json`, which is the list of artists
each radar *watches*. This is the evidence for who belongs on that list.

## Three jobs, three cadences

Two write, one reads. The split is the point: the writers are slow or
perishable, the reader is free, so the floors in `policy.py` can be re-tuned as
often as you like for nothing.

| | | when | cost |
|---|---|---|---|
| `--seed` | the export zip → one file per month | once, then yearly to repair | 0 requests, reads 21 MB |
| `--month` | the last calendar month, from the stats API | monthly | 1 request |
| (default) | every month on disk → one row per artist | whenever | free |

## The two numbers

Depth and currency, kept apart, with no ratio between them:

    lifetime active months   how long they have mattered
    months in the last 24    whether they still do

                  m24 >= 10        m24 < 10
    life >= 24    core             lapsed
    life <  24    emerging         thin

`lapsed` is the band that earns the design: real past interest, nothing now.
Do not watch it for new releases, but keep the credit-graph edge — that is
roadmap.md's "prune the first, never the second". Radiohead lands here on 73
lifetime months and 3 recent ones, and that was confirmed by hand.

The floors are `M24_FLOOR`, `DEEP_FLOOR` and `RECENT_WINDOW` in
[policy.py](../policy.py), with the artists they were measured against in the
comment beside them.

## What is on disk

`cache/listens_months/YYYY-MM.json` — one file per month, 2.6 MB for 137 months.

| field | |
|---|---|
| `month` | the month this file is the whole of |
| `source` | `export` or `stats`, so a seeded month is distinguishable |
| `artists` | `[{mbid, name, plays}]`. `mbid` is null where nothing ever mapped it |

One file per month on purpose: a month nobody fetched is a **missing file**
rather than a silently short count.

## Decided on purpose

**Months, not plays.** Plays scale with how much history you hold — Drexler is
68 plays in a 2,000-listen sample and 6,447 in the export, a 95× difference on
the same artist. A plays threshold calibrated on one file is wrong by two
orders of magnitude on the other. Active months can only grow toward the months
the data spans, so a threshold roughly survives.

**Two numbers, not a ratio.** A share of recent to lifetime months was tried and
dropped: dividing by lifetime put the denominator on both sides of a revival, so
coming back took ten months for a deep artist and five for a new one. It
punished an artist for having mattered once. An absolute count asks the same of
everybody.

**Joined on MBID, never on name.** `normalise()` loses Omar Rodríguez‐López to a
U+2010 hyphen — 50 active months and 742 plays, reported as absent. Matching on
mbid takes `favourites.json` from 84 of 93 entries to 89.

**The stats API, not the raw listens.** Raw listens carry an mbid on about 12%
of rows; the monthly stats endpoint carries one on 80%, and folding name-only
rows against spellings known elsewhere brings that to **94% of plays**. The
stats API splits one artist whenever a listen went unmapped or an accent
differs, so "Jorge Drexler" arrives twice in one month, with an mbid (218 plays)
and without (38). 59 of 130 such rows folded back.

**The export repairs, it does not feed.** It is the only source of MBIDs at
scale and the only way to recover a month the cron missed, so it is a yearly
chore rather than the pipeline. Everything between exports comes from one
request a month.

**The window counts back from the newest month on disk, not today.** So the
header says `through 2026-05` and every verdict is "as of your data". Counting
from today would quietly mark everyone lapsed when the real cause is a missed
run.

**A collaboration counts for every credited artist**, which is what the stats
API does too, so the two sources join without a step at the seam. It means
credited plays exceed listens — 206,560 against 190,131 — and
`mbid_mapping.artists` is what supplies one name per mbid. The `artist_name`
field is the whole credit line: "j milo" is the line for a Milo j & Trueno
track, and using it invents an artist while losing two real ones.

## Gotchas

**A missed month is gone.** `range=month` only ever answers about one past
calendar month; there is no way to ask for September once November starts.
Re-download the export and `--seed` again to fill the hole.

**Stats lag about 18 hours.** Run it a day or two into the month, not at
midnight on the 1st.

**`total_artist_count` is not an artist count.** all_time reports 9,024 against
the export's 6,405 distinct MBIDs, inflated by exactly the fragmentation the
fold undoes.

**`emerging` is too loose to act on.** 2,006 artists, because the currency test
scales to a short history and three recent months out of three qualifies. Right
for a verdict, useless as a list — it wants a floor nobody has set yet.

**A burst reads as decay.** Omar Rodríguez-López has 3 active months in the last
24 and 154 plays inside them, last played this month. He lands `lapsed`.
Months cannot tell a binge from a cooling taste; `recent_plays` is printed next
to them so the eye can.
