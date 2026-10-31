# D44: A producer is found by scanning the labels they work for, not by asking for them

- **Status:** Proposed
- **Date:** 2026-10-31
- **Supersedes nothing.** Extends D42 with a second question and borrows D30's
  conclusion about remixes for a different shape of the same problem.
- **Where it lives:** `core/labels.py` (the judgement), `core/qobuz.py`
  (`label_catalogue`), `radars/labels.py` (the loop and the two builders),
  `data/labels.json`, `data/producers.json`, `tests/test_labels.py`,
  `tests/test_labels_radar.py`

## Context

The radar reports what a watched ARTIST released (first pass) and what they are
credited on (second pass, D42). The question this answers is the next one over:
*what did the producers of those artists make for somebody else?* — the engineer
or producer whose name recurs across the records you already play.

Nothing in Qobuz files a release under a producer. `artist/get` indexes billed
artists only, which is the whole reason D42 had to search the track index, and
the track index does not reliably carry a production credit either (Evidence).
So the forward lookup that both existing passes rely on does not exist for the
person this is about, and a reverse index has to be either bought elsewhere or
replaced by a narrower catalogue scan.

The producer list itself is not the problem. `stages/discover.py` on the
`ranking` branch already extracts it from per-track credits, and the 20
discovery files on disk hold 1,538 people with a production or engineering
credit, 497 of them on three records or more.

## Options

1. **Fan out from the producers through Discogs.** The only complete person →
   work index anywhere: `core/discogs.py` on `ranking` already pages it. Costs
   a `DISCOGS_TOKEN`, roughly 24,000 requests for the full watchlist, and
   inherits the two defects that branch measured on the same path — 73% of
   referrals arrive through mixing rather than production, and Discogs carries
   a release YEAR, not a date, so it cannot answer "what came out this week"
   at all.
2. **Invert to the store's new-release feed and read credits per release.**
   D42 declined this on the ungated feed. Re-measured widened across all twelve
   genres, which D42 did not try, and it is still dead (Evidence).
3. **MusicBrainz producer relationships.** Free, dated, and a real reverse
   index — `inc=release-rels` returns exactly "records this person produced".
   Coverage is about 1% (Evidence).
4. **Scan the LABELS the watched artists release on, and let the credits
   decide.** Qobuz indexes a label completely and newest-first, so a catalogue
   read is a date window and the store narrows to a few hundred releases a week
   before any judgement happens. Costs one request per label plus one per
   candidate, and it is a scene filter rather than a person index: a producer
   working outside the label set is invisible.
5. **Do nothing.** The radar already reports ~5.8 credited appearances a week
   from 167 artists with no token and no state.

## Decision

Option 4, on this branch, with three judgements layered on top of it once the
first runs had been read: the row NAMES which of your artists the producer was
found through, a remix is not a record they made (D30's conclusion reached by a
different test), and no label may fill the report.

**`works with` is the whole reason a row lands.** "James Ford - Producer" is a
stranger in an issue about music you follow; "James Ford - Producer, works with
Björk, Little Simz" is a recommendation with its evidence attached. The names
come straight from the `for` field the discovery files fill in, so they are the
artists this person was actually found through rather than anything inferred —
the same discipline as D21 on the `ranking` branch, where an explanation may
only say what the person actually did.

**A remix is not a record they made.** D30 decided that on `ranking` and
decided it on ROLES: a candidate whose only credit is `Re-Mixer`.
`ROLE_FAMILY` already drops those, because a remixer is not production. What
was left is the other shape — a genuine `Producer` credit on a release that is
itself a rework — and `core.labels.is_remix` is that test, on the title.

And the shape of option 4 itself: the label is the QUERY and the credit is the
JUDGEMENT. `label/get` says what came out, `album/get` says who made it, and
`core/labels.py` decides which of those is news. The producer list is the
filter rather than the thing being looked up, which is what makes the cost flat
in the number of producers — adding a name to `data/producers.json` costs no
requests at all.

Not a replacement for D42, and D42 is not superseded: the track-index pass is
still the only thing that finds a watched artist's own guest spots, and this
radar deliberately drops any release already billed to a watched artist so the
two cannot report the same row.

## Evidence

All measured 2026-10-31, against the live `gb-en` store and the 167 artists in
`data/favourites.json` that resolve to a Qobuz id.

