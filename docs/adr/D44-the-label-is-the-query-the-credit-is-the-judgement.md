# D44: The label is the query and the credit is the judgement

- **Status:** Accepted. Its default is amended by
  [D45](D45-the-label-is-reason-enough-for-an-album.md), which reports every
  album on a watched label and keeps this file's judgement for the credits.
- **Date:** 2026-10-31
- **Where it lives:** `core/labels.py` (the judgement), `core/qobuz.py`
  (`label_catalogue`), `radars/labels.py` (the loop and the two builders),
  `data/labels.json`, `data/producers.json`, `tests/test_labels.py`,
  `tests/test_labels_radar.py`

## Context

The radar reports what a watched artist released, and what they are credited on
(D42). The next question is what the *producers* of those artists made for
other people.

Qobuz files a release under the artists named on it, never under its producer.
That is why D42 had to search the track index, and the track index does not
carry production credits reliably either (Evidence). So the forward lookup both
existing passes rely on does not exist for the person this is about.

The producer list is not the problem: `stages/discover.py` on `ranking` reads
per-track credits, and 168 walked artists give 5,191 names.

## Options

1. **Fan out from each producer through Discogs.** The only complete person →
   work index. Needs a token, ~24,000 requests, and Discogs carries a release
   *year*, so it cannot answer "what came out this week".
2. **Read credits off the store's new-release feed.** D42 declined this on the
   ungated feed; re-measured across all twelve genres and still dead.
3. **MusicBrainz producer relationships.** Free, dated, a real reverse index,
   ~1% filled in.
4. **Scan the labels those artists release on, and let the credits decide.**
   Qobuz indexes a label completely and newest-first, so one request narrows
   the store to a week of releases. It finds a producer only inside that label
   set.
5. **Do nothing.** The Friday radar already reports ~5.8 credited appearances a
   week.

## Decision

Option 4. `label/get` says what came out, `album/get` says who made it, and
`core/labels.py` decides which of those is news. The producer list is the
filter rather than the thing looked up, so adding a name costs no requests.

Three judgements came out of reading the first runs:

- **Every row names which of your artists that producer works with.** "James
  Ford - Producer" is a stranger; "works with ROSALÍA, Björk" is a
  recommendation. The names come from the `for` field the discovery files fill
  in.
- **A remix is not a record they made.** D30 decided this on `ranking` using
  roles (`Re-Mixer`), which `ROLE_FAMILY` already drops. `is_remix` covers the
  other shape: a real `Producer` credit on a rework.
- **No label may fill the report** (`--per-label`).

D42 stands. Its track-index pass is still the only thing that finds a watched
artist's own guest spots, and this radar drops any release already credited to
an artist you watch, so the two cannot report the same row.

## Evidence

All measured 2026-10-31 against the live `gb-en` store and the 167 watched
artists with a Qobuz id.

| what was tried | result |
|---|---|
| the track index, searched by producer name | **dead.** Six people with 2–6 producer-only albums returned 4 of 4, 2 of 2, 0 of 2, 5 of 6, 2 of 3, 0 of 2. `Aidan Cullen` is the clean case: 54 rows, so nothing was truncated, and the album `album/get` credits him `Producer` on is absent. Prolific names also lose to `SEARCH_CAP` — Tainy 10 of 30, Ovy On The Drums 14 of 45 |
| MusicBrainz `inc=release-rels` | **dead.** Tainy 2 relationships, Edgar Barrera 1 (and it is `writer`), Campi Campón 2. Tainy has produced hundreds |
| the new-release feed, all 12 genres | **dead**, 12× wider than D42 measured it. 1,998 albums, 483 inside 14 days, containing **1** of the 23 releases the radar's own first pass found. An editorial shortlist weighted to major-label Anglo releases |
| label catalogues | **works.** Strictly date-descending on `Sony Music Entertainment` (47,303 releases) and `Young` (546), which is what makes a page a date range |

**Only the middle of the label distribution is worth scanning.** The 167
artists released 613 records in a year across 251 labels: the top 10 cover
23%, the top 50 cover 57%, and 145 labels released exactly one. Probing the top
60 for a fortnight returned 340 unseen releases, of which **7 labels with
catalogues over 2,000 produced 245** — Sony alone 128. That is where
`MAJOR_CATALOGUE = 2000` comes from, and it is a size rather than a list of
names because `WM Spain` and `Universal Music Latino` behave the same way and
look nothing like Sony in the file.

