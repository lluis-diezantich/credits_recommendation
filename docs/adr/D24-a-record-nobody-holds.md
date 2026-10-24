# D24: A record nobody holds is not a collaboration, and some billings are not artists

- **Status:** Accepted
- **Date:** 2026-10-22
- **Where it lives:** `policy.album_provenance` (the `"compilation"` label),
  `policy.MADE_TOGETHER` and `policy.NOT_ARTISTS`, `stages/discover.py`'s
  `album_billing`, and the read-side filters in `stages/co_artists.py`.
  Columns: `co_artist_albums.provenance`, `seeds.albums_compilation`.

## Context

[D21](D21-explanations-name-what-the-person-did.md) gave every co-artist a
fluent sentence built from stored rows. That made the list's junk worse rather
than better: a wrong row now arrives with evidence attached and reads as the
most convincing thing on the page. `todo.md` put filtering it the first item in
the plan, and blocking everything user-facing, for that reason.

Two kinds of junk, measured on the four-seed corpus of 2026-10-22. They are
listed by size, which is the opposite of the order they were noticed in:

**A various-artists record read as 20 separate guest spots.** *Army Of Me* is
Björk's 2005 remix and covers album: 20 billed tracks, a different remixer
holding each one, Björk filed as composer throughout.
[D14](D14-co-appearance-is-its-own-output.md)'s test is whether the seed holds
`MainArtist` across the album, so she held none of it and the record labelled as
a guest spot — twenty times over, once per remixer. Every one of them became an
artist whose own record she had appeared on. That is **20 of her 35
co-artists**, and the same 20 are **20 of the 147 people** in her crew graph.

`policy.OWN_ALBUM_MAIN_SHARE`'s comment had already named this case as the one
that would tell two floors apart, and recorded that no corpus contained one.
Björk's does.

**Billings that are not an artist.** "Colors" is the *A COLORS SHOW* channel,
billed on "Capitana - A COLORS SHOW". "Penelope Cruz" is an actor, reading on
Residente's "313" beside Sílvia Pérez Cruz. Both are genuinely billed, on a
track the seed is genuinely on, which is every piece of evidence this project
collects about them. "K.U.K.L." and "The Sugarcubes" are Björk's own former
bands — the seed under another name, which is the defect
[D23](D23-ask-musicbrainz-who-the-seed-is.md) fixed for her solo credits and
not for these.

## Options

1. **A count of co-billed artists.** Drop a guest record that bills many
   artists. Free and structural, but the threshold has no room: Pérez Cruz's own
   "Toda la vida, un día" bills 11 guests and is real, and "WE PRAY" bills four
   and is real. Any floor low enough to catch a 20-track compilation is low
   enough to cut a four-way single if that single were ever labelled guest.
2. **The top billed SHARE, against the floor that already exists.** Ask who
   holds the most of the record rather than how many names are on it. A
   compilation has a different holder on every track, so the top share collapses;
   a four-way single has four artists each holding the whole of it.
3. **A hand list for all of it**, compilations included, by album title.
   Needs no measurement and does not generalise: the next seed's compilation is
   a title nobody has seen.
4. **An external source for the non-artist billings** — MusicBrainz says
   whether an entity is a Person or a Group, and says `member of band`.
   Principled, and it does resolve the two bands in theory.

## Decision

**Option 2 for the compilations, option 3 for the rest.**

`album_provenance` takes the top billed count as a third argument and returns a
fourth value, `"compilation"`, when no artist holds half the billed tracks. It
is checked before the seed's own share, because on *Army Of Me* the seed's
share is zero and `"guest"` is the wrong answer rather than a near one. The
argument is optional, so a discovery file written before this keeps the label it
had.

`policy.NOT_ARTISTS` is a hand list of four normalised keys with a reason
written beside each, the same stance `data/favourites.json` takes where nothing
can be derived. It is kept to names seen in a walked corpus so it stays
checkable, rather than being a guess at what the next seed will turn up.

> Superseded in part by [D35](D35-the-seeds-own-band-is-its-own-reason.md):
> the four keys are now two lists, because two of them are the seed under
> another name rather than billings that are not artists, and the drop line
> said the wrong thing about them. The compilation rule above is unaffected.

Both apply **on read**, in `stages/co_artists.py`, which is
[D15](D15-filters-before-ranking.md)'s stance: the rows stay in the store with
their provenance, so a label that turns out to be wrong costs a different
`WHERE` clause and not a rewalk.

Option 4 was measured and rejected for now, not on principle. MusicBrainz does
state both bands as `member of band`, on the request `core.musicbrainz` already
makes, so the data is free — but `normalise` keeps the periods in "K.U.K.L."
while MusicBrainz files the band as "KUKL", so the keys do not meet. A name key
that strips punctuation touches every match in the project and wants its own
measurement; two names on a hand list do not justify that yet.

## Evidence

Measured 2026-10-22 over `cache/credits` for all four seeds, no requests:

| | |
| --- | --- |
| albums with any billing | **258** |
| albums where no artist holds half the billed tracks | **1** — *Army Of Me*, at 5% |
| next lowest album | *Family Tree*, at **91%** |

One case, and a 5%-to-91% gap around the floor, so this reuses
`OWN_ALBUM_MAIN_SHARE` rather than introducing a second number to calibrate.
The exact value is as untested here as it is for own/guest, and for the same
reason: nothing in the corpus sits near it.

What the two filters remove from the list, before and after:

| | before | after |
| --- | --- | --- |
| co-appearances | 121 | **97** |
| unheard artists shown | 73 | **51** |

24 rows: 20 off *Army Of Me*, and the four hand-listed billings.

## Consequences

The crew graph is fixed by the labelling alone and needed no second change:
`policy.seed_albums_of` reads `own_albums`, and a compilation is counted in
neither direction, so the 20 remixers can no longer be promoted as people who
worked on a Björk record.

Ranking across seeds — `todo.md` step 3 — can now count `seed_records +
their_records` instead of `albums`, which was its stated input and was inflated
by exactly this. `stages/co_artists.py` and `docs/store.md` both order on it now.

What this does not do:

- **It merges nothing.** The collaborator-alias defect is untouched: Sjón is
  still four people, Arca two, Inflo two. That is the remaining identity fix and
  it still blocks step 3.
- **The hand list does not generalise.** Seed 5 will arrive with its own
  channel or actor, and nothing in the code will notice. The *A COLORS SHOW*
  class is at least predictable — a session brand billed as an artist — and if
  three more turn up, the shape of a rule is a session's name appearing in the
  album title.
- **`people` still holds the 20.** They are in the store, labelled, reachable
  by a query that asks for them. Only the gate above stops them.
- **Compilations are counted and not explained.** `seeds.albums_compilation`
  says how many a seed has; nothing says which, beyond
  `co_artist_albums.provenance`.

What would reopen it: a seed whose discography contains a genuine
collaboration album that no single artist holds — a duo record filed with both
names on alternating tracks would do it — which is the case the 5%-to-91% gap
says does not exist yet.
