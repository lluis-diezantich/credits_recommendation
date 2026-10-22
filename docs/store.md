# The store

`data/music.db` — every JSON already on disk, in one queryable file.

    ./stages/load.py

That is the whole setup. It fetches nothing: unplug the network and it still
runs. ~15 seconds, mostly the listen export.

## What it is, and what it is not

It **is** a reshaping of what you already have. Most of what the README lists as
plausible is a join, not a model — "people who appear in 3+ discovery graphs",
"artists who record the same writers", "did the graph built on listens to 2024
contain the artists adopted in 2025". Each is one SQL statement here and about a
page of Python otherwise.

It is **not** new data. Nothing in it was fetched. In particular there is no
`language` column, because no source in this project carries one — Qobuz's raw
`track/search` response has no language field (checked), and neither does
Discogs. Getting language means new requests. See *Where new data lands* below.

It is **derived and disposable.** Rebuilt from scratch on every run, gitignored,
never migrated. `cache/` stays the source of truth for the reason
`writing.py:145` gives: `track/search` is not stable between runs, so the cache
is what makes any of this reproducible. Deleting `music.db` costs one rerun.
Deleting `cache/` costs the corpus.

## Engine

Stdlib `sqlite3`, always, even with DuckDB installed. The store adds no
dependency of its own — `requests` is the project's only one, and the store
needs no network — and sqlite is not a consolation prize here —
it builds these 216k rows in **2.0s** where DuckDB takes **68.7s**, because
DuckDB is columnar and inserts rows one at a time.

    ./stages/load.py --engine duckdb     # works, but 69s and a native .duckdb file

To use DuckDB — and it is worth using — keep sqlite for the build and attach the
result: 0.03s aggregates over the 190k listens, plus struct access into the raw
JSON and Parquet for the dump era. `docs/duckdb.md` has the measured workflow.
Every query below runs unchanged on both engines.

    ./stages/load.py --no-listens        # skip the 190k-row export
    ./stages/load.py --summary           # row counts of an existing DB, no rebuild

## Opening it

    sqlite3 data/music.db                            # if you have the CLI
    python3 -c "import sqlite3,sys; [print(r) for r in sqlite3.connect('data/music.db').execute(sys.argv[1])]" "SELECT ..."

Or in a notebook, which is where this actually gets used:

    import sqlite3, pandas as pd
    con = sqlite3.connect("data/music.db")
    pd.read_sql("SELECT * FROM songs WHERE tier = 'authored'", con)

## Tables

Row counts below are from the 2026-10-20 build and drift as the pools are
regenerated. `meta` is authoritative.

    meta                     provenance: which file each table came from, row counts, dates

    seeds                4   one row per seed walked - the TOP of the funnel:
                             releases, albums_own/albums_guest/albums_compilation,
                             people, co_artists
    co_artists         121   who a seed has made a record WITH, per seed. 59%
                             already-played against the crew graph's 13% (adr/D14)
    co_artist_albums   143   the records behind each co-appearance - own, guest,
                             or compilation, which is nobody's (adr/D24)

    people             835   the credit graph, one row per person, merged from 5 places
                             albums/own_albums/tracks are SUMMED over seeds.
                             person_key folds the alias map, so Sjon is one row
                             and not four - adr/D25
    person_seeds       565   one row per (person, seed) - the grain those counts
                             are really measured at. Read this, not people.albums,
                             for "how embedded in ONE seed's catalogue"
    person_names       281   spelling variants
    person_sources     412   which file contributed each person (multi-seed joins)
    person_classes     396   production / engineering / writing / billing / performance
    person_roles       923   role + policy's role_key, role_class, role_weight, count
    person_albums      777   which of the seed's albums they appear on
    person_edges       123   worked_with edges from the Discogs path

    releases          7860   pool.json + pool_discogs.json, keyed (album_id, source)
    release_artists  12023   billed artists per release

    songs              257   from writing_*.json, one row per folded song
    song_titles        345   title variants, including cross-language retitles
    song_roles         442   writing roles held
    song_tier_votes    265   per-recording tier votes (read these, not `tier` alone)
    song_co_composers  295   everyone else credited as composer, with counts
    song_performers    264   who else recorded it, with covers_mill flag

    tracks             910   cache/search rows — the recording grain
    credits          11926   every `performers` string expanded: person x role x track

    discogs_candidates      154   candidate artists from the Discogs path
    discogs_candidate_via   161   why each was surfaced

    listens         190196   the ListenBrainz export, with MBIDs

