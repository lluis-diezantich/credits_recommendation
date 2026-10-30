# D42: The known-artist radar also reports what its artists are CREDITED on, found by searching the track index

- **Status:** Accepted
- **Date:** 2026-10-30
- **Where it lives:** [`../../core/appearances.py`](../../core/appearances.py),
  [`../../core/credits.py`](../../core/credits.py) (cherry-picked from
  `ranking`), `search_tracks`/`album_detail` in
  [`../../core/qobuz.py`](../../core/qobuz.py), `appearances()` in
  [`../../radars/qobuz.py`](../../radars/qobuz.py), the second table in
  [`../../radars/report.py`](../../radars/report.py), `Release.because` in
  [`../../core/radar.py`](../../core/radar.py)

## Context

`a force`, on Miguel Atwood-Ferguson's *Ananta: Spirit Of Coltrane*, came out
on 2026-10-30 and credits aja monet as `FeaturedArtist, SpokenWord`. She is
324 plays deep in `data/favourites.json`. It did not appear in issue #33, and
nothing was broken: Qobuz files a release under an artist only when they are
billed on the **album**, so `artist/get` returns nine releases for her and that
album is not one of them. `core/qobuz.py:artist_releases` then drops guests
again on the way past. The radar answers "what did these artists release",
and the thing it misses is the thing a listener would most want — the record
they would never have looked for.

Two id-based ways out were tried first and both are incomplete:
`artist/get?extra=tracks` returns 32 tracks for her, `extra=tracks_appears_on`
returns 3 (compilations only), and neither includes the feature. There is no
reverse credit index in the API.

## Options

1. **Widen `artist_releases` to keep guest credits.** One line: stop filtering
   on the watched id. Costs nothing and finds nothing — the album is not in the
   response to filter.
2. **Scan the store's new-release feed and read credits per release.**
   `album/getFeatured?type=new-releases-full` is 425 albums for `gb-en`, and
   *Ananta* is in it. But that feed is an editor's shortlist: 40–47 albums per
   release day for an entire storefront, so a release crediting a watched
   artist that the editors ignored is invisible, and the coverage is unmeasured.
3. **Search the track index for each watched artist's NAME, then read each
   candidate album.** The only path that actually reaches the track. Costs a
   fuzzy name match, which drags in composers, tribute acts and anything
   sharing a substring, so most of the work is discarding.
4. **A fourth radar, with its own workflow and issue.** Keeps Friday's issue
   untouched, at the price of two issues to read and a second place to dedupe
   the overlap.
5. **Revive the `ranking` branch.** It answers a different question — who else
   should I hear, from back-catalogue credits — and brings `policy.py`, the
   seeds, the resolvers and the ranking with it.

## Decision

Option 3, inside the existing radar and the existing issue (so not 4).

`track/search?query=<name>` is the reverse lookup the catalogue does not offer.
Every candidate it returns then costs one `album_detail`, which answers in one
request the two questions the search row cannot: the real release date and the
per-track credits. Five decisions stand between a search hit and a printed row,
and all five live in `core/appearances.py` as pure functions with tests, not in
the fetch loop:

| outcome | what it means |
| --- | --- |
| `absent` | the name is not in the credits — the index matched something else |
| `writer` | credited only as composer/lyricist/producer: every cover |
| `compilation` | a real credit, billed `Various Artists` |
| `retrospective` | a real performance on a repackage of old recordings |
| `redelivery` | the real date is outside the window |
| `duplicate` | the same record under a second Qobuz id |
| `appearance` | news |

Three shapes of the implementation are load-bearing:

- **The role test is a DENYLIST of writing and production roles, not an
  allowlist of instruments.** That is the lesson `core/credits.py` already
  records: 65 of the 124 role tokens in the Drexler corpus are in no table and
  nearly all are genuine (Spanish Guitar, Berimbau, Theremin). An allowlist
  discards real credits — Yussef Dayes' `Drums` on Daley's *Strange Nature* —
  to catch a dozen bad ones.
- **One Batch per ARTIST, not per call.** The runner counts a Batch as a call
  and reports `fetched` of `watching` as artists, so yielding the second pass
  separately made a 128-artist run say "from 256 of 128 artists".
- **`Release.because` carries the credit into the report**, and
  `radars/report.py` prints appearances as their own table. "Miguel
  Atwood-Ferguson — Ananta" in an issue about artists you follow is a stranger
  without it, and the headline count stays about what the watched artists
  released, because "9 new releases from 128 artists" has meant that in every
  issue so far.

`core/credits.py` is **cherry-picked from `ranking`**, not rewritten. This is
the case `CLAUDE.md` warns about — two branches holding one file — and it was
taken with that cost open-eyed, because `parse_performers` is the function
whose own docstring records that writing it twice is what created
`core/names.py`. A third implementation was the worse trade. D41 is **not**
superseded: `stages/`, `policy.py` and the ranking stay archived, and what came
across is one pure parser, not the pipeline.

## Evidence

Backfilled over 42 days and 130 watched artists on 2026-10-30, against the
live `gb-en` store. 2467 requests.