**The track index does not carry production credits** (kills the cheap version
of this, which would have been D42's second pass run over producer names). Six
people with 2–6 producer-ONLY albums in the discovery files, searched by name:
the index returned 4 of 4, 2 of 2, 0 of 2, 5 of 6, 2 of 3 and 0 of 2 of the
albums known to credit them. `Aidan Cullen` is the clean case — 54 index rows,
so nothing was truncated by `SEARCH_CAP`, and Bad Bunny's *nadie sabe lo que va
a pasar mañana*, which `album/get` credits him `Producer` on, is simply absent.
Prolific names lose again to the cap: `Tainy` 10 of 30 known albums,
`Ovy On The Drums` 14 of 45.

**MusicBrainz holds almost none of it.** `Tainy` has 2 release relationships,
`Edgar Barrera` 1 (and it is `writer`), `Carles Campi Campón` 2. Tainy has
produced hundreds of records.

**The new-release feed is still dead, 12× wider than D42 measured it.** All
twelve genre feeds plus the ungated one hold 1,998 albums, 483 of them inside
14 days — so the feed is much bigger than the 425 D42 saw. Of the 23 releases
the radar's own first pass found for the 167 watched artists in that same
window, the feed contains **1**. Björk, Natalia Lafourcade, The Mars Volta,
iLe, José González, Rita Payés and Seun Kuti are all missing. It is an
editorial shortlist weighted to major-label Anglo releases, and this watchlist
is small-label Latin, Iberian and world music.

**Labels are worth scanning, but only the middle of the distribution.** The 167
artists released 613 records in 365 days across **251 distinct labels**: the top
10 cover 23%, the top 50 cover 57%, the top 100 cover 74%, and 145 labels
released exactly one. Probing the top 60 for a fortnight returned 340 unseen
releases, of which **7 labels with catalogues over 2,000 contributed 245** —
Sony Music Entertainment alone 128. Dropping those 7 leaves 95 candidates per
fortnight from 53 labels. That measurement is where `MAJOR_CATALOGUE = 2000`
comes from, and it is a threshold rather than a list of names because
`WM Spain`, `Universal Music Latino` and `BMG Rights Management (US) LLC` all
behave like Sony and none of them look like it in the file.

**A label catalogue is date-descending**, which is what makes the window a
prefix and lets `label_catalogue` stop paging: strictly descending by
`release_date_original` on `Sony Music Entertainment` (47,303 releases) and on
`Young` (546). Without that property this radar would cost a full catalogue
read per label per week.

**The first full run**, 2026-10-31, 212 labels, 14-day window, `--credit
production`: **9,947 releases scanned, 13 reported**, at a funnel of 13 credit,
239 absent, 29 sideline, 16 yours, 4 writing. 254 labels in the file, 42 of them
left out by the gate (27 major, 15 self-release). Roughly 450 requests and
about six minutes.

Reading those 13 rows is what the rest of this radar's judgement came from, and
three of them were right: Marta Salogni producing Westerman on Partisan, Edgar
Barrera producing Xavi on Interscope, and a Cachorro López row. The other ten
found four defects, all now fixed and tested:

| | |
|---|---|
| 3 rows named the WRONG PERSON | the row was kept for somebody's `Producer` credit and attributed to whoever held the most tracks — *Día de Muertos* to its `Music Director`. `core.labels.earned` picks the credit that earned the verdict, the same shape as `core/appearances.py`'s billed-credit preference |
| 5 of 13 rows were ONE act on one label | `Sumi Ani` is the producer `Ani Sumiati`'s own imprint, and a self-releasing producer credits themselves on everything. The catalogue gate cannot see it and neither can a name test (`sumi ani` is not `ani sumiati`), so the fix is a cap: `--per-label 2`. Of 212 labels scanned, exactly one produced more than two rows |
| 1 row was a REMASTER | *La Quiniela del Día (Remastered 2026)*, a 1960s Fania record. `album_detail`'s real date cannot catch it because the remaster genuinely is new, so the title is the only evidence — `core.labels.REMASTER_PATTERNS`, kept apart from `core/appearances.py`'s measured list on purpose |
| 1 row was a dub REMIX | Kaytranada on a Rochelle Jordan remix. Left alone: D30 on `ranking` decided a remix is not a collaboration, and reaching that conclusion here wants its own measurement rather than a pattern bolted on now |

**The second run, with those fixes in: 10 rows** from the same 9,947 releases,
funnel 13 credit, 239 absent, 29 sideline, 16 yours, 4 writing, 3 capped. All
three misattributed rows now name a producer — Gustavo Borner on *Día de
Muertos*, Lucas Piedracueva on the Raso Estudio single, Kevin Parker on the
GTAVI score — and the five Beckdown singles are two.

Two findings from that run that are NOT fixed:

- **The repackage marker is in `version`, not `title`.** Qobuz returns *La
  Quiniela del Día* with `version: "Remastered 2026"`, so the reissue test read
  the title alone and printed it anyway; `radars/labels.py` now joins the two
  before judging. **The same gap exists in `radars/qobuz.py`**, which passes
  `detail["title"]` to `core.appearances.verdict` and so never shows
  `is_retrospective` the version field either. Not touched here: D42's funnel
  is measured against that behaviour and changing it is its own decision.
- **The GTAVI score reaches both radars.** Kevin Parker produced it and Tame
  Impala is credited on it, so it is in `data/appearances-backfill.md` as a
  credited appearance AND here as a production credit. The `yours` test drops
  only releases BILLED to a watched artist, which this is not. Two sources
  reporting one record from two true angles is arguably correct; it is recorded
  here because it will look like a bug in an issue.

**Who is worth looking for**, measured over `data/producers.json` the same day.
The file holds 1,538 people with a production or engineering credit across the
20 discovery files, and three tests cut it to 785 — `core.labels.person_verdict`:

| | |
|---|---|
| `junk`, 5 entries | `Not Documented` (7 credits across 5 of the watched artists) and `Unknown` (10 across 3) are what Qobuz ships when a label leaves the credit slot blank, so either one reports a release whenever that happens. `Jr`, `KJ` and `JD` are a suffix and two sets of initials off a split name. An exact list after `normalise`, NOT a pattern: the first cut was a regex and it matched `Navarro` and `Molina` on `n/?a\b` |
| `yourself`, 24 entries | Rosalía, C. Tangana, Kaytranada, Willie Colón and twenty more hold `Producer` on their own records. The Friday radar already reports those, and the `yours` test cannot catch them here because it only sees BILLING |
| `thin`, 723 entries | credited on exactly one of these artists' records. One credit does not establish that an artist chose to work with somebody, and a recurring name is this radar's whole premise |

**`thin` counts every credited family, and counting production alone was tried
and measured down.** The reasoning for the stricter version was that `albums`
folds in engineering — 615 of the 1,538 are mixing and mastering engineers, and
nine mastering credits is not two productions. It cut the list from 785 names
to 409, and the 90-day backfill then showed what that cost: **Marta Salogni**
holds 9 credits on these artists' records and none of them is `Producer`
(she mixes for them), **Neal Pogue** 10 and none, and the two rows they
produced for other people — Salogni on Westerman's *L/C*, Pogue on Dylan
Cartlidge's *Lucky Shot* — are the two rows that best make this radar's case.
Both vanished.

The list and the verdict answer different questions, and the stricter version
conflated them. The list asks *is this person part of your artists' crew*,
where a mixing credit is evidence. `verdict` asks *did they produce this
particular record*, and that is decided per release from its own roles.
Filtering the list by the verdict's question discards exactly the people who
mix for your artists and produce for everybody else.

**The 90-day backfill**, 2026-10-31, `data/labels-backfill.md`: 212 labels,
`--credit production`, no cap, ~2,000 requests and about twenty minutes.
**34 releases reported** from 1,484 candidates — funnel 34 credit, 1,210
absent, 106 sideline, 119 yours, 12 writing, 3 reissue.

**2.6 a week**, against the Friday radar's measured 5.8 credited appearances.
21 distinct producers across the 34 rows. What it says about the knobs:

| | |
|---|---|
| `--per-label 2` costs 5 rows | 29 of 34 survive. Worth knowing WHICH: one label is an Altafonte distributor string carrying Gepe's whole campaign (4 rows, and a hand mute is the better answer), but `XL Recordings` holds 3 because James Ford produced three FONTAINES D.C. singles in the window — the radar working, not repeating. The cap is off by default for backfills and on for runs |
| engineering would be ~4× the rows | 106 sideline against 34 credit, so `--credit production,engineering` lands around 140 rows in 90 days, ~11 a week. That is the 73%-mixing number from the archived pipeline showing up again on a different corpus |
| 4 rows are the producer's OWN record | Dahi twice, Larry Harlow, Rello — they are billed on it, so it is a testable category. NOT implemented: whether "the producer you follow put out their own album" is news is a taste question, and guessing it here would be the unmeasured threshold this file exists to prevent |
| 3 reissues and 2 remixes were caught | by `is_reissue` and `is_remix`, both of which were written because the first runs printed one of each |

The rows are what the decision rests on, and the `works with` column is why they
read as recommendations: James Ford (works with ROSALÍA) → FONTAINES D.C. ×3,
Marta Salogni (ROSALÍA, Björk) → Westerman, Elliott Kozel (ROSALÍA) → Slow Pulp
and Soccer Mommy, Leon Michels (Kali Uchis) → Denzel Curry, Neal Pogue (Kali
Uchis, Karol G) → Dylan Cartlidge, Josh Crocker (Kali Uchis) → Gotts Street
Park. Not one of those artists is on the watchlist.

**One earlier measurement in this file was invalid and is withdrawn.** A first
90-day run reported 33 rows stopping at 2026-10-16, and a `data/labels_seen.json`
present when it started had suppressed 10 releases as already-reported. Every
run was `--dry-run`, and `--dry-run` was then verified not to write state, so
how that file came to exist is unexplained. The measurements above were taken
with `--state` pointed at a scratch path, which is what a measurement should
always do here.

**A mute was being undone.** Two rows reported Carin León releases, who is
muted in `data/favourites.json` as of `ef2709d`. The `yours` test read
`favourites.ids_for`, which drops muted entries, so the one artist deliberately
excluded from the Friday radar was reachable through his producer. Fixed to
read every entry carrying a Qobuz id.

## Consequences

**Easy.** Adding a producer costs nothing — `data/producers.json` is read, not
queried, so the whole fan-out this ADR rejected becomes a file edit. The same
goes for narrowing: `--credit production` against
`--credit production,engineering` is the 73%-mixing question asked at run time
rather than argued about in advance.

**Hard.** It is a scene filter, not a person index. A producer who works on a
label none of your artists use does not appear, and nothing in the output says
they were missed. The gate also rejects a real label that happens to share a
name with a watched artist — `Napa` is both a band on the watchlist and the
label name on their own releases, so it is excluded as a self-release.

**What it rules out.** Any claim that this radar has found "everything the
producers of your artists made". It has found what they made inside a label
set, which is a different and smaller claim, and the report says so by naming
the label on every row.

**Follow-ups**, kept here rather than in `todo.md`: that file is on the
`ranking` branch (D41) and a new link to it would dangle by construction.

- `record_scanned = False` means a release that credits nobody is re-read every
  week. Cheap now (one `album_detail` per candidate) and it is what makes
  adding a producer retroactive, but it is the first thing to measure if the
  run gets slow.
- `data/labels.json` is 254 hand-editable entries generated once. Nothing
  re-measures a catalogue size, so a label that grows past `MAJOR_CATALOGUE`
  keeps being scanned until `--discover` is re-run.
- The 1,538-person producer list comes from 20 discovery files, which is 20 of
  167 artists. The list is the input this is most under-provisioned on, and
  growing it is a `ranking`-branch walk, not a change here.
- Ranking those people by SELECTIVITY was tried and abandoned, 2026-10-31. The
  idea is sound — a producer with 1,070 credits is not evidence of anything and
  one with 12 is — and `core/discogs.py`'s `total_releases` on `ranking` is
  what measures it. But `cache/discogs` only covers 106 of the 923, and the
  number it returns counts a person's OWN discography where they are also a
  recording artist: Björk comes back at 2,713 releases and ranks as the least
  selective person in the file. Doing it properly needs the role-filtered
  Discogs fan-out that option 1 rejects.

**What would reopen it.** A reverse credit index with real dates — Qobuz adding
one, or MusicBrainz's producer relationships reaching usable coverage. Either
makes option 3 or 4 unnecessary and this radar an expensive way to ask a
question that could then be asked directly.