Four views: `v_releases_scored`, `v_people`, `v_songs_by_others`,
`v_credit_graph`.

### Grain

The grain is the **recording**, not the album. Album identity is the unresolved
one (README:134) — both pools hold Qobuz album ids reached by different paths, so
they collide, which is why `releases` is keyed `(album_id, source)`. Song
identity is cheaper: `listens.recording_mbid` exists, and a Qobuz ISRC exists
upstream but is not cached yet. So `songs`, `tracks` and `credits` are the tables
that will take new columns.

## Cookbook

Each of these maps to something the README asks for.

**Other recordings of a song** — the one song-level feature that works exactly
today (README:89).

```sql
SELECT performer_name, album_title
FROM v_songs_by_others
WHERE song_key = 'al otro lado del reio'
ORDER BY performer_name;
```

**The collaborator graph, weighted, seed excluded.**

```sql
SELECT person_name, role_class, COUNT(*) AS n, ROUND(SUM(role_weight), 1) AS weight
FROM credits
WHERE source = 'credits' AND person_key NOT LIKE '%drexler%'
GROUP BY person_name, role_class
ORDER BY weight DESC LIMIT 20;
```

**Filters instead of ranking** (README:102) — removing rows is cheaper than
ordering them.

```sql
SELECT title, via_name, sig_score, genre, label
FROM releases
WHERE sig_selectivity_band = 'selective'
  AND (sig_flags IS NULL OR sig_flags NOT LIKE '%single_token_name%')
  AND sig_score >= 0.8
ORDER BY sig_score DESC, date DESC;
```

**Explanations, not scores** (README:105) — a sentence out of `via.signal`.

```sql
SELECT title,
       via_name || ' — ' || via_top_role || ' on ' || via_seed_albums
         || ' of the seed''s albums' AS because
FROM releases WHERE source = 'qobuz' AND via_seed_albums >= 10
ORDER BY via_seed_albums DESC LIMIT 15;
```

**Shared songbook** (README:111) — writer ↔ performer graph.

```sql
SELECT sp.performer_name, COUNT(DISTINCT sp.song_key) AS songs
FROM song_performers sp
WHERE sp.covers_mill = FALSE
GROUP BY sp.performer_name
HAVING COUNT(DISTINCT sp.song_key) > 1
ORDER BY songs DESC;
```

**Production posture** (README:115) — the shape of the credits, not the names.

```sql
SELECT role_class, COUNT(DISTINCT person_key) AS people, COUNT(*) AS credits,
       ROUND(1.0 * COUNT(*) / COUNT(DISTINCT person_key), 1) AS credits_per_person
FROM credits WHERE source = 'credits'
GROUP BY role_class ORDER BY credits DESC;
```

**Bridges** (README:118) — people joining otherwise disjoint scenes.

```sql
SELECT p.name, p.top_role, COUNT(DISTINCT e.other_name) AS reach
FROM people p JOIN person_edges e ON e.person_key = p.person_key
GROUP BY p.name, p.top_role
HAVING COUNT(DISTINCT e.other_name) >= 3
ORDER BY reach DESC;
```

**More seeds** (README:122) — set intersection, once a second `discovery_*.json`
exists. Works unchanged as seeds are added, because `load.py` globs them.

```sql
SELECT person_key, COUNT(*) AS graphs
FROM person_sources
WHERE source LIKE 'discovery_%'
GROUP BY person_key
HAVING COUNT(*) >= 3;
```

Returns 0 today because one seed exists, which is the correct answer rather than
an empty table. Crawl a second seed and it starts working with no change — the
loader globs `discovery_*.json`.

**Exposure bias, measured** (README:149) — how many candidate artists are already
in the listen history? These are the ones a naive offline score would reward you
for "finding".

```sql
SELECT COUNT(DISTINCT ra.name)
FROM release_artists ra
WHERE lower(ra.name) IN (SELECT artist_key FROM listens);
-- 250
```