| stage | count |
| --- | --- |
| `track/search` calls | 211 |
| candidate albums in window, by the search payload's date | 1163 |
| survive the real-date check in `album_detail` | 297 |
| — already visible to pass one | 59 |
| — new, credit-level | 238 |
| of those, holding a performance role | 142 |
| on a named album artist, not `Various Artists` | 51 |
| distinct albums | 45 |
| after dropping repackages | ~31 |

**≈5 genuine appearances a week**, against the 9 releases pass one reports. A
weekly run is ~211 searches plus ~170 candidate reads: **~380 requests, about
85 seconds** at the existing 0.22s pause, against 128 before. The first
production run came in at 128 searches plus 148 reads — 276 requests, under the
estimate, because a one-week window admits fewer candidates than a sixth of a
six-week one.

Three numbers decided a rule rather than describing one:

- **`writer` was 96 of 238.** Every piano, karaoke and cumbia version of "Tu
  Falta de Querer" credits Mon Laferte as `ComposerLyricist` and nothing else;
  "Les" came back seven times. The role denylist is what makes this pass
  usable at all, and without it precision was 1 in 17.
- **`Various Artists` was 91 of 142 performance credits.** Dropped on
  `album/get`'s singular `artist` field, because `artists` comes back EMPTY on
  a compilation — reading the wrong one made `Canciones para recordar` (32
  tracks, Various Artists) print as a Jorge Drexler album in the first live
  run of this pass.
- **A `>= 15 tracks` rule was tried for repackages and withdrawn.** It threw
  away three genuine guest spots on genuine albums — Califato ¾ on *Papela
  Funk* (20 tr), Kishi Bashi on *Chrysalis* (16 tr), Rawayana on *MudaH*
  (19 tr). Only title patterns survived. A long album is a long album.

What is **not** measured, and is the honest limit of the above: the ~31 was
classified by reading the list, not by a rule, so it is an estimate of what a
good week looks like and not a precision figure. One 6-week window is also one
window; the funnel is printed in every issue precisely so these numbers get
re-measured rather than quoted.

### The first production run

The finished radar, 128 artists, `--days 6`, live `gb-en`, 2026-10-30:

    12 new releases  (9 from pass one, 3 appearances)
    Credit pass: 4 appearance, 9 writer, 19 compilation, 1 retrospective,
                 100 absent, 3 redelivery, 2 duplicate, 10 unreadable

So 148 candidates read for 3 printed rows, and the issue grew from 9 to 12.
Four points the sample settles, and one it does not:

- **`absent` is 100 of 148** — two thirds of the cost is the name search being
  a name search. Expected, and it is the price of the only path that reaches a
  track-level credit at all.
- **`compilation` at 19 is now the biggest real category**, ahead of `writer`
  at 9. Over six weeks it was the other way round. One week is too short to
  call that a trend, which is the reason the line is printed.
- **`unreadable` at 10** is higher than the backfill implied and is unexplained
  — `album/get` failing on 7% of candidates. Worth watching; it costs nothing
  but a missed row, and `core.http` has already retried by then.
- **`appearance` 4 against 3 printed**: the fourth was dated after the run and
  dropped by D33, which is the runner doing its job.
- **One visible false positive.** Gwen Stefani's *You Make It Feel Like
  Christmas* printed for Mon Laferte's `FeaturedArtist` credit on "Feliz
  Navidad". The record is from 2017; this is its deluxe reissue, and **no
  field in the payload says so** — `release_date_original`,
  `release_date_stream` and `release_date_download` all read 2026-10-30 and
  the copyright reads 2026. The only tell is `version: "Deluxe Edition –
  2025"`.

  No rule was added for it, deliberately. A deluxe edition is often exactly
  where a NEW collaboration appears, so suppressing the word would cost the
  finds this pass exists for, and one occurrence in one week is not the
  measurement that should decide it. It is left visible and countable instead.

## Consequences

- **The issue gains a second table**, and the `credit candidates:` line under
  it. The first table and the headline are unchanged, so an issue from before
  this reads the same way as one after it.
- **A run costs about three times the requests.** Still well inside the
  workflow's budget, and `--no-credits` restores the old behaviour exactly.
- **The index caps at 1000 results per name and ignores every spelling of
  `order`**, so a very prolific artist's newest credit could in principle sit
  past the cap — Björk and Santana both report exactly 1000. Unmeasured.
  Nothing depends on it: pass one still guarantees their own releases.
- **A name search is a name search.** The `absent` bucket is the false
  positives being thrown away, and it will never be empty. The two in the
  sample both matched a composer called "Ajá John Arias".
- **`core/credits.py` now exists on both branches.** A fix to it on `main`
  will not reach `ranking`, and reviving that branch means a merge that
  includes this file. Accepted, and it is the second entry on D41's divergence
  list rather than a new kind of problem.
- **`Release.because` is on the shared `Release`**, so `ranking`'s copy of
  `core/radar.py` is one field behind. Additive and optional: absent from
  `row()` when None, and no other radar sets it.
- **What would reopen this:** the `appearance` count staying near zero for a
  month, which would mean the pass is not earning its requests; or the
  `writer` bucket shrinking relative to `appearance`, which would mean the role
  denylist has drifted and wants re-reading against a fresh sample.
