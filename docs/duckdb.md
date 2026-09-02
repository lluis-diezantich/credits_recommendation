# DuckDB, for this project

Everything below was measured on this repo's data, not quoted from DuckDB's docs.

## The one thing to know

**Build with sqlite. Query with DuckDB.** Do not build with DuckDB.

    load 216k rows, sqlite       2.0s     42.0 MB
    load 216k rows, duckdb      68.7s     17.6 MB

DuckDB is columnar, and `executemany` feeds it one row at a time. Batching 1,000
rows per `INSERT` only got it to 47s. It is the wrong tool for a load and an
excellent one for everything after, so `./stages/load.py` defaults to sqlite and
`--engine auto` will never pick DuckDB for you — even with DuckDB installed.

Once loaded, DuckDB reads that same sqlite file directly:

    aggregate over 190,196 listens, grouped by year    0.03s

## Install

    pip install duckdb          # python module - what the examples below use
    brew install duckdb         # optional CLI, if you like a REPL

Nothing in the pipeline requires it. The README's "no install, no dependencies"
stays true; this is an optional query layer.

## Setup: attach the store

Two lines at the top of every session. The `INSTALL` is a one-time download
(~2s), cached afterwards.

```python
import duckdb
con = duckdb.connect()                       # in-memory; the data lives in sqlite
con.execute("INSTALL sqlite; LOAD sqlite;")
con.execute("ATTACH 'data/music.db' AS m (TYPE sqlite, READ_ONLY);")

con.sql("SELECT COUNT(*) FROM m.listens").show()
```

`READ_ONLY` on purpose: the store is derived and rebuilt by `load.py`, so nothing
should be writing to it from a notebook.

Every table from `docs/store.md` is now `m.<table>` — `m.songs`, `m.credits`,
`m.listens`. In the CLI it is the same two statements.

**Gotcha:** `duckdb data/music.db` does **not** work. That file is a sqlite
database, and DuckDB's own format is different. Always `ATTACH` it. If you do
build a native file with `--engine duckdb --db data/music.duckdb`, keep the
`.duckdb` extension so the two never get confused.

## What DuckDB buys you here

### 1. Skip the load step entirely

DuckDB reads the pipeline's JSON where it lies. Useful when you have just
re-run a stage and don't want to rebuild.

```sql
SELECT s.song, s.tier, s.performer_count_excl_mills
FROM (SELECT unnest(songs) AS s FROM read_json_auto('data/writing_jorge-drexler.json'))
ORDER BY 3 DESC LIMIT 5;
```

Globs work, so the whole cache is one table:

```sql
SELECT COUNT(*) FROM (SELECT unnest(items) AS i FROM read_json_auto('cache/search/*.json'));
-- 910
```

### 2. Nested fields without flattening them first

This is the real win over sqlite, which would need `load.py` to have unpacked
these into columns. `via.signal` stays a struct and you read into it with dots;
lists keep their type and `len()`/`unnest()` work on them.

```sql
SELECT p.title, p.via.name AS via, p.via.signal.score AS score, p.via.signal.flags AS flags
FROM (SELECT unnest(pool) AS p FROM read_json_auto('data/pool_discogs.json'))
WHERE len(p.via.signal.flags) > 0
ORDER BY score DESC LIMIT 5;
```

`unnest` also explodes a list *inside* a row, which is how you get from one song
to its performers with no join:

```sql
SELECT s.song, unnest(s.performers).name AS performer
FROM (SELECT unnest(songs) AS s FROM read_json_auto('data/writing_jorge-drexler.json'))
WHERE s.song = 'la edad del cielo';
```

### 3. Profile a table in one statement

`SUMMARIZE` gives min, max, approximate distinct count and null percentage per
column. Fastest way to find out whether a field is actually populated.

```sql
SUMMARIZE SELECT * FROM m.releases;
```

### 4. Join raw JSON against the loaded store

One query spanning a file on disk and a table in sqlite — how many plays does
each referring person have in the listen history?

```sql
WITH via AS (
  SELECT p.via.name AS name, COUNT(*) AS candidates
  FROM (SELECT unnest(pool) AS p FROM read_json_auto('data/pool.json'))
  GROUP BY 1)
SELECT v.name, v.candidates, COUNT(l.listened_at) AS plays
FROM via v
LEFT JOIN m.listens l ON lower(l.artist_name) = lower(v.name)
GROUP BY 1, 2 ORDER BY plays DESC LIMIT 10;
-- C. Tangana     65 candidates   794 plays
-- Caetano Veloso 117            508
```

**Aggregate the JSON side first.** Joining the raw pool rows straight to
`listens` multiplies 117 pool rows by 508 listens and reports 59,436 plays. The
`WITH` clause above is not styling, it is the fix.

### 5. Parquet, for when the dumps arrive

```sql
COPY (SELECT * FROM m.listens) TO 'data/listens.parquet' (FORMAT parquet);
```

42 MB of sqlite becomes 7.4 MB of Parquet in 0.13s, and counting distinct
artists in it takes 4ms. This is the format to keep MusicBrainz and Discogs
extracts in — DuckDB queries Parquet larger than RAM without importing it, which
is the entire reason to reach for it over sqlite later:

```sql
-- the shape the MB work dump work will take, once fetched
SELECT w.languages, COUNT(*) FROM 'data/mb_works.parquet' w GROUP BY 1 ORDER BY 2 DESC;
```

## Pandas, if you want it

```python
df = con.sql("SELECT * FROM m.songs WHERE tier = 'authored'").df()   # (235, 9)
```

`.df()` on any result, and it needs `pip install pandas` — DuckDB itself does not
pull it in. `notebooks/showcase.ipynb` is the natural home for this.

## When to stop using sqlite

Not yet. The honest trigger is a **file too big to load**, and nothing here
qualifies — 216k rows is small. Switch the moment you download a MusicBrainz or
Discogs dump, because at that point "import it first" is the expensive step
DuckDB lets you skip. Until then sqlite builds in 2s and DuckDB reads it in
0.03s, which is the best of both.

## Cheat sheet

    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute("ATTACH 'data/music.db' AS m (TYPE sqlite, READ_ONLY);")

    read_json_auto('data/pool.json')       read a file, infer the schema
    read_json_auto('cache/search/*.json')  glob many files as one table
    unnest(col)                            list column -> rows
    unnest(col).field                      list of structs -> one field
    struct.field.subfield                  nested access, no flattening
    SUMMARIZE SELECT ...                   per-column profile
    COPY (...) TO 'x.parquet' (FORMAT parquet)
    SELECT * FROM 'x.parquet'              query a file with no import
    .df()                                  result -> pandas