**The time split** (README:156) — the honest evaluation baseline.

```sql
WITH firsts AS (SELECT artist_key, MIN(year) AS y FROM listens GROUP BY artist_key),
     plays  AS (SELECT artist_key, year, COUNT(*) AS c FROM listens GROUP BY 1, 2)
SELECT f.y AS first_year, COUNT(*) AS new_artists
FROM firsts f JOIN plays p ON p.artist_key = f.artist_key AND p.year = f.y
WHERE p.c >= 20
GROUP BY f.y ORDER BY f.y;
```

Read the caveat under *Numbers that disagree with the README* before trusting the
output of that one.

**The funnel, end to end** — what discovery produced and what survives each cut.
`seeds` is the top half, `releases` the bottom, and each step is the one before
plus one condition.

```sql
SELECT name, releases AS albums_walked, albums_own, albums_guest,
       albums_compilation, people AS credited_people, co_artists
FROM seeds;
```

`albums_compilation` is a various-artists record in the seed's discography —
neither theirs nor anybody else's. One in four corpora, and it was worth a
column because that one produced 20 of Björk's 35 co-artists
([adr/D24](adr/D24-a-record-nobody-holds.md)).

```sql
WITH pool AS (SELECT * FROM releases WHERE seed_qobuz_id = 41620 AND source = 'qobuz')
SELECT 1 AS step, 'in the pool' AS filter, COUNT(*) FROM pool
UNION ALL SELECT 2, 'not the referrer''s own record', COUNT(*) FROM pool
          WHERE NOT via_is_first_artist
UNION ALL SELECT 3, 'player or producer referral', COUNT(*) FROM pool
          WHERE NOT via_is_first_artist
            AND (via_referral_classes LIKE '%performance%'
                 OR via_referral_classes LIKE '%production%')
ORDER BY step;
```

Measured 2026-10-20 on the Drexler pool: 1,255 -> 383 -> 271, then 215 unheard,
208 since 2015 and streamable, 38 after the cap. The side-credit cut is the big
one — 872 of the 1,255 rows are the referring person's own albums.

**Who the seed made a record WITH** — the other output of discovery, and the one
with the best hit rate. Unheard only:

```sql
SELECT c.name, c.seed_records + c.their_records AS together,
       c.seed_records, c.their_records, c.last_seen
FROM co_artists c
WHERE c.seed_qobuz_id = 41620
  AND c.seed_records + c.their_records > 0
  AND NOT EXISTS (SELECT 1 FROM listens l WHERE l.artist_key = c.person_key)
ORDER BY together DESC, c.last_seen DESC;
```

`seed_records` is them guesting on the seed's album, `their_records` is the seed
guesting on theirs. Both are a record the two made together — see
[adr/D14](adr/D14-co-appearance-is-its-own-output.md). Joining on `person_key`
works because it is `normalise(name)`, the same key `listens.artist_key` carries.

**Count on those two and not on `albums`.** `albums` counts every sleeve the two
are printed on, including a various-artists record that is nobody's, so it both
admits rows that are not collaborations and ranks them above real ones — 20 of
Björk's 35 co-artists came off one remix album
([adr/D24](adr/D24-a-record-nobody-holds.md)). The rows stay in the store and
`co_artist_albums.provenance` says which is which, so the filter is this `WHERE`
clause rather than a rewalk.

`stages/co_artists.py` applies one more cut that no query can: `policy.NOT_ARTISTS`,
a hand list of billings that are not an artist at all — the *A COLORS SHOW*
channel, an actor reading on a track, Björk's own former bands.

**The shortlist** — the credits thesis, as something a person can actually read.
Filtered first, then ordered: `policy.shortlisted`'s three cuts, then
`policy.ranked_score`'s penalty on a shaky name match, then unheard and recent.

