# D21: An explanation names what the person did, and every clause is a row

- **Status:** Accepted
- **Date:** 2026-10-20
- **Where it lives:** [`core/explain.py`](../../core/explain.py),
  `NAMEABLE_CLASSES` and `nameable_roles` in [`policy.py`](../../policy.py),
  [`stages/co_artists.py`](../../stages/co_artists.py)

## Context

The co-artist list ([D14](D14-co-appearance-is-its-own-output.md),
[D20](D20-the-funnel-is-queryable.md)) was a table of names and counts. The
reason each name was there existed in `credits` — one row per (track, person,
role) — but reading it meant a second query per artist.

[roadmap.md](../roadmap.md) lists explanations as straightforward and free, and
they are the one thing a credits graph can do that a similarity model cannot: a
verifiable reason. "87% similar" cannot be checked by anybody.

## Options

1. **A template per row in the renderer** — "fans of X also like Y": no data
   needed, and nothing in it is checkable, which gives up the only advantage.
2. **Print the raw evidence** — roles, counts, titles, as columns: honest, and
   nobody reads a table of five columns per row as a reason.
3. **One sentence assembled from the stored facts**, with the facts kept beside
   it for anything downstream.

## Decision

Option 3. `core/explain.py` renders, `policy.py` decides what may be named,
`stages/co_artists.py` does the SQL and the printing — the layering this repo
already has.

Three rules, each of which is a test:

- **Only what the person did.** `nameable_roles` keeps performance and
  production and drops billing and engineering. MainArtist is *why they are in
  the list at all*, so naming it is circular, and "credited on 11 tracks
  (mastering engineer)" is true and useless.
- **No invented pronouns.** The store knows names, not genders, so the seed's
  name is repeated where a pronoun would go. A wrong guess misgenders a real
  person.
- **No overstating.** "e.g." only when there is more than one record to pick
  from, no plural for one of something, and a role clause only when both a role
  and a track count are present — half the evidence is not evidence.

## Evidence

30 of the 67 co-artists hold a nameable role on the records they share with
their seed; the other 37 are billing-only and get the shorter sentence with no
role clause. The strongest row in the corpus:

    Juan Falú is billed on 4 of Sílvia Pérez Cruz's records, credited on 13
    tracks (producer, guitar) - e.g. El Noi de la Mare (2024). Never played.

Each clause traces to a row: `co_artists.seed_records`, a `credits` count over
`co_artist_albums`, a `co_artist_albums` title, a `listens` count. Costs no
requests — the stage opens the store read-only and touches nothing else.

## Consequences

- An explanation can state something wrong with confidence, because Qobuz's
  roles are imperfect — [roadmap.md](../roadmap.md) notes mastering engineers
  filed as composers. The sentence is as true as the credit.
- It inherits the name problem: "Colors" (the *A COLORS SHOW* channel) and
  "Penelope Cruz" both get fluent sentences. Filtering those is
  [D13](D13-match-plausibility-on-read.md)'s unfinished business, not the
  renderer's.
- `--json` prints the same facts the sentence was built from, so a future radar
  or report re-renders rather than parsing prose.
- The role clause names the HIGHEST track count among the named roles, not one
  count per role, which slightly overstates a role held on fewer tracks than
  another. Worth splitting if anyone complains about a specific row.
