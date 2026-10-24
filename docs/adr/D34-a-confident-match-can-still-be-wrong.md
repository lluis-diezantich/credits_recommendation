# D34: A catalogue that predates the artist is flagged, and an exact match is not exempt

- **Status:** Accepted
- **Date:** 2026-10-23
- **Where it lives:** [`policy.py`](../../policy.py)
  (`MATCH_SPAN_SLACK_YEARS`), [`core/musicbrainz.py`](../../core/musicbrainz.py)
  (`began_year`, `predates`), [`stages/favourites.py`](../../stages/favourites.py)
  (`--check-matches`, and the `review()` gate)

## Context

`data/favourites.json` resolves a name to a Qobuz artist id, and
[D13](D13-match-plausibility-on-read.md) handles a match that *looks* shaky.
The failure this is about is the opposite one: a match that looks certain and
is not.

"ZOO" resolved to Qobuz id 62584, which carries 174 albums by several unrelated
acts across five decades. The Friday radar reported English-language singles
for a band that records in Valencian, and the only thing that caught it was a
human reading the issue and being suspicious. `--review` could not have: it
skips `exact` and `manual` rows by design, and 150 of 172 entries are `exact`.

So the watchlist had 150 entries that nothing would ever re-examine, and a
wrong one is not a one-off error — it poisons every weekly issue until noticed.

A name comparison cannot help here. Qobuz id 62584 really is called "Zoo". The
discriminating evidence is the catalogue.

## Options

1. **Compare release titles with MusicBrainz release-groups.** The strongest
   signal, and it catches same-era collisions too. Needs `inc=release-groups`
   on the artist lookup, which changes the cached document shape and means
   refetching all 154 artists at 1.2s each.
2. **Flag an implausible album count.** Free, and useless: Zoot Sims genuinely
   has 1,016 albums.
3. **Compare the catalogue's start against `life-span.begin`.** Already in the
   cache that `--check-active` filled, so no new MusicBrainz request at all. A
   catalogue that starts before the artist existed is a contradiction between
   two stated facts rather than a heuristic about taste.

## Decision

Option 3. One Qobuz request per artist — the same cost as a radar run — and
zero new MusicBrainz requests.

It **flags and does not reclassify**, following
[D5](D5-flag-rather-than-reclassify.md). `qobuz_match` keeps whatever the
resolver decided, because the resolver was not wrong about what it did; the
doubt lands in a separate `suspect` field. The two are kept apart for the same
reason `ended` and `watch` are: one is a measurement, the other is a verdict.

`review()` then treats `suspect` as overriding the exact/manual skip. Without
that the flag would be inert, which was the whole complaint about the existing
"watched with no MBID" line.

## Evidence

Measured 2026-10-23 over the 111 watched artists that have both a MusicBrainz
begin year and a dated Qobuz catalogue. 109 showed no contradiction. Both that
did were genuine, and neither was a wholly wrong id — each was a correct id
with a second artist merged into it:

| | id | begin | catalogue starts | what is in there |
|---|---|---|---|---|
| CHUWI | 4244764 | 2020 | 2019-08-14 | "Что В Твоих Глазах", a Russian CHUWI |
| Y La Bamba | 737125 | 2008 | 1996-07-04 | Navidad Negra, Tanto Amor — Colombian cumbia |

`MATCH_SPAN_SLACK_YEARS = 0` follows from that distribution: the two
contradictions are 1 year and 12 years, so a single year of slack would already
have hidden CHUWI, and there is no false-positive noise to buy off. Compared
year to year, because `begin` is often a bare year and month precision would
flag a debut released in the founding year.

18 of 154 cached artists have no begin date and 3 watched artists have no MBID
at all. Both are reported as unchecked rather than counted as clean.

## Consequences

- **A confidently wrong id is now findable** without reading a weekly issue
  carefully, which is the only thing that found the last one.
- **A flag is not a fix, and for a merged id there may be no fix.** Both
  artists found here are the *right* artist plus a stowaway, so re-picking the
  id cannot help. Filtering releases within an id is a different feature, and
  this ADR does not propose it — see [../../todo.md](../../todo.md).
- **It runs by hand.** `--check-active` has the same shape and the same
  question hanging over it; both belong in a monthly job the day
  `profile-month.yml` grows one.
- **Same-era collisions are still invisible.** Two artists of the same name who
  both started in 2015 produce no contradiction. Option 1 is what would catch
  those, and this decision does not rule it out — it is strictly cheaper and
  can be added beside it.
- **What would reopen it:** a false positive. One reissue carrying its original
  recording date as `release_date_original` would do it, and the answer then is
  slack in `policy.py`, measured again, not a change here.