```sql
WITH kept AS (
  SELECT album_id, source, date, title, via_name, genre,
         -- The resolvers now fold policy.match_confidence into sig_score, so
         -- this only discounts rows written BEFORE that -- the ones with no
         -- sig_match_confidence. Penalising a new row here would square it.
         sig_score * CASE WHEN sig_match_confidence IS NULL
                           AND sig_flags LIKE '%single_token_name%'
                          THEN 0.1 ELSE 1.0 END AS score
  FROM releases
  -- policy.shortlisted, spelled out. 7,860 rows -> 291.
  WHERE source <> 'discogs'                               -- 81% of the rows
    AND NOT via_is_first_artist                            -- not their own record
    AND (via_referral_classes LIKE '%performance%'         -- a player
         OR via_referral_classes LIKE '%production%')      -- or a producer
    AND sig_score > 0                                      -- policy.carries_signal
    AND date >= '2015-01-01' AND streamable
),
unheard AS (
  SELECT * FROM kept
  WHERE NOT EXISTS (
    SELECT 1 FROM release_artists ra
    JOIN listens l ON l.artist_key = ra.name_key
    WHERE ra.album_id = kept.album_id AND ra.source = kept.source)
),
capped AS (
  -- policy.cap_per_referrer, MAX_PER_REFERRER = 2. Keyed on via_name, NOT
  -- via_through, which is NULL on every Qobuz-path row.
  SELECT *, ROW_NUMBER() OVER (PARTITION BY via_name
                               ORDER BY score DESC, date) AS nth
  FROM unheard
)
SELECT ROUND(score, 2) AS score, date, title, via_name AS through, genre,
       (SELECT name FROM release_artists ra
        WHERE ra.album_id = capped.album_id AND ra.source = capped.source
        LIMIT 1) AS artist
FROM capped
WHERE nth <= 2
ORDER BY score DESC, date
LIMIT 20;
```

Four things to know before trusting it.

**Join on `name_key`, never `lower(name)`.** `name_key` is `normalise(name)`, the
key `listens.artist_key` already carries. `lower(name)` matches 250 of 2,773
pooled names against 313, because it cannot see an accent — it called Xoel López
unheard, and he is in the export 331 times. That column exists for this query.

**A score of 0 is not a weak referral, it is no referral.** `sig_score > 0`
drops 175 rows through 5 people whose only link to the seed was a record he
guested on — [adr/D18](adr/D18-drop-score-zero-referrals.md). It is separate
from the three filters below, which are judgements about what a credit is worth.

**The three filters are the difference between a list and a table dump.**
Measured 2026-10-20: 7,860 rows, of which 1,470 Qobuz-native, 1,998 side credits
and 2,778 musician-or-producer referrals; 291 satisfy all three, and 220 of those
are by artists never played. `policy.py`'s POOL FILTERS block has the argument
for each cut and [adr/D15](adr/D15-filters-before-ranking.md) has the decision.
The numbers live in two places on purpose — the predicate is `policy.shortlisted`
and this WHERE clause restates it, because sqlite cannot call Python. If they
drift, the predicate is right.

**The penalty still matters inside the shortlist.** 72 of the 291 carry
`single_token_name`, through five people — "Mauro" alone contributes 42. Filtering
to the Qobuz path does not escape the name problem, it only reduces it: that path
resolves names through autosuggest too.

**Which score you are reading depends on when the pool was written.**
`sig_match_confidence` is the discount the resolvers applied, and `sig_score` is
already multiplied by it — divide to recover the raw referrer score. It is NULL
for every row written before [adr/D17](adr/D17-fold-plausibility-into-the-score.md),
which is why the CASE above is conditional. Once both pools have been
regenerated, that branch can go.

**The cap is what makes it a list rather than one discography.** The 291 arrive
through 30 people (212 through 24, once unheard and since-2015 are asked for too),
and uncapped the first rows were nine Juan Campodónico records. `nth <= 2` leaves
38 rows across all 24, with 12 distinct people in the top 20 —
[adr/D16](adr/D16-cap-the-list-per-referrer.md) has the numbers for caps of 1, 2,
3 and 5. Raising it brings the dropped rows straight back; nothing is reordered
and no score changes.

`artist` is still an arbitrary one of the credited names, since `LIMIT 1` has no
ordering.

**Where the identifiers are** — 92.6% of listens carry a `recording_mbid`, which
is the only MusicBrainz identifier anywhere in this project.

