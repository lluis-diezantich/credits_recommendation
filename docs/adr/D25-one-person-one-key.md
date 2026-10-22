# D25: One person, one key — from a hand-edited file fed by a report, not from a lookup

- **Status:** Accepted
- **Date:** 2026-10-22
- **Where it lives:** `core/aliases.py`, `data/aliases.json` (un-ignored),
  `policy.alias_candidate` and `NAME_SIMILARITY`, `stages/discover.py`'s
  `collapse_credits`, `preferred_first` and `alias_report`, and the person-key
  mint sites in `stages/load.py`.

## Context

The identity model was `normalise(primary name)`, which folds case, accents and
whitespace — a label's typography and nothing else. It cannot merge a person
filed under two different names, and the credits are full of them. The last of
the three defects [D22](D22-co-appearance-is-the-second-pipeline.md)'s probe
found, and the one [D23](D23-ask-musicbrainz-who-the-seed-is.md) explicitly
left open.

It splits the people who matter most, because a producer who is also a writer
is credited one way for the production and another way for the publishing:

| | before | ranks |
| --- | --- | --- |
| Sjón | 4 people (12, 11, 9, 2 albums) | 4, 6, 8, 68 |
| Arca | 2 people (11, 7) | 5, 10 |
| Inflo | 2 people (13, 10) | 1, 2 |

A ranker reading `albums` would have taken each fragment as a separate
collaborator and ranked all of them below their true weight.

## Options

1. **MusicBrainz per collaborator, blanket.** `core.musicbrainz.names` already
   reads exactly the fields that answer this, and D23 proved the stance on the
   seed. 180–287 requests per seed.
2. **The same, budgeted to the top N by album count.** The known splits sit at
   ranks 1–10, so a budget of 12 covers them at 12 requests per seed.
3. **Auto-merge on name shape.** Token subset and near spelling, free, no
   requests, and it generalises to a seed nobody has walked.
4. **A hand-edited file, fed by a report.** `data/aliases.json`, the stance
   `data/favourites.json` already takes, with `stages/discover.py` printing the
   candidate pairs it did NOT merge so the file is filled from a walk's
   evidence rather than from memory.

## Decision

**Option 4.** The file holds the performing name and every other spelling seen
in a walked corpus; `core.aliases.person_key` is the only way a person key is
minted; `discover.py` ends a walk by printing what the file folded and what it
thinks might still be one person.

Both MusicBrainz options are blocked on the same fact rather than on cost (see
Evidence): a collaborator has no MBID anywhere on disk, so asking MusicBrainz
means a **search by name** — the fuzzy match `core.qobuz.find_artist` refuses on
principle, and `MATCH_PENALTY` exists because that class of match is already
47% of the candidate pool. Spending 12 requests a seed to buy a guess is worse
than spending none to buy a fact.

Option 3 was rejected as an *automatic* merge and kept as a *report*, which is
what `policy.alias_candidate` is. A wrong merge invents a collaboration that
nobody can check and that no query reveals, which is strictly worse than the
split it fixes — and two of the 48 candidate pairs are a person and the band
named after them, where merging would delete one of two billable acts.

## Evidence

**MBIDs are not available for crew.** Measured 2026-10-22 over
`data/favourites.json` and `listens.artist_mbid`, no requests: of the **top 12
people across all four seeds — 1 of 48** has an MBID on disk (Arca, because she
is also an artist with plays). `listens.artist_mbid` covers who you listen to,
not the producers and composers who made their records.

**The free signal that looked sufficient is not.** A performing name and a
legal name tend to be co-credited on one track in complementary roles, which
looked like a derivable rule:

| | co-credited tracks | roles |
| --- | --- | --- |
| Arca / Alejandro Ghersi | 14 | FeaturedArtist / Composer |
| Inflo / Dean Josiah Cover | 37 | Producer / Composer |
| Sjón / his legal name | **0** | Composer / Composer |

A real producer-and-writer pair is indistinguishable from the first two, and
Sjón fails the rule outright. So this is written down, not inferred.

**The report's own measurement**, 2026-10-22 over the four corpora, 48 pairs
out of 851 people: **27** subset-or-spelling, **19** `bare` (one side a single
surname — the `single_token_name` collision class), **2** an ensemble suffix and
therefore not reported at all. `NAME_SIMILARITY` is `TITLE_SIMILARITY`'s 0.92,
reused rather than re-derived: the pairs it catches differ by one character.

**What the file merged**, on 30 entries covering 72 spellings:

| | after |
| --- | --- |
| Sjón | **30 albums, rank 1** of Björk's graph |
| Arca | 15 albums, rank 4 |
| Inflo | **14 albums, rank 1** of Little Simz's graph |
| Carles Campi Campón | 22 albums over 2 seeds |
| people, four files | 892 → **851** |

## Consequences

**[D23](D23-ask-musicbrainz-who-the-seed-is.md)'s stated residue closed for
free.** "Simbiatu Abisola Abiola Ajikawo" and "Simbi Ajikawo" are in no
MusicBrainz field, so 9 of Little Simz's 29 self-credits survived that fix.
Pointing them at the seed's own performing name in this file makes
`discover.py` drop them as the seed rather than keep them as a collaborator —
the alias map and the seed-name set meet at the same key.

**Ranking is unblocked**, which was the point: `todo.md` step 3 can now read
`person_seeds.albums` without a person's weight being spread over four rows.

Two things the merge forced, both correctness fixes in their own right:

- **A track's credits are collapsed by person before anything is counted**
  (`collapse_credits`). Inflo holds Producer and his legal name holds Composer
  on 37 of the same tracks, so accumulating per parsed name would have counted
  each track twice and each role twice — inflating exactly the person the merge
  was written to fix. Roles stay in the order the credit string gave them, so a
  rebuild on another day produces the same file.
- **`watchlist.json` stopped being a second source for `person_albums`.** That
  table's primary key rested on two files agreeing about a title and a track
  count, which held only because `appearances` is a copy of the discovery pass.
  A merged person's counts changed and the derived file still held the old ones,
  which turned a redundant row into a failed build. Measured first: 191 rows,
  all 191 already present from a discovery file, none unique. One fact, one
  source — the loud failure the loader was given for a real disagreement is
  kept, and the fake disagreement is gone.

What this does not do:

- **It does not generalise.** Seed 5 arrives with its own splits and nothing
  merges them until somebody reads the report at the end of the walk. That is
  the cost that was accepted, and the report is what makes it a ten-minute job
  rather than a discovery.
- **19 pairs are reported and not merged**, on purpose — "Graham Massey" /
  "Massey", "Evelyn Glennie" / "Glennie", "Leiton" / "Martin Leiton". A single
  surname is right often enough to read and wrong often enough that nothing may
  act on it.
- **A split with no shared spelling is invisible.** Nothing relates "NELLEE
  HOOPER" to "N. Hills" in Björk's graph, and the report cannot raise what it
  cannot see. If a pair like that is ever confirmed, it goes in the file by
  hand like the three pen names did.
- **`normalise` is unchanged.** It still drops `ð` and `þ` rather than
  transliterating them, which is why "Sigurjón Birgir Sigurðsson" needed a file
  entry at all. Fixing it touches every key in the project — person keys,
  listens joins, title folding — and wants its own measurement and ADR.

What would reopen it: a cheap source of MBIDs for crew. If the resolvers ever
store one per person, option 1 becomes a direct lookup rather than a search,
and the objection in the Decision disappears.
