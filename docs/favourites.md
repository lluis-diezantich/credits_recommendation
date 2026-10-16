# Favourites, and the release radar

`data/favourites.json` — the artists you actually play, with one id per source.
The radars read it instead of each hardcoding their own list.

    ./stages/favourites.py --user <listenbrainz-user>    # build or refresh it
    ./radars/qobuz.py --days 90                          # what came out

Not to be confused with `data/watchlist.json`, which is the **collaborator**
list the credits pipeline builds by reading who made records. This is the other
direction: who you listen to.

## Two halves, two cadences

The split is the whole design, so keep it.

| | | when | cost |
|---|---|---|---|
| `stages/favourites.py` | names → ids. Lossy, needs your eyes once. | monthly, or when you notice a gap | 1 ListenBrainz request per window, 1 Qobuz search per **new** name |
| `radars/qobuz.py` | ids → new releases. Cheap, idempotent, schedulable. | weekly | 1+ Qobuz request per watched artist |

Resolving is separated because a name can match nothing, the wrong person, or
four plausible candidates — Qobuz has two distinct artists called "Javier
Colina". You pay for that ambiguity once instead of every week, and a wrong
match nobody looked at would otherwise poison the radar quietly.

## Running it

    # 1. build or refresh the list (keeps every id you fixed by hand)
    ./stages/favourites.py --user lluisdiezantich --count 100

    # 2. fix whatever did not resolve cleanly
    ./stages/favourites.py --review

    # 3. stop watching someone
    ./stages/favourites.py --mute "Bobby Cruz" "Feli Colina"

    # 4. the actual point
    ./radars/qobuz.py --days 90

Step 1 defaults to the `all_time` window. `--range week,month` unions several,
`--range all` takes all nine; each extra window is another hundred-odd artists
deeper into the tail. `--count` is **per window, not in total**.

Step 2 needs no `--user` and makes no ListenBrainz call. For each open row it
prints Qobuz's candidates with album counts, marking the id the entry already
holds, and reads one answer: a number picks, `#41620` enters an id by hand and
confirms it against Qobuz before writing, `/text` searches a different
spelling, `s` skips, `m` mutes, `q` saves and quits. Ctrl-C aborts without
writing.

Step 4 records **everything it scanned**, not just what it printed, so the
first run absorbs the back catalogue past `--days` silently and never reports
it. That is deliberate and one-way.

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
| `watch` | absent means watched. `false` mutes |

## Two conventions

**`"watch": false` mutes without deleting.** Delete an entry and it is just a
name nobody recognises, so the next run adds it straight back from the top
lists. The entry has to stay for the exclusion to stick. Absent means watched,
so the field only ever appears on the exceptions — `stages/resolve_qobuz.py`
uses the same convention for people.

**`"qobuz_match": "manual"` is never re-resolved**, including by `--refresh`.
That flag exists to re-ask autosuggest, not to overrule you. `--review` skips
these rows too.

Everything else is merged, not overwritten: a run updates stats and adds new
names, and artists who drop out of every window keep their entry with
`rank: null` — falling off a top-100 this quarter is not a reason to stop
watching someone.

## Decided on purpose

**It is the one file in `data/` that is committed.** `.gitignore` excludes
`data/*.json` because it is regenerated output, with `!data/favourites.json` as
the exception: the manual ids and the mutes exist nowhere else, so regenerating
it loses work rather than time. Under 100 KB, slow-moving, worth a diff.

**It reads the live stats API, not the listen export.** The export is a
point-in-time ZIP and reading it needs pandas, which would end this project's
no-dependencies property. What that loses is `aliases.yml` name merging, so two
spellings of one artist can both appear — mute one.

**There is no relevance filter, and the obvious one was tried and removed.**
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