```sql
SELECT COUNT(*) AS listens, COUNT(recording_mbid) AS with_mbid,
       ROUND(100.0 * COUNT(recording_mbid) / COUNT(*), 1) AS pct
FROM listens;
```

## Gotchas

**Identity is a normalised name.** `person_key` is `core.names.normalise(name)`,
inherited from `discover.py` rather than reinvented — so the store has the same
weakness: two different people with one name collide. The corpus has four
Drexlers (Jorge, Pablo, Diego, Luca) and they are only separable because Qobuz
gave them different artist ids. Do not treat `person_key` as a person.

**`credits` does not cover the pool.** `cache/credits` holds the seed's 63 albums
(265 tracks); `cache/search` holds the 910 `track/search` rows. Neither covers
the 7,860-release candidate pool, whose credits were never fetched. An empty
result for a pool artist means *not fetched*, not *no credits*.

**`songs.tier` is a hint.** Read `song_tier_votes` and `song_co_composers`
instead. Cover and karaoke metadata is wrong in both directions — Qobuz credits
Drexler as Composer on "Waka Waka" (he wrote only the Spanish lyric) and credits
the cover artist as Composer on "12 Segundos de Oscuridad", which is his.
`writing.py:406` explains the plurality rule.

**List fields are `' | '`-joined text** where you would only read them
(`sig_flags`, `person_albums.roles`, `via_through`) and separate tables where you
would filter on them (`person_classes`, `song_roles`). If you find yourself
`LIKE`-matching a joined column often, that one wants promoting to a table.

**`meta` is the provenance record.** `SELECT * FROM meta` tells you which file
each table came from and when that file was generated, which is how you tell a
stale load from a changed pipeline.

## Numbers that disagree with the README

Both were checked against the files, and the store is what surfaced them.

**Feature parity is already fixed.** README:139 says `pool_discogs.json` carries
genre and label on 0 of 6,392 rows. It carries both on all 6,390. The file was
regenerated 2026-09-02 and the two-line fix landed; the README predates it. The
row count moved 6,392 → 6,390 at the same time, which is why `releases` totals
7,860 and not the README's 7,862.

**The 2021 gap is real and much bigger than suspected.** README:163 flags 2021 as
worth checking. It holds **26 listens across 8 artists**, against 1,837 in 2020
and 13,715 in 2022. That is not a thin year, it is a missing one — do not split
on it, and treat 2020 and 2022 boundaries with suspicion too.

**The time-split counts do not reproduce.** The query above gives 28 / 57 / 44 /
87 for 2022-2025 where README:159 quotes 85 / 93 / 90 / 100. The definitions
differ: this one requires 20+ plays *within the artist's first calendar year*,
which is stricter than "reaches 20+ plays". Neither is wrong; the README's number
was computed some other way and that way is not written down. Pick a definition,
put it in SQL, and the ambiguity stops recurring. Note also that 2013 (143) is an
import artifact — every artist is new in the first year of history.

**Listen totals differ slightly.** 190,196 listens and 7,357 distinct artists
here, against README:156's 190,198 and 7,427. The listens figure is the true line
count in the zip. The artist gap is explained: `artist_key` is
`normalise(artist_name)`, so ~70 accent and case variants merge — which is the
intended behaviour, not a loss.

## Where new data lands

The store is shaped so the language work is additive rather than a rewrite.

1. **ISRC.** Qobuz's raw `track/search` returns `isrc` and `album.upc` per track;
   `writing.py:181` keeps four fields and drops both. Add them to the slim shape,
   bump the cache key to `cache/search/v2_...` so the existing cache stays
   reproducible, re-run — 10 requests. `tracks` gains an `isrc` column.
2. **Language.** ISRC → MusicBrainz recording → work → `work.languages`. Free, no
   key, 1 req/sec, cacheable. Lands as a new `works` table joined on ISRC, so
   nothing above changes. Expect thin coverage: MB has 42 authored works for
   Drexler against the 162 songs Qobuz proves he wrote (`writing.py:14`), so an
   empty Catalan result will still not be proof.
3. **Dumps, later.** MB before Discogs, and only when going multi-seed makes
   per-lookup API calls the bottleneck. Discogs' dump buys tracklist `Written-By`
   credits (`writing.py:11`), not language — it has no language field at all.
