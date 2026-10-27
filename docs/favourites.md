# Favourites, and the release radar

`data/favourites.json` — the artists you actually play, with one id per source.
The radars read it instead of each hardcoding their own list.

    ./radars/qobuz.py --days 90        # what came out
    ./radars/qobuz.py --find "Name"    # the Qobuz id for a name, to paste in

## The list is hand-edited now

This file used to have two halves on two cadences: `stages/favourites.py`
turned names into ids monthly, and `radars/qobuz.py` turned ids into releases
weekly. [D41](adr/D41-main-is-the-radar-the-rest-is-a-branch.md) archived the
first half onto the **`ranking`** branch along with the profile it read, so on
main the watchlist is a committed file you edit by hand and the radar is the
only thing that reads it.

What that means in practice:

- **Adding an artist** is `./radars/qobuz.py --find "Name"` to get the id, then
  a new entry in `data/favourites.json` with `"qobuz_match": "manual"`.
- **Dropping one** is `"watch": false` on their entry, never a deletion — see
  [Two conventions](#two-conventions) for why.
- **An artist who will not release again** gets `"ended": "<date>"`. Nothing
  checks MusicBrainz for this any more; it was `--check-active` on the archived
  stage.
- **The list no longer grows by itself.** It is frozen at whatever the last run
  of the stage left, which is the accepted cost in D41 rather than an oversight.

The split was the whole design and the reason for it still holds: a name can
match nothing, the wrong person, or four plausible candidates — Qobuz has two
distinct artists called "Javier Colina". Paying for that ambiguity once rather
than every week is why resolution was ever separate, and a wrong match nobody
looked at would poison the radar quietly. Hand-editing keeps that property; it
just does the resolving with your eyes instead of a stage.

Everything the stage knew about doing this well — the review loop, the merge
rules, the measurement that put the bar at active months rather than play
counts — is on the branch, in this file's own history:

    git show ranking:docs/favourites.md
    git show ranking:docs/profile.md

Not to be confused with `data/watchlist.json`, which is the **collaborator**
list the credits pipeline built by reading who made records. That is also on
`ranking`. This is the other direction: who you listen to.

The radar records **everything it scanned**, not just what it printed, so a
first run absorbs the back catalogue past `--days` silently and never reports
it. That is deliberate and one-way — though the scheduled known-artist run
passes `--all` and records nothing at all, which is
[D32](adr/D32-the-known-artist-radar-reports-the-whole-week.md).

## What is in the file

| field | |
|---|---|
| `name` | as ListenBrainz credits it |
| `mbid` | MusicBrainz artist id — `radars/listenbrainz.py` watches on this |
| `qobuz_id` | `radars/qobuz.py` |
| `itunes_id` | `radars/itunes.py`. Always `null`: nothing resolves Apple ids, so that radar falls back to its own built-in list |
| `plays` | largest listen count any window reported |
| `rank`, `ranks` | best rank, and the rank in every window it charted in. `null`/`{}` means it charted in none this run |
| `qobuz_match` | `exact`, `ambiguous`, `manual`, `not_found`, `no_exact_match` |
| `watch` | absent means watched. `false` mutes — **your** decision |
| `ended` | a death or split date from MusicBrainz, or `true` when the date is unknown. A **fact**, not a decision |

## Who has stopped releasing

`--check-active` asks MusicBrainz one question per watched artist —
`life-span.ended` — and stamps the answer in. On the 2026-10 watchlist it found
six the radar had been querying every week:

    died   Frankie Ruiz             1998-08-09
    died   Fela Kuti                1997-08-02
    died   Enrique Morente          2010-12-13
    died   Joe Arroyo               2011-07-26
    split  Extremoduro              2019-12-17
    split  Los Abuelos de la Nada   1988

**MusicBrainz, not the release dates.** The obvious alternative — "has anyone
released nothing lately" — fails on exactly these artists, because a dead one
keeps putting out compilations and remasters. MusicBrainz states it outright and
says which it was. What it *cannot* say is whether a living artist who never
formally stopped has quietly finished; for that the release dates are still the
only signal, and nothing reads them yet.

**`ended` is not `watch`, on purpose.** A mute is yours and you can lift it; a
death is not yours to lift. Both skip the artist in `favourites.ids_for`, which
is the single place all three radars read, so one field refreshes without
disturbing the other. Two of these six are `core` in the profile — Fela Kuti and
Extremoduro are genuinely played, and genuinely never releasing again. That is
the fact a listening history can never contain.

One request per artist at 1.2s, cached in `cache/musicbrainz/` effectively
forever, since a death date does not change. `--refresh-active` re-asks. Four
watched artists have no MBID and are reported rather than assumed active: an
unanswerable lookup must not read as a yes.

## Two conventions

**`"watch": false` mutes without deleting.** Delete an entry and it is just a
name nobody recognises, so the next run adds it straight back from the top
lists. The entry has to stay for the exclusion to stick. Absent means watched,
so the field only ever appears on the exceptions. The archived resolver used
the same convention for people.

**`"qobuz_match": "manual"` means you chose this id**, and nothing was allowed
to re-resolve it — not `--refresh`, which existed to re-ask autosuggest rather
than to overrule you, and not the review loop. It is the flag to set on any id
you paste in by hand. On main nothing re-resolves anything, so it is a note to
your future self rather than a guard.

The archived stage merged rather than overwrote: a run updated stats and added
new names, and artists who dropped out of every window kept their entry with
`rank: null` — falling off a top-100 this quarter is not a reason to stop
watching someone. The `rank` and stats fields still in the file are from the
last such run.

## Decided on purpose

**It is the one file in `data/` that is committed.** `.gitignore` excludes
`data/*.json` because it is regenerated output, with `!data/favourites.json` as
the exception: the manual ids and the mutes exist nowhere else, so regenerating
it loses work rather than time. Under 100 KB, slow-moving, worth a diff.

**It read the live stats API, not the listen export.** The export is a
point-in-time ZIP and reading it needs pandas, which would end this project's
no-dependencies property. What that lost is name merging, so two spellings of
one artist can both appear — mute one.

**The relevance filter lived in `profile.py`**, which is on `ranking`. The
condition this section originally set — *"any replacement has to measure
breadth from something live"* — was met there: one stats request a month,
appended to a durable store, with the verdict being active months rather than a
play count. `git show ranking:docs/profile.md` has the measurements. What
follows is why the first attempt failed, which is still the reason the bar was
set where it was.

**The first relevance filter was tried and removed.**
Counting distinct tracks per artist out of `music.db` does separate one song on
repeat from an artist you follow: measured on a real 321-artist file, 19 played
on two tracks or fewer, and a collaboration credits a play to every artist on
it, which is how a featured name reaches a top-artists list at all. It was
removed anyway, because `music.db` is built from a point-in-time export, so the
number is stale by construction — it already missed five months and 29 of 321
artists outright, and would decay further every week with nothing to show that
it had. A relevance filter whose own freshness cannot be checked is worse than
none. Any replacement has to measure breadth from something live.

## Gotchas

**Muting is the only way to shrink the list.** Narrowing `--range` or `--count`
does not drop anyone: artists already in the file survive as leftovers and stay
watched.

**Fresh is per storefront.** `--store es-es` is a different catalogue, not a
different view of one. The same artist returned 69/66/69 releases across three
Apple storefronts.

**Release types are inferred from track count**, because this Qobuz endpoint
returns no type. A six-track album is labelled EP.

**Reissues can surface as new.** `release_date_original` is preferred, so
remasters usually keep their old date, but a catalogue row carrying only a
stream date will look new. The `(Remastered)` / `(Deluxe)` suffix is kept in
the title, so it is recognisable rather than filtered.

**A failed artist is skipped, not fatal.** 5xx is retried three times; anything
still failing warns, and the run continues. Nothing is recorded as seen for
that artist, so a later run reports it.