**Who to look for**, over `data/producers.json` (5,191 people): 2,763 kept.

| dropped | |
|---|---|
| 12 `junk` | `Not Documented` holds credits across 15 of these artists and `Unknown` across 11 — what Qobuz ships when a label leaves the slot blank. Plus `Jr`, `KJ`, `JD`, fragments off a split name. An exact list after `normalise`, because a first regex matched `Navarro` and `Molina` |
| 49 `yourself` | artists you already watch, producing their own records. The `yours` test cannot catch them, because it only sees who a release is credited to |
| 2,361 `thin` | credited on one record only. One credit does not show that an artist chose to work with somebody |

**`thin` counts every kind of credit, and counting production alone was
measured down.** It cut the list to 409 and dropped Marta Salogni (9 credits on
these artists, none as `Producer` — she mixes for them) and Neal Pogue (10,
none), and with them the two rows that best made this radar's case. The list
asks whether somebody is part of the crew, where a mixing credit is evidence.
`verdict` asks whether they produced *this* record, decided per release.

**The runs.** A 90-day backfill on a 785-name list reported 34 releases from
1,484 candidates, 2.6 a week. After walking all 167 artists the list reached
2,763 names and a 14-day scan reported **24 releases, about 12 a week** —
larger than the Friday radar's 5.8, with `works with` naming three artists per
row instead of one. Funnel from the backfill: 34 credit, 1,210 absent, 106
sideline, 119 yours, 12 writing, 3 reissue.

What the runs say about the knobs:

- **engineering is ~4× the rows.** 106 sideline against 34 credit, so
  `--credit production,engineering` lands near 11 a week on its own. The same
  73%-mixing shape the archived pipeline measured.
- **`--per-label 2` costs 5 of 34.** Four come from one distributor string
  carrying a single campaign, where a hand mute is the better answer; the fifth
  is James Ford's three Fontaines D.C. singles, which is the radar working.
- **`Executive Producer` earns rows it probably should not** — 3 of the 24,
  all one person on regional Mexican singles. It is a label role.
- **The most connected people are now mastering engineers.** Chris Gehringer
  across 15 of these artists with no production credit at all, then Dave Kutch
  and Randy Merrill across 10. `--credit production` filters them per release,
  but they are why a selectivity weighting will eventually be needed.
- **4 of 34 rows are the producer's own record.** Testable, since they are
  credited on it. Left alone: whether that is news is a taste question.

**One measurement is withdrawn.** A first 90-day run reported 33 rows stopping
at 2026-10-16; a `data/labels_seen.json` present when it started had suppressed
10 releases as already reported. Every run was `--dry-run`, and `--dry-run` was
then verified not to write state, so how that file appeared is unexplained. The
numbers above used `--state` on a scratch path, which is what a measurement
here should always do.

## Consequences

**Easy.** Adding a producer is a file edit, so the fan-out option 1 rejected
becomes free. `--credit` and `--per-label` ask the volume questions at run time.

**Hard.** This is a scene filter. A producer working on a label none of your
artists use never appears, and nothing in the output says so. The gate also
rejects a real label that shares a name with a watched artist — `Napa` is both
a band on the list and the label on their own releases.

**Ruled out:** any claim that this finds everything those producers made. It
finds what they made inside a label set, which is why every row names its
label.

**Follow-ups** (kept here; `todo.md` is on `ranking`, so a link would dangle):

- `record_scanned = False` means a release crediting nobody is re-read weekly.
  That is what makes adding a producer retroactive, and the first thing to
  measure if a run gets slow.
- Nothing re-measures a catalogue size, so a label that grows past
  `MAJOR_CATALOGUE` keeps being scanned until `--discover` runs again.
- Ranking people by selectivity was tried and abandoned: `cache/discogs` covers
  106 of them, and the count includes their own discography, so Björk comes
  back at 2,713 releases and ranks as the least selective person in the file.
  Doing it properly needs the Discogs fan-out option 1 rejects.

**What would reopen it:** a reverse credit index with real dates. Qobuz adding
one, or MusicBrainz's producer relationships reaching usable coverage, makes
this an expensive way to ask a question that could be asked directly.
