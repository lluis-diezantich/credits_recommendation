# D6: `data/music.db` is derived, disposable and rebuilt from JSON

- **Status:** Accepted
- **Date:** 2026-10-17
- **Where it lives:** [`stages/load.py`](../../stages/load.py),
  [`../store.md`](../store.md), [`../duckdb.md`](../duckdb.md)

## Context

Every stage reads and writes JSON in `data/`, which makes each stage rerunnable
alone but makes a question like "which pooled artists have I never played"
unanswerable without loading six files by hand.

## Options

1. **Query the JSON** with a script per question: no new artefact, and every
   question is bespoke.
2. **A SQLite file rebuilt from the JSON**, with the JSON staying authoritative:
   one query language, and a second copy of the data that can go stale.
3. **Postgres**, with the store as the system of record: survives a laptop,
   needs a schema decided up front and something to run it.

## Decision

Option 2. `./stages/load.py` rebuilds 216k rows from whatever is on disk and
fetches nothing, so deleting the file costs one rerun. Postgres is deferred
until the ranker needs feedback state — dismissed, played, rated — because that
state is what defines the schema, so building it first means guessing.

## Evidence

The rebuild went from 0.77s to 0.23s when 15 of the 21 tables took primary keys,
because a key is itself a unique index and subsumed 15 single-column ones (45
indexes down to 30, now 31). Indexes are created *after* the bulk load: in
`SCHEMA` they would be maintained per insert across 216k rows, and a test asserts
`CREATE INDEX` never appears there.

## Consequences

- Six tables carry no primary key, each for a stated reason rather than by
  omission — `person_roles` needs a source-precedence decision, `tracks` and
  `credits` are genuinely duplicated inside the cached pages. [../store.md](../store.md)
  lists all six.
- SQLite allows NULL in a primary-key column of a rowid table and counts NULLs
  as distinct, so each key protects only rows whose key columns are all present.
  DuckDB refuses NULL in a key, so a `song_performers` key would build under one
  engine and fail under the other.
- A query in [../store.md](../store.md) is the deliverable for a new question,
  not a script.
