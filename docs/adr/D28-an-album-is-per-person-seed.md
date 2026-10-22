# D28: An album is a fact about a (person, seed) pair, finishing what D19 started

- **Status:** Accepted
- **Date:** 2026-10-22
- **Where it lives:** `person_albums` in `stages/load.py` — the
  `seed_qobuz_id` column and the primary key that leads with it.

## Context

[D19](D19-person-seed-is-the-grain.md) found that `albums`, `own_albums` and
`tracks` are facts about a **(person, seed)** pair and were being stored one row
per person, so the last discovery file won: Fred Kevorkian's 13 Drexler albums
became the 1 from a Pérez Cruz record. It created `person_seeds` at that grain
and fixed the counts.

It did not change `person_albums`, which stayed keyed `(person_key, album_id)`.
That key says "a person worked on an album once" — but the row carries
`provenance`, which is `own` or `guest` **relative to the seed being walked**.
Two seeds sharing one album therefore produce two rows that differ, and the key
forbids both.

`todo.md` had this on the list as a key that "rests on an empirical fact, not a
structural one", and `test_load.py` carried the measurement: zero disagreeing
pairs on the real corpus. The sixth seed ended that. Walking ROSALÍA alongside
Björk produced:

| album | person | Björk's walk | ROSALÍA's walk |
| --- | --- | --- | --- |
| Oral (Olof Dreijer Remix) | Noah Goldstein | `own` | `guest` |
| Oral (Olof Dreijer Remix) | Sega Bodega | `own` | `guest` |

Neither walk is wrong. It is Björk's record and ROSALÍA guests on it, and both
producers are credited on it in both discographies. `load.py` stopped with
`UNIQUE constraint failed`, and because it unlinks the store before building,
the previous store was already gone — so the pipeline had no queryable store
until this was fixed.

## Options

1. **Put the seed in the key**, the shape `person_seeds` and
   `co_artist_albums` already use.
2. **First-wins on (person_key, album_id)**, keeping one row per album. Cheap,
   and it is what D25 did for the derived `watchlist.json` rows — but here both
   rows are primary evidence from an EXACT step, and dropping one makes
   `provenance` mean "whichever seed was walked first", which is not a fact
   about anything.
3. **Drop `provenance` from `person_albums`** and read it from
   `person_seeds` instead. Removes the conflict by removing the column, but
   provenance is per album, not per (person, seed) pair — a person can be on
   two of a seed's records, one owned and one guested.

## Decision

**Option 1.** `person_albums` gains `seed_qobuz_id`, and the primary key is
`(seed_qobuz_id, person_key, album_id)`.

This is not a new judgement; it is D19's argument reaching the one table it
missed. The three tables that hold per-seed evidence now agree on their grain:
`person_seeds`, `co_artist_albums` and `person_albums`.

A second index, `ix_person_albums_person`, comes with it: the key leads with
the seed, so "every album this person worked on, across seeds" lost the prefix
it used to scan.

## Evidence

Measured on the six-seed corpus, 2026-10-22: **2 (person, album) pairs** where
two seeds disagree, both on the same album, and the disagreeing field is
`provenance` in both — never `title`, `date`, `tracks` or `roles`. That is the
whole of the conflict, and it is exactly the column that is per-seed.

After the change the store builds with all six seeds and `person_albums` holds
3,233 rows.

## Consequences

**The loud failure is kept and now protects something real.** Two seeds
disagreeing is legal; one seed's own walk writing the same (person, album)
twice still stops the build, because that would mean the loader produced data
its own schema forbids. `test_load.py` carries both cases.

What this makes easy: asking the funnel question per seed without a join to
`person_seeds` to find out whose record it was.

What it costs: a query that wants a person across all seeds must say so, and
`SELECT * FROM person_albums WHERE person_key = ?` no longer uses the primary
key. Hence the second index.

What would reopen it: nothing in this direction. The remaining grain question
is the opposite one — whether `people`'s summed `albums` across seeds is a
number anybody should read, which D19 already flagged and `person_seeds`
already answers.
