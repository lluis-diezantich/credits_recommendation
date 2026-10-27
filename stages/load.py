#!/usr/bin/env python3
"""LOAD: every JSON already on disk, into one queryable file.

Not numbered like the other stages because it is not in their chain -- it runs
AFTER whichever of them have run, over whatever they happened to leave behind,
and adds nothing of its own. Missing files are skipped, not errors.

Nothing here fetches. It reads `data/*.json`, `cache/search/*`, `cache/credits/*`
and the ListenBrainz export, and writes `data/music.db`. Unplug the network and
it still runs.

Why a store at all: most of what the README lists as "plausible" is a JOIN, not
a model. "people who appear in 3+ discovery graphs", "artists who record the same
writers", "did the graph built on listens up to 2024 contain the artists adopted
in 2025" - each is one SQL statement and about a page of Python. The store does
not add data. It reshapes what is here so those questions stop being scripts.

Two design calls worth knowing about:

  The DB is DERIVED and disposable. It is rebuilt from scratch on every run and
  gitignored. `cache/` stays the source of truth, for the reason writing.py:145
  gives -- track/search is not stable, so the cache is what makes any of this
  reproducible. Deleting music.db costs one rerun; deleting cache/ costs the
  corpus.

  The grain is the RECORDING, not the album. `pool.json` and `pool_discogs.json`
  are album-grained and their album ids collide (both are Qobuz ids reached by
  different paths), which is why `releases` is keyed (album_id, source) rather
  than album_id. Song identity is the cheaper join -- the listens carry
  `recording_mbid` and Qobuz carries an ISRC we do not cache yet -- so the tables
  that will actually take new columns are `songs`, `tracks` and `credits`.

    ./stages/load.py                     # build data/music.db
    ./stages/load.py --no-listens        # skip the 190k-row export
    ./stages/load.py --engine sqlite     # force the stdlib engine
    ./stages/load.py --summary           # row counts of an existing DB, no rebuild

See docs/store.md for the table map and a query cookbook.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sqlite3
import sys
import zipfile
from pathlib import Path

from core import aliases, listens
from core.credits import parse_performers
from core.names import normalise
from core.paths import DATA, ROOT
from policy import role_class, role_key, role_weight

DB_DEFAULT = DATA / "music.db"
# The export lives OUTSIDE the repo (README:78). Found, not required, and
# picked by size -- see core.listens.newest_export for what that fixes.
LISTENS_GLOB = listens.EXPORT_GLOB


# ---- engine --------------------------------------------------------------


def connect(path: Path, engine: str):
    """Open `path`. stdlib sqlite3 unless duckdb was asked for explicitly.

    sqlite is the default because it is 30x faster to BUILD, measured: 2.0s
    against 68.7s for the same 216k rows. DuckDB is columnar and inserts rows one
    at a time through executemany -- batching 1,000 rows per statement only got it
    to 47s. It is the wrong tool for a load and the right one for a query, so the
    recommended setup is sqlite here and DuckDB reading it:

        ATTACH 'data/music.db' AS m (TYPE sqlite, READ_ONLY);

    which gives 0.03s aggregates over the 190k listens without a second copy of
    anything. docs/duckdb.md has the whole workflow. --engine duckdb still works
    and yields a smaller file (17.6 MB vs 42 MB); it just costs a minute.

    Both speak enough of the same DB-API and the same `?` placeholder that the
    DDL below is plain SQL with no engine-specific types in it.
    """
    engine = resolve_engine(engine)
    if engine == "duckdb":
        import duckdb
        return duckdb.connect(str(path)), "duckdb"
    import sqlite3
    return sqlite3.connect(str(path)), "sqlite"


def resolve_engine(engine: str) -> str:
    """Settle on an engine, and fail here if it cannot be had.

    Separate from connect() because main() deletes the DB before rebuilding it,
    and an engine that is not installed must not take the previous build down
    with it -- the whole point of the file being disposable is that rebuilding is
    cheap, which stops being true if a typo destroys it and then cannot rebuild.
    """
    if engine == "auto":
        # Deliberately NOT "duckdb if importable": pip installing duckdb for the
        # query side must not silently turn a 2s build into a 69s one.
        return "sqlite"
    if engine == "duckdb":
        try:
            import duckdb  # noqa: F401
        except ImportError:
            # from None: the ImportError adds nothing the message does not say.
            raise SystemExit("duckdb not installed - `pip install duckdb`, or use "
                             "--engine sqlite (no extra install)") from None
    return engine


SCHEMA = """
CREATE TABLE meta (
    table_name TEXT, source TEXT, rows INTEGER, generated TEXT, loaded_at TEXT);

-- people ---------------------------------------------------------------
CREATE TABLE people (
    person_key TEXT PRIMARY KEY, name TEXT, qobuz_id INTEGER, discogs_id INTEGER,
    watch BOOLEAN, cover_source_only BOOLEAN,
    albums INTEGER, own_albums INTEGER, tracks INTEGER, seeds INTEGER,
--  ^ SUMMED across the seeds in person_seeds, which is the real grain. For
--    "how embedded in ONE seed's catalogue" read person_seeds instead.
    top_role TEXT, first_seen TEXT, last_seen TEXT,
    resolved_via TEXT, resolved_confidence TEXT, unresolved_reason TEXT,
    discogs_total_releases INTEGER, selectivity REAL, selectivity_band TEXT,
    sources TEXT);
CREATE TABLE person_names   (person_key TEXT, name TEXT,
                             PRIMARY KEY (person_key, name));
CREATE TABLE person_sources (person_key TEXT, source TEXT,
                             PRIMARY KEY (person_key, source));
CREATE TABLE person_classes (person_key TEXT, class TEXT,
                             PRIMARY KEY (person_key, class));
CREATE TABLE person_roles   (person_key TEXT, role TEXT, role_key TEXT,
                             role_class TEXT, role_weight REAL, n INTEGER);
CREATE TABLE person_albums  (seed_qobuz_id INTEGER, person_key TEXT,
                             album_id TEXT, title TEXT,
                             provenance TEXT,
--  ^ own/guest/compilation, from discover.py: a credit on a record the seed
--    only guested on is not a credit on one of the seed's records. It is a
--    fact about (album, SEED), which is why the seed leads the key -- one
--    album is Bjork's OWN record and a guest spot for ROSALIA, and Noah
--    Goldstein and Sega Bodega are credited on it in both walks. D28 finishes
--    what D19 started: an album is per (person, seed), the grain person_seeds
--    and co_artist_albums already use.
                             date TEXT, tracks INTEGER, roles TEXT,
                             PRIMARY KEY (seed_qobuz_id, person_key, album_id));
CREATE TABLE person_edges   (person_key TEXT, other_name TEXT, releases INTEGER,
                             roles TEXT, kind TEXT,
                             PRIMARY KEY (person_key, other_name, kind));

-- releases (candidate pool) --------------------------------------------
CREATE TABLE releases (
    album_id TEXT, source TEXT, seed_qobuz_id INTEGER,
--  ^ which seed's graph this candidate came out of. Both pool files carry it
--    and it was dropped, so two seeds' pools in one table were
--    indistinguishable in SQL -- the defect person_seeds fixed for people.
    title TEXT, date TEXT, tracks INTEGER,
    hires BOOLEAN, streamable BOOLEAN, label TEXT, genre TEXT,
    via_name TEXT, via_qobuz_id INTEGER, via_path TEXT, via_top_role TEXT,
    via_seed_albums INTEGER, via_through TEXT, via_through_roles TEXT,
-- The two facts policy.shortlisted needs that SQL cannot derive. Stored as
-- facts, not as the verdict: the composition is policy's and would go stale in
-- the store the same way sig_score did. docs/store.md spells the WHERE out.
    via_referral_classes TEXT,
--  ^ role_class of each referring role: "production", "engineering", ...
    via_is_first_artist BOOLEAN,
--  ^ the referring person is the FIRST credited artist, i.e. it is their own
--    record rather than one they worked on. 5,862 of the 7,860 rows are.
    via_albums_count INTEGER, via_discogs_releases INTEGER,
--  ^ the two catalogue sizes, for corroborating the name match: how many
--    albums the matched Qobuz artist holds, and how many releases the Discogs
--    credits put that person on. Both were fetched and dropped before.
    sig_score REAL, sig_role_weight REAL, sig_selectivity REAL,
    sig_selectivity_band TEXT, sig_person_seed_albums INTEGER,
    sig_embedded REAL, sig_match_confidence REAL, sig_own_albums INTEGER,
--  ^ how many of those albums are the seed's OWN records. sig_embedded is
--    computed from THIS, not from via_seed_albums, so a referrer who only ever
--    appeared on a record the seed guested on scores 0 -- 5 of 50 did.
    sig_flags TEXT,
--  ^ sig_score is ALREADY multiplied by sig_match_confidence by the resolvers,
--    so a reader must not apply the penalty a second time. Divide by it to
--    recover the raw referrer score. (No semicolons in these comments: the
--    tests split SCHEMA on them.)
    PRIMARY KEY (album_id, source));
-- name_key is normalise(name), the same key listens.artist_key carries, so a
-- pooled artist can be joined to your listening at all. Without it the only
-- join available is lower(name), which matches 250 of 2,773 names and silently
-- calls every accented artist unheard -- it recommended Xoel Lopez, who is in
-- the export 331 times.
-- One row per seed walked. The top half of the funnel: how much of the
-- discography is really the seed's own work, how many people it credits, how
-- many artists they are billed alongside. Lived only in discovery_*.json, so
-- "what did discovery actually produce" could not be asked of the store.
CREATE TABLE seeds (seed_qobuz_id INTEGER PRIMARY KEY, name TEXT, mbid TEXT,
--  ^ from data/favourites.json, matched on `core.aliases.person_key` and not
--    on the spelling: 5 of 20 seeds are written differently in the two files
--    ("Ruben Blades" / "Rubén Blades"), and an exact-name join silently found
--    15. It is here so artist_genres can be joined without reading a file.
                    store TEXT,
                    releases INTEGER, albums_own INTEGER, albums_guest INTEGER,
                    albums_compilation INTEGER,
--  ^ various-artists records in the seed's discography, which are neither the
--    seed's own nor anybody else's. NULL from a file written before D24.
                    albums_unbilled INTEGER, tracks INTEGER,
                    credited_tracks INTEGER, people INTEGER,
                    co_artists INTEGER, source TEXT, generated TEXT);

-- Who the seed has made a record WITH, as opposed to who worked on their
-- records. Measured at 59% artists-already-played against 13% for the crew
-- graph (docs/adr/D14), and until now it reached no table at all.
-- person_key is normalise(name), so this joins to people and to
-- listens.artist_key like everything else.
CREATE TABLE co_artists (seed_qobuz_id INTEGER, person_key TEXT, name TEXT,
                         albums INTEGER, their_records INTEGER,
                         seed_records INTEGER, first_seen TEXT, last_seen TEXT,
                         PRIMARY KEY (seed_qobuz_id, person_key));
CREATE TABLE artist_genres (mbid TEXT, genre TEXT, votes INTEGER,
                            PRIMARY KEY (mbid, genre));
--  ^ MusicBrainz genres, from cache/musicbrainz_genres/. User-voted, so
--    `votes` is the only quality signal there is and a 1 is one person's
--    opinion. Used as a VETO on a scene link, never as one: linking two seeds
--    on a shared tag put 18 of 20 in a single scene through "pop" and "jazz"
--    (D38). Keyed by mbid because that is what the cache filename is.
CREATE TABLE ubiquity (person_key TEXT PRIMARY KEY, name TEXT,
                       discogs_id INTEGER, discogs_name TEXT, match TEXT,
                       total_releases INTEGER);
--  ^ How many releases Discogs holds for this person: the input
--    policy.selectivity() never had. `match` is load-bearing, not
--    provenance -- only 'exact' is trusted, because a wrong same-name pick
--    returns a SMALL catalogue and small reads as scarce. Read it through
--    policy.trusted_ubiquity(), never raw.
CREATE TABLE co_artist_albums (seed_qobuz_id INTEGER, person_key TEXT,
                               album_id TEXT, title TEXT, date TEXT,
                               provenance TEXT,
--  ^ "own": they guested on the seed's record. "guest": the seed guested on
--    theirs. Both are a record the two of them made together.
--    "compilation": a various-artists record neither of them holds, which is
--    not a collaboration at all -- 20 of Bjork's 35 co-artists are one remix
--    album (D24). Stored rather than dropped, and excluded on read by
--    stages/co_artists.py, so a wrong label costs a query and not a rewalk.
                               PRIMARY KEY (seed_qobuz_id, person_key, album_id));

-- One row per (person, seed): albums and tracks are facts about a person IN
-- ONE seed's catalogue, and `people` holds one row per person, so there was
-- nowhere for the second seed's numbers to go. load_people used to let the
-- last discovery file win, which silently replaced Fred Kevorkian's 13 Drexler
-- albums with the 1 he has on a Perez Cruz record. 14 people are in both files.
CREATE TABLE person_seeds (person_key TEXT, seed_qobuz_id INTEGER, seed_name TEXT,
                           source TEXT, albums INTEGER, own_albums INTEGER,
                           tracks INTEGER, top_role TEXT,
                           first_seen TEXT, last_seen TEXT,
                           PRIMARY KEY (person_key, seed_qobuz_id));
CREATE TABLE release_artists (album_id TEXT, source TEXT, name TEXT,
                              name_key TEXT,
                              PRIMARY KEY (album_id, source, name));

-- songs (writing_*.json) ----------------------------------------------
CREATE TABLE songs (
    song_key TEXT, artist_query TEXT, title TEXT, tier TEXT,
    tier_disagreement BOOLEAN, own_recording BOOLEAN,
    performer_count INTEGER, performer_count_excl_mills INTEGER, flags TEXT,
    PRIMARY KEY (song_key, artist_query));
CREATE TABLE song_titles       (song_key TEXT, artist_query TEXT, title TEXT,
                                PRIMARY KEY (song_key, artist_query, title));
CREATE TABLE song_roles        (song_key TEXT, artist_query TEXT, role TEXT,
                                PRIMARY KEY (song_key, artist_query, role));
CREATE TABLE song_tier_votes   (song_key TEXT, artist_query TEXT, tier TEXT, n INTEGER,
                                PRIMARY KEY (song_key, artist_query, tier));
CREATE TABLE song_co_composers (song_key TEXT, artist_query TEXT, name TEXT, n INTEGER,
                                PRIMARY KEY (song_key, artist_query, name));
CREATE TABLE song_performers   (song_key TEXT, artist_query TEXT, performer_name TEXT,
                                performer_key TEXT, album_title TEXT, covers_mill BOOLEAN);

-- recordings and credits (the cache, parsed) --------------------------
CREATE TABLE tracks (
    store TEXT, query TEXT, album_id TEXT, album_title TEXT,
    track_title TEXT, performer_name TEXT, performers_raw TEXT);
CREATE TABLE credits (
    source TEXT, store TEXT, album_id TEXT, track_id INTEGER, track_title TEXT,
    person_name TEXT, person_key TEXT, role TEXT, role_key TEXT,
    role_class TEXT, role_weight REAL);

-- discogs candidate artists -------------------------------------------
CREATE TABLE discogs_candidates (name TEXT PRIMARY KEY, releases INTEGER);
CREATE TABLE discogs_candidate_via (
    name TEXT, person_name TEXT, person_key TEXT, discogs_id INTEGER, roles TEXT,
    person_seed_albums INTEGER, role_weight REAL, selectivity REAL,
    selectivity_band TEXT,
    PRIMARY KEY (name, person_key, discogs_id));

-- listens --------------------------------------------------------------
CREATE TABLE listens (
    listened_at INTEGER, listened_date TEXT, year INTEGER,
    track_name TEXT, artist_name TEXT, artist_key TEXT, release_name TEXT,
    recording_mbid TEXT, artist_mbid TEXT, release_mbid TEXT);
"""

# Indexes, created AFTER the rows are in -- the whole build is one bulk load
# into a file that was just deleted, and maintaining an index per INSERT is the
# one way to make a sub-second rebuild slow.
#
# Fifteen fewer than there used to be, because the primary keys in SCHEMA now
# cover them: a PK is itself a unique index, so PRIMARY KEY (person_key, name)
# makes a separate index on person_key redundant -- leftmost-prefix matching
# serves the lookup, and keeping both would maintain two indexes per row.
# What is left is the columns no key starts with: the scores and dates a ranker
# orders by, the names and classes a filter matches, and the listens.
#
# On the primary keys themselves, since this file argued against them once:
# they could not go on until the loader stopped inserting duplicate rows, which
# it now does (see deduped()). Three tables still have none, for three
# different reasons, and none of them is an oversight:
#
#   person_roles     722 rows, 612 distinct (person_key, role). The same role
#                    arrives with a count from discovery_*.json and with n=NULL
#                    from watchlist.json's bare-list form. Two tuples, one
#                    fact -- collapsing them means ruling that a count beats an
#                    absence, which is source precedence and belongs in the
#                    open, not in a constraint.
#   song_performers  album_title is NULL BY DESIGN -- load_songs iterates
#                    `perf["albums"] or [None]`, so a performer with no album
#                    is a row with no album. Today's corpus happens to have one
#                    for every performer, which is not the same as the column
#                    being non-null. It is also where the two engines diverge:
#                    SQLite tolerates NULL in a PK column (and treats NULLs as
#                    distinct, so such rows go unprotected), while DuckDB
#                    follows the standard and refuses them. A key here would
#                    build under --engine sqlite and fail under duckdb.
#   tracks, credits  Still genuinely duplicated: 910/906 and 11,926/9,516. The
#                    duplicates are inside the cached pages, so deduping them
#                    means deciding which cached copy wins -- a question about
#                    the corpus, not about this loader.
#
# And the caveat that applies to every key above, because SQLite will not say
# it: in a rowid table a PK column may still be NULL, and NULLs count as
# distinct. So each key protects the rows whose key columns are all present,
# which is all of them today, and quietly protects nothing on a row where a
# source file omitted a field. Loader.insert turns the violation it DOES catch
# into a message that names the table and the row.
INDEXES = """
-- people: person_key is the join key for six tables
CREATE INDEX ix_people_name           ON people (name);
CREATE INDEX ix_people_qobuz          ON people (qobuz_id);
CREATE INDEX ix_person_names_name     ON person_names (name);
CREATE INDEX ix_person_roles_key      ON person_roles (person_key);
CREATE INDEX ix_person_roles_class    ON person_roles (role_class);
CREATE INDEX ix_person_albums_album   ON person_albums (album_id);
CREATE INDEX ix_person_albums_person  ON person_albums (person_key);
--  ^ the key leads with the seed now, so "every album this person worked on,
--    across seeds" lost the prefix it used to scan.
CREATE INDEX ix_person_edges_other    ON person_edges (other_name);

-- releases: album_id joins, sig_score and date are what a ranker will order by
CREATE INDEX ix_releases_source       ON releases (source);
CREATE INDEX ix_releases_score        ON releases (sig_score);
CREATE INDEX ix_releases_date         ON releases (date);
CREATE INDEX ix_releases_via          ON releases (via_qobuz_id);
CREATE INDEX ix_releases_shortlist    ON releases (source, via_is_first_artist);
CREATE INDEX ix_person_seeds_seed     ON person_seeds (seed_qobuz_id);
CREATE INDEX ix_co_artists_person     ON co_artists (person_key);
CREATE INDEX ix_releases_seed         ON releases (seed_qobuz_id);
CREATE INDEX ix_release_artists_name  ON release_artists (name);
CREATE INDEX ix_release_artists_key   ON release_artists (name_key);

-- songs: (song_key, artist_query) is the identity, and every child joins on it
CREATE INDEX ix_songs_tier            ON songs (tier);
CREATE INDEX ix_song_performers_key   ON song_performers (song_key, artist_query);
CREATE INDEX ix_song_performers_who   ON song_performers (performer_key);
CREATE INDEX ix_song_performers_mill  ON song_performers (covers_mill);

-- the parsed cache
CREATE INDEX ix_tracks_album          ON tracks (album_id);
CREATE INDEX ix_tracks_query          ON tracks (query);
CREATE INDEX ix_tracks_performer      ON tracks (performer_name);
CREATE INDEX ix_credits_key           ON credits (person_key);
CREATE INDEX ix_credits_album         ON credits (album_id);
CREATE INDEX ix_credits_class         ON credits (role_class);
CREATE INDEX ix_credits_source        ON credits (source);

-- discogs candidates
CREATE INDEX ix_discogs_via_key       ON discogs_candidate_via (person_key);

-- listens: the big one, and artist_key is how every credit joins to a play
CREATE INDEX ix_listens_artist        ON listens (artist_key);
CREATE INDEX ix_listens_year          ON listens (year);
CREATE INDEX ix_listens_date          ON listens (listened_date);
CREATE INDEX ix_listens_at            ON listens (listened_at);
CREATE INDEX ix_listens_recording     ON listens (recording_mbid);
CREATE INDEX ix_listens_track         ON listens (track_name);
"""

VIEWS = """
CREATE VIEW v_releases_scored AS
SELECT source, album_id, title, date, label, genre, via_name, via_top_role,
       sig_score, sig_selectivity_band, sig_flags
FROM releases;

CREATE VIEW v_people AS
SELECT p.person_key, p.name, p.qobuz_id, p.discogs_id, p.albums, p.own_albums,
       p.tracks, p.seeds,
       p.top_role, p.first_seen, p.last_seen, p.sources,
       (SELECT COUNT(*) FROM person_classes c WHERE c.person_key = p.person_key) AS n_classes
FROM people p;

CREATE VIEW v_songs_by_others AS
SELECT s.song_key, s.artist_query, s.title, s.tier, s.tier_disagreement,
       s.performer_count_excl_mills, sp.performer_name, sp.album_title
FROM songs s JOIN song_performers sp
  ON sp.song_key = s.song_key AND sp.artist_query = s.artist_query
WHERE sp.covers_mill = FALSE;

CREATE VIEW v_credit_graph AS
SELECT c.person_key, c.person_name, c.role_class, c.role_weight,
       c.album_id, c.track_title, c.source
FROM credits c;
"""


# ---- helpers -------------------------------------------------------------


class Loader:
    def __init__(self, con, engine):
        self.con, self.engine = con, engine
        self.counts: dict[str, int] = {}
        self.meta: list[tuple] = []

    def insert(self, table: str, cols: list[str], rows: list[tuple]) -> None:
        """Bulk-insert, turning a key violation into something actionable.

        The tables have primary keys now, so a loader that builds duplicate
        rows fails here instead of writing them. That is the point of the key
        -- but `sqlite3.IntegrityError: UNIQUE constraint failed:
        person_albums.person_key, person_albums.album_id` names the constraint
        and not the row, and a build over 216k rows is not a place to go
        looking. So the offending row is found and printed.

        Re-raised, never swallowed: this means the loader produced data its own
        schema says is impossible, and continuing would write a store that is
        wrong in a way no query would reveal.

        sqlite3.IntegrityError only, which is the default engine and so the one
        worth a readable message. Under --engine duckdb a violation arrives as
        duckdb.ConstraintException and propagates with duckdb's own wording --
        catching it would mean importing an optional dependency here to name an
        exception class, which costs more than the better message is worth.
        """
        if rows:
            marks = ",".join("?" * len(cols))
            statement = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({marks})"
            try:
                self.con.executemany(statement, rows)
            except sqlite3.IntegrityError as error:
                raise SystemExit(
                    f"{table}: {error}\n"
                    f"  first duplicate: {self._first_duplicate(table, cols, rows)}\n"
                    "  the loader built a row its own schema forbids - see "
                    "deduped() and the primary-key notes above INDEXES") from error
        self.counts[table] = self.counts.get(table, 0) + len(rows)

    @staticmethod
    def _first_duplicate(table: str, cols: list[str], rows: list[tuple]):
        """The first row that repeats, as a {column: value} dict, or None.

        Best effort and only ever reached on the way to exiting, so it costs
        nothing in the normal case. It cannot know which columns the key used,
        so it reports the first wholly repeated row -- which is the duplicate in
        every case this loader has actually produced.
        """
        seen = set()
        for row in rows:
            if row in seen:
                return dict(zip(cols, row, strict=False))
            seen.add(row)
        return None

    def note(self, table: str, source: str, rows: int, generated: str | None) -> None:
        self.meta.append((table, source, rows, generated,
                          dt.datetime.now().isoformat(timespec="seconds")))


def load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"warning: skipping {path.name}: {exc}", file=sys.stderr)
        return None


def role_rows(person_key: str, roles) -> list[tuple]:
    """`roles` is a {role: count} dict in most files and a bare list in
    watchlist.json's `unresolved`. Both arrive here; count is NULL for the list
    form rather than a fabricated 0."""
    out = []
    items = roles.items() if isinstance(roles, dict) else [(r, None) for r in (roles or [])]
    for role, n in items:
        out.append((person_key, role, role_key(role), role_class(role),
                    role_weight(role), n))
    return out


def joined(values) -> str | None:
    return " | ".join(str(v) for v in values) if values else None


def deduped(rows: list[tuple]) -> list[tuple]:
    """Distinct rows, in first-seen order.

    Every junction table here is assembled by appending from several files, so
    a person in both discovery_*.json and watchlist.json contributes the same
    album twice. Three of the six used to go through sorted(set(...)) and three
    went through unchanged, which is the whole of the duplicate-row bug: 777
    person_albums rows for 563 distinct triples, identical.

    dict.fromkeys rather than the obvious sorted(set(...)), and this is not a
    style preference -- sorting these tuples RAISES. They carry None in every
    column a source file may omit (an album with no date, an edge with no
    release count, and `n` which is None for watchlist.json's bare-list role
    form and an int for the dict form everywhere else), and Python 3 will not
    compare None with str or int:

        TypeError: '<' not supported between instances of 'int' and 'NoneType'

    So the fix that looks right turns a silently duplicated row into a failed
    build. dict.fromkeys dedupes on hash alone, never compares, and keeps a
    deterministic order -- which matters because the alternative, a bare set(),
    would order rows by Python's per-process string hash seed and make the
    build unreproducible.
    """
    return list(dict.fromkeys(rows))


# ---- people --------------------------------------------------------------


def load_people(ld: Loader) -> None:
    """Merge the five places a person appears into one `people` row.

    A person is keyed by normalise(primary name) -- the same key discover.py
    uses, so this store inherits its identity model rather than inventing a
    second one. That is a real limitation and it is documented rather than
    papered over: two different Diego Drexlers would collide, and the 4
    Drexlers in the corpus are only distinguishable because Qobuz gives them
    different artist ids. `sources` records which files contributed, so a row
    assembled from three files is visible as such.
    """
    # One mint for every person key in here: a merged person must not be
    # re-split by a file that was derived before the merge existed.
    alias_map = aliases.load()
    # Seed mbids live only in favourites.json. Keyed through the alias map for
    # the reason above the `seeds` schema: the two files disagree on spelling.
    favourite_mbid: dict[str, str] = {}
    blob = load_json(DATA / "favourites.json") or {}
    for entry in (blob.get("artists") if isinstance(blob, dict) else blob) or []:
        if entry.get("name") and entry.get("mbid"):
            favourite_mbid[aliases.person_key(entry["name"], alias_map)] = entry["mbid"]
    people: dict[str, dict] = {}
    names, classes, roles, edges = [], [], [], []
    # Same merge as person_seeds, one grain down: two spellings of one person
    # credited on the SAME album are one row, with the tracks summed and the
    # roles unioned.
    album_rows: dict[tuple, dict] = {}
    # MERGED on their primary key, not appended. Since normalise() began
    # stripping quotes, two spellings in ONE file can mint one key -- Hector
    # "El Father" and Hector El Father are one person -- and two rows with the
    # same key and different numbers is a row the schema forbids. Summing is
    # what `people` already did across seeds; these do it within one.
    person_seeds: dict[tuple, dict] = {}
    co_artist_rows: dict[tuple, dict] = {}
    seeds: list[tuple] = []
    co_artist_albums: dict[tuple, tuple] = {}

    def merge(into: dict, key: tuple, name: str | None, counts: dict,
              first: str | None, last: str | None) -> dict:
        row = into.setdefault(key, {"name": name, "first": first, "last": last})
        for field, value in counts.items():
            row[field] = (row.get(field) or 0) + (value or 0)
        for field, value, pick in (("first", first, min), ("last", last, max)):
            known = [x for x in (row.get(field), value) if x]
            row[field] = pick(known) if known else None
        return row

    def touch(key: str, source: str) -> dict:
        row = people.setdefault(key, {"person_key": key, "sources": set()})
        row["sources"].add(source)
        return row

    # discovery_*.json - the credit graph itself
    for path in sorted(DATA.glob("discovery_*.json")):
        blob = load_json(path)
        if not blob:
            continue
        seed = blob.get("seed") or {}
        seed_id = seed.get("qobuz_id")
        seeds.append((
            seed_id, seed.get("name"),
            favourite_mbid.get(aliases.person_key(seed.get("name") or "",
                                                  alias_map)),
            seed.get("store"), seed.get("releases"),
            seed.get("albums_own"), seed.get("albums_guest"),
            seed.get("albums_compilation"),
            seed.get("albums_unbilled"), seed.get("tracks"),
            seed.get("credited_tracks"), len(blob.get("people") or []),
            len(blob.get("co_artists") or []), path.name, blob.get("generated")))
        for artist in blob.get("co_artists") or []:
            # Re-minted from the name, NOT the stored `key`. The file's key
            # was minted by whichever normalise() was current when discover.py
            # wrote it, and `credits` below mints fresh -- so trusting the
            # stored one made the two disagree for every name holding a quote
            # and silently split the person. D25 is the general case.
            key = aliases.person_key((artist.get("names") or [""])[0], alias_map)
            stats = artist.get("stats") or {}
            merge(co_artist_rows, (seed_id, key),
                  (artist.get("names") or [None])[0],
                  {"albums": stats.get("albums"),
                   "their_records": stats.get("their_records"),
                   "seed_records": stats.get("seed_records")},
                  stats.get("first"), stats.get("last"))
            # Keyed, not appended: one album under two spellings of the same
            # co-artist is one row.
            for alb in artist.get("albums") or []:
                co_artist_albums[(seed_id, key, alb.get("album_id"))] = (
                    alb.get("title"), alb.get("date"), alb.get("provenance"))
            # A co-artist is a person too: the names table is how a reader gets
            # from a spelling to a key, and these keys appear nowhere else.
            names += [(key, n) for n in artist.get("names") or []]
        for person in blob.get("people") or []:
            key = aliases.person_key((person.get("names") or [""])[0], alias_map)
            row = touch(key, path.name)
            stats = person.get("stats") or {}
            seed_row = merge(person_seeds, (key, seed.get("qobuz_id")),
                             seed.get("name"),
                             {"albums": stats.get("albums"),
                              "own_albums": stats.get("own_albums"),
                              "tracks": stats.get("tracks")},
                             stats.get("first"), stats.get("last"))
            seed_row["source"] = path.name
            # The role from whichever spelling did the most, same rule as
            # `people.top_role` one block down.
            if (seed_row.get("top_role") is None
                    or (stats.get("albums") or 0) >= (seed_row.get("_top") or 0)):
                seed_row["top_role"] = stats.get("top_role")
                seed_row["_top"] = stats.get("albums") or 0
            # SUMMED over the seeds this person appears in, never overwritten:
            # "albums of any seed's that they worked on". For "how embedded in
            # ONE seed's catalogue" -- which is what the scoring means -- read
            # person_seeds. top_role comes from the seed where they did the
            # most, since that is what they mainly are.
            busiest = (row.get("albums") or 0) <= (stats.get("albums") or 0)
            row.update({
                "name": (person.get("names") or [None])[0],
                "cover_source_only": bool(person.get("cover_source_only")),
                "albums": (row.get("albums") or 0) + (stats.get("albums") or 0),
                "own_albums": (row.get("own_albums") or 0) + (stats.get("own_albums") or 0),
                "tracks": (row.get("tracks") or 0) + (stats.get("tracks") or 0),
                "seeds": (row.get("seeds") or 0) + 1,
                "top_role": stats.get("top_role") if busiest else row.get("top_role"),
                "first_seen": min(x for x in (row.get("first_seen"), stats.get("first")) if x)
                              if (row.get("first_seen") or stats.get("first")) else None,
                "last_seen": max(x for x in (row.get("last_seen"), stats.get("last")) if x)
                             if (row.get("last_seen") or stats.get("last")) else None,
            })
            names += [(key, n) for n in person.get("names") or []]
            classes += [(key, c) for c in person.get("classes") or []]
            roles += role_rows(key, person.get("roles"))
            for alb in person.get("albums") or []:
                album_key = (seed_id, key, alb.get("album_id"))
                held = album_rows.setdefault(album_key, {
                    "provenance": alb.get("provenance"),
                    "title": alb.get("title"), "date": alb.get("date"),
                    "tracks": 0, "roles": set()})
                held["tracks"] = (held["tracks"] or 0) + (alb.get("tracks") or 0)
                held["roles"].update(alb.get("roles") or [])
        ld.note("people", path.name, len(blob.get("people") or []), blob.get("generated"))
        ld.note("co_artists", path.name, len(blob.get("co_artists") or []),
                blob.get("generated"))

    # watchlist.json - resolved Qobuz ids, plus the ones that failed to resolve
    wl = load_json(DATA / "watchlist.json") if (DATA / "watchlist.json").exists() else None
    if wl:
        for artist in wl.get("artists") or []:
            key = aliases.person_key(artist.get("name") or "", alias_map)
            row = touch(key, "watchlist.json")
            stats, res = artist.get("stats") or {}, artist.get("resolved") or {}
            row.update({
                "name": row.get("name") or artist.get("name"),
                "qobuz_id": artist.get("qobuz_id"),
                "watch": bool(artist.get("watch")),
                "cover_source_only": bool(artist.get("cover_source_only")),
                # First-wins, not summed: watchlist.json is DERIVED from a
                # discovery file, so adding its counts would double the seed
                # that produced it.
                "albums": row.get("albums") or stats.get("albums"),
                "tracks": row.get("tracks") or stats.get("tracks"),
                "top_role": row.get("top_role") or stats.get("top_role"),
                "first_seen": row.get("first_seen") or stats.get("first"),
                "last_seen": row.get("last_seen") or stats.get("last"),
                "resolved_via": res.get("via"),
                "resolved_confidence": res.get("confidence"),
            })
            names += [(key, n) for n in artist.get("name_variants") or []]
            classes += [(key, c) for c in artist.get("classes") or []]
            roles += role_rows(key, artist.get("roles"))
            # `appearances` deliberately does NOT reach person_albums. It is a
            # copy of the discovery pass this file was resolved from -- 191
            # rows on the real corpus, 191 of them already present, none
            # unique -- so it adds nothing and makes the table's primary key
            # rest on two files agreeing about a title and a track count.
            # They stopped agreeing the moment the alias map changed a merged
            # person's counts and this derived file still held the old ones.
            # One fact, one source: the EXACT step that produced it.
        for person in wl.get("unresolved") or []:
            key = aliases.person_key((person.get("names") or [""])[0], alias_map)
            row = touch(key, "watchlist.json:unresolved")
            row.setdefault("name", (person.get("names") or [None])[0])
            row["unresolved_reason"] = person.get("reason")
            row["albums"] = row.get("albums") or person.get("albums")
            names += [(key, n) for n in person.get("names") or []]
            classes += [(key, c) for c in person.get("classes") or []]
            roles += role_rows(key, person.get("roles"))
        ld.note("people", "watchlist.json",
                len(wl.get("artists") or []) + len(wl.get("unresolved") or []),
                wl.get("generated"))

    # discogs_watchlist.json - the people Qobuz cannot see, plus their edges
    discogs_file = DATA / "discogs_watchlist.json"
    dw = load_json(discogs_file) if discogs_file.exists() else None
    if dw:
        for person in dw.get("recovered") or []:
            key = aliases.person_key((person.get("names") or [""])[0], alias_map)
            row = touch(key, "discogs_watchlist.json")
            sel = person.get("selectivity") or {}
            row.update({
                "name": row.get("name") or (person.get("names") or [None])[0],
                "discogs_id": person.get("discogs_id"),
                "discogs_total_releases": person.get("discogs_total_releases"),
                "selectivity": sel.get("score"), "selectivity_band": sel.get("band"),
            })
            names += [(key, n) for n in person.get("names") or []]
            if person.get("discogs_name"):
                names.append((key, person["discogs_name"]))
            roles += role_rows(key, person.get("roles"))
            for edge in person.get("worked_with") or []:
                edges.append((key, edge.get("name"), edge.get("releases"),
                              joined(edge.get("roles")), "worked_with"))
        for person in dw.get("still_unresolved") or []:
            key = aliases.person_key((person.get("names") or [""])[0], alias_map)
            row = touch(key, "discogs_watchlist.json:still_unresolved")
            row.setdefault("name", (person.get("names") or [None])[0])
            row["unresolved_reason"] = person.get("reason")
            row["discogs_id"] = row.get("discogs_id") or person.get("discogs_id")
            names += [(key, n) for n in person.get("names") or []]
        ld.note("person_edges", "discogs_watchlist.json", len(edges), dw.get("generated"))

        cands, cand_via = [], []
        for cand in dw.get("collaborator_candidates") or []:
            cands.append((cand.get("name"), cand.get("releases")))
            for via in cand.get("via") or []:
                cand_via.append((cand.get("name"), via.get("name"),
                                 aliases.person_key(via.get("name") or "", alias_map),
                                 via.get("discogs_id"),
                                 joined(via.get("roles")), via.get("person_seed_albums"),
                                 via.get("role_weight"), via.get("selectivity"),
                                 via.get("selectivity_band")))
        ld.insert("discogs_candidates", ["name", "releases"], cands)
        ld.insert("discogs_candidate_via",
                  ["name", "person_name", "person_key", "discogs_id", "roles",
                   "person_seed_albums", "role_weight", "selectivity", "selectivity_band"],
                  cand_via)
        ld.note("discogs_candidates", "discogs_watchlist.json", len(cands), dw.get("generated"))

    cols = ["person_key", "name", "qobuz_id", "discogs_id", "watch",
            "cover_source_only", "albums", "own_albums", "tracks", "seeds",
            "top_role", "first_seen",
            "last_seen", "resolved_via", "resolved_confidence", "unresolved_reason",
            "discogs_total_releases", "selectivity", "selectivity_band", "sources"]
    ld.insert("people", cols,
              [tuple(joined(sorted(r["sources"])) if c == "sources" else r.get(c)
                     for c in cols) for r in people.values()])
    # Per (person, seed), which is the grain albums and tracks are actually
    # measured at -- see the table comment in SCHEMA.
    ld.insert("person_seeds",
              ["person_key", "seed_qobuz_id", "seed_name", "source", "albums",
               "own_albums", "tracks", "top_role", "first_seen", "last_seen"],
              [(key, seed_id, row["name"], row.get("source"), row.get("albums"),
                row.get("own_albums"), row.get("tracks"), row.get("top_role"),
                row.get("first"), row.get("last"))
               for (key, seed_id), row in person_seeds.items()])
    ld.insert("person_names", ["person_key", "name"], deduped(names))
    # A junction rather than a column, because multi-seed intersection is a
    # FILTER: "keep people who appear in 3+ discovery graphs" (README:122) is a
    # HAVING COUNT(*) on this table, and unanswerable against a joined string.
    ld.insert("person_sources", ["person_key", "source"],
              deduped([(k, src) for k, r in people.items()
                       for src in sorted(r["sources"])]))
    ld.insert("person_classes", ["person_key", "class"], deduped(classes))
    ld.insert("person_roles",
              ["person_key", "role", "role_key", "role_class", "role_weight", "n"],
              deduped(roles))
    ld.insert("person_albums",
              ["seed_qobuz_id", "person_key", "album_id", "provenance", "title",
               "date", "tracks", "roles"],
              [(seed_id, key, album_id, row["provenance"], row["title"],
                row["date"], row["tracks"], joined(sorted(row["roles"])))
               for (seed_id, key, album_id), row in album_rows.items()])
    ld.insert("seeds",
              ["seed_qobuz_id", "name", "mbid", "store", "releases", "albums_own",
               "albums_guest", "albums_compilation", "albums_unbilled",
               "tracks", "credited_tracks", "people", "co_artists",
               "source", "generated"], deduped(seeds))
    ld.insert("co_artists",
              ["seed_qobuz_id", "person_key", "name", "albums", "their_records",
               "seed_records", "first_seen", "last_seen"],
              [(seed_id, key, row["name"], row.get("albums"),
                row.get("their_records"), row.get("seed_records"),
                row.get("first"), row.get("last"))
               for (seed_id, key), row in co_artist_rows.items()])
    ld.insert("co_artist_albums",
              ["seed_qobuz_id", "person_key", "album_id", "title", "date",
               "provenance"],
              [(seed_id, key, album_id, *rest)
               for (seed_id, key, album_id), rest in co_artist_albums.items()])
    ld.insert("person_edges",
              ["person_key", "other_name", "releases", "roles", "kind"],
              deduped(edges))


# ---- releases ------------------------------------------------------------


def load_releases(ld: Loader) -> None:
    """pool.json and pool_discogs.json into one table, keyed (album_id, source).

    Keyed (album_id, source) because both pools hold QOBUZ album ids reached by
    different paths, so the ids collide and album_id alone is not unique.

    Unioning them is also how the store earns its keep on day one. README:139
    records pool_discogs as carrying genre and label on 0 of 6,392 rows. One
    query says otherwise:

        SELECT source, COUNT(*), COUNT(genre), COUNT(label)
        FROM releases GROUP BY source
        -> discogs  6390  6390  6390
        -> qobuz    1470  1470  1470

    Both are complete. The file was regenerated on 2026-09-02 and the fix landed;
    the README was not updated. Cheap to check, invisible until the two shapes sat
    in one table.
    """
    for name, source in (("pool.json", "qobuz"), ("pool_discogs.json", "discogs")):
        path = DATA / name
        if not path.exists():
            continue
        blob = load_json(path)
        if not blob:
            continue
        rows, artists = [], []
        for rel in blob.get("pool") or []:
            via = rel.get("via") or {}
            sig = via.get("signal") or {}
            # The referring role arrives under two names: the Discogs path
            # records which credit referred (`through_roles`), the Qobuz path
            # only the person's top role. Both are "what was this reached
            # through", so both feed via_referral_classes.
            referral = via.get("through_roles") or (
                [via["top_role"]] if via.get("top_role") else [])
            credited = rel.get("artists") or []
            rows.append((
                rel.get("album_id"), source, (blob.get("seed") or {}).get("qobuz_id"),
                rel.get("title"), rel.get("date"),
                rel.get("tracks"), bool(rel.get("hires")), bool(rel.get("streamable")),
                rel.get("label"), rel.get("genre"),
                via.get("name"), via.get("qobuz_id"), via.get("path"),
                via.get("top_role"), via.get("seed_albums"),
                joined(via.get("through")), joined(via.get("through_roles")),
                joined(sorted({role_class(r) for r in referral})),
                bool(credited) and normalise(credited[0]) == normalise(via.get("name") or ""),
                via.get("albums_count"), via.get("discogs_releases"),
                sig.get("score"), sig.get("role_weight"), sig.get("selectivity"),
                sig.get("selectivity_band"),
                # The two paths name it differently: the Discogs pool records
                # whose seed-album count was used (`person_seed_albums`), the
                # Qobuz pool its own (`seed_albums`). One column either way, or
                # half the table reads NULL and nothing says why.
                sig.get("person_seed_albums", sig.get("seed_albums")),
                sig.get("embedded"), sig.get("match_confidence"),
                sig.get("own_albums"), joined(sig.get("flags"))))
            artists += [(rel.get("album_id"), source, a, normalise(a))
                        for a in rel.get("artists") or []]
        ld.insert("releases",
                  ["album_id", "source", "seed_qobuz_id", "title", "date",
                   "tracks", "hires",
                   "streamable", "label", "genre", "via_name", "via_qobuz_id",
                   "via_path", "via_top_role", "via_seed_albums", "via_through",
                   "via_through_roles", "via_referral_classes",
                   "via_is_first_artist", "via_albums_count",
                   "via_discogs_releases", "sig_score", "sig_role_weight",
                   "sig_selectivity", "sig_selectivity_band",
                   "sig_person_seed_albums", "sig_embedded",
                   "sig_match_confidence", "sig_own_albums", "sig_flags"], rows)
        ld.insert("release_artists", ["album_id", "source", "name", "name_key"],
                  artists)
        ld.note("releases", name, len(rows), blob.get("generated"))


# ---- songs ---------------------------------------------------------------


def load_artist_genres(ld: Loader) -> None:
    """cache/musicbrainz_genres/<mbid>.json -> one row per (mbid, genre).

    Its own cache directory, not the artist documents: widening their `inc`
    would turn all 154 of them into refetches at 1.2s each, which is the cost
    D34 declined. Absent directory is not an error -- the grouping treats a
    seed with no genres as un-vetoable rather than unlinkable.
    """
    rows = []
    for path in sorted(glob.glob("cache/musicbrainz_genres/*.json")):
        blob = load_json(Path(path))
        if not blob:
            continue
        mbid = Path(path).stem
        rows += [(mbid, g.get("name"), g.get("count") or 0)
                 for g in blob if g.get("name")]
    if not rows:
        return
    ld.insert("artist_genres", ["mbid", "genre", "votes"], deduped(rows))
    ld.note("artist_genres", "cache/musicbrainz_genres", len(rows), None)


def load_ubiquity(ld: Loader) -> None:
    """data/ubiquity.json -> one row per person. Absent file is not an error.

    Optional on purpose: `ubiquity.py` costs 1,160 Discogs requests at 25/min,
    so a fresh clone must build a store without it. Every consumer reads the
    count through policy.ubiquity_factor(), which is neutral on None, and a
    store with no `ubiquity` rows ranks exactly as it did before the table
    existed.
    """
    path = DATA / "ubiquity.json"
    if not path.exists():
        return
    blob = load_json(path)
    if not blob:
        return
    rows = [(p.get("person_key"), p.get("name"), p.get("discogs_id"),
             p.get("discogs_name"), p.get("match"), p.get("total_releases"))
            for p in blob.get("people") or [] if p.get("person_key")]
    ld.insert("ubiquity", ["person_key", "name", "discogs_id", "discogs_name",
                           "match", "total_releases"], deduped(rows))
    ld.note("ubiquity", path.name, len(rows), blob.get("generated"))


def load_songs(ld: Loader) -> None:
    for path in sorted(DATA.glob("writing_*.json")):
        blob = load_json(path)
        if not blob:
            continue
        query = ((blob.get("artist") or {}).get("query")) or path.stem
        songs, titles, roles, votes, cocomp, performers = [], [], [], [], [], []
        for song in blob.get("songs") or []:
            key = song.get("song")
            songs.append((key, query, song.get("title"), song.get("tier"),
                          bool(song.get("tier_disagreement")),
                          bool(song.get("own_recording")),
                          song.get("performer_count"),
                          song.get("performer_count_excl_mills"),
                          joined(song.get("flags"))))
            titles += [(key, query, t) for t in song.get("variants") or []]
            roles += [(key, query, r) for r in song.get("roles") or []]
            votes += [(key, query, t, n) for t, n in (song.get("tier_votes") or {}).items()]
            cocomp += [(key, query, n, c) for n, c in (song.get("co_composers") or {}).items()]
            for perf in song.get("performers") or []:
                for album in perf.get("albums") or [None]:
                    performers.append((key, query, perf.get("name"),
                                       normalise(perf.get("name") or ""), album,
                                       bool(perf.get("covers_mill"))))
        ld.insert("songs", ["song_key", "artist_query", "title", "tier",
                            "tier_disagreement", "own_recording", "performer_count",
                            "performer_count_excl_mills", "flags"], songs)
        ld.insert("song_titles", ["song_key", "artist_query", "title"], titles)
        ld.insert("song_roles", ["song_key", "artist_query", "role"], roles)
        ld.insert("song_tier_votes", ["song_key", "artist_query", "tier", "n"], votes)
        ld.insert("song_co_composers", ["song_key", "artist_query", "name", "n"], cocomp)
        ld.insert("song_performers",
                  ["song_key", "artist_query", "performer_name", "performer_key",
                   "album_title", "covers_mill"], performers)
        ld.note("songs", path.name, len(songs), blob.get("generated"))


# ---- cache: tracks and credits ------------------------------------------


def load_cache(ld: Loader) -> None:
    """The two cache dirs, with every `performers` string expanded.

    This is the table the rest of the repo does not have: 11,926 (person, role)
    rows against a track, with policy's weight and class already attached. The
    parse is core.credits.parse_performers, so the co-artist rule it documents
    applies here too and "Rueda de Candombe" does not become a role.

    Scope, so an empty result is not read as an absence: cache/credits holds the
    SEED's 63 albums (265 tracks) -- it is what discover.py fetched -- while
    cache/search holds the 910 track/search rows for the writing step. Neither
    covers the 7,862-release candidate pool, whose credits were never fetched.

    person_key goes through the alias map, not just `normalise`. It has to:
    the discovery files key Inflo's 37 Composer credits under "inflo" now, and
    a `credits` table that still keyed them under "dean josiah cover" would
    make every join to it -- the evidence behind each co-artist sentence, and
    signal_for's roles -- silently miss half the person. core/aliases.py says
    why the file exists.
    """
    alias_map = aliases.load()
    tracks, credits = [], []

    for path in sorted(glob.glob("cache/search/*.json")):
        stem = Path(path).stem                      # <store>_<query>_<offset>
        store, _, rest = stem.partition("_")
        query = rest.rsplit("_", 1)[0].replace("%20", " ")
        blob = load_json(Path(path))
        if not blob:
            continue
        for track in blob.get("items") or []:
            album = track.get("album") or {}
            tracks.append((store, query, album.get("id"), album.get("title"),
                           track.get("title"),
                           (track.get("performer") or {}).get("name"),
                           track.get("performers")))
            for name, roles in parse_performers(track.get("performers") or ""):
                key = aliases.person_key(name, alias_map)
                for role in roles:
                    credits.append(("search", store, album.get("id"), None,
                                    track.get("title"), name, key, role,
                                    role_key(role), role_class(role), role_weight(role)))

    for path in sorted(glob.glob("cache/credits/*.json")):
        stem = Path(path).stem                      # <store>_<album_id>
        store, _, album_id = stem.partition("_")
        blob = load_json(Path(path))
        if not blob:
            continue
        for track in blob:
            for name, roles in parse_performers(track.get("performers") or ""):
                key = aliases.person_key(name, alias_map)
                for role in roles:
                    credits.append(("credits", store, album_id, track.get("id"),
                                    track.get("title"), name, key, role,
                                    role_key(role), role_class(role), role_weight(role)))

    ld.insert("tracks", ["store", "query", "album_id", "album_title", "track_title",
                         "performer_name", "performers_raw"], tracks)
    ld.insert("credits", ["source", "store", "album_id", "track_id", "track_title",
                          "person_name", "person_key", "role", "role_key",
                          "role_class", "role_weight"], credits)
    ld.note("tracks", "cache/search", len(tracks), None)
    ld.note("credits", "cache/search + cache/credits", len(credits), None)


# ---- listens -------------------------------------------------------------


def load_listens(ld: Loader, path: Path) -> None:
    """The ListenBrainz export, straight out of the zip.

    Kept because it is the only user-preference data in the project (README:78)
    and because the honest evaluation in README:156 is a time split over it --
    "build the graph on listens up to one year end, ask whether it contains the
    artists adopted the next year". That is a windowed join, so `year` is
    materialised rather than computed per query.

    `recording_mbid` and `artist_mbid` come out of ListenBrainz's own
    `mbid_mapping`, which matters more than the play counts: they are the only
    MusicBrainz identifiers anywhere in this project, and MB works are where
    lyrics language lives. This is the existing half of a crosswalk whose other
    half is the Qobuz ISRC the cache does not keep yet.
    """
    rows = []
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if not name.startswith("listens/") or not name.endswith(".jsonl"):
                continue
            year = int(name.split("/")[1])
            with zf.open(name) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        listen = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    md = listen.get("track_metadata") or {}
                    mapping = md.get("mbid_mapping") or {}
                    ts = listen.get("listened_at")
                    date = (dt.datetime.fromtimestamp(ts, dt.UTC).date().isoformat()
                            if isinstance(ts, (int, float)) else None)
                    artist = md.get("artist_name") or ""
                    rows.append((ts, date, year, md.get("track_name"), artist,
                                 normalise(artist), md.get("release_name"),
                                 mapping.get("recording_mbid"),
                                 (mapping.get("artist_mbids") or [None])[0],
                                 mapping.get("release_mbid")))
    ld.insert("listens",
              ["listened_at", "listened_date", "year", "track_name", "artist_name",
               "artist_key", "release_name", "recording_mbid", "artist_mbid",
               "release_mbid"], rows)
    ld.note("listens", path.name, len(rows), None)


# ---- main ----------------------------------------------------------------


def summarise(con, engine: str) -> int:
    rows = con.execute(
        "SELECT table_name, source, rows, generated FROM meta ORDER BY table_name").fetchall()
    if not rows:
        print("meta is empty - was this DB built by load.py?")
        return 1
    print(f"{'table':<22}{'source':<38}{'rows':>8}  generated")
    for table, source, n, generated in rows:
        print(f"{table:<22}{(source or ''):<38}{n:>8}  {generated or '-'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Load every JSON already on disk into one queryable DB file. "
                    "Fetches nothing.")
    parser.add_argument("--db", default=str(DB_DEFAULT), help=f"default {DB_DEFAULT}")
    parser.add_argument("--engine", default="auto", choices=["auto", "duckdb", "sqlite"],
                        help="default stdlib sqlite3, which builds in 2s. duckdb "
                             "builds the same rows in 69s - to QUERY with duckdb, "
                             "keep sqlite here and ATTACH it (docs/duckdb.md)")
    parser.add_argument("--listens", help="path to a ListenBrainz export zip "
                                          f"(default: newest match for {LISTENS_GLOB})")
    parser.add_argument("--no-listens", action="store_true",
                        help="skip the export - the only slow part of the load")
    parser.add_argument("--summary", action="store_true",
                        help="print row counts of an existing DB and exit, no rebuild")
    args = parser.parse_args()

    db = Path(args.db)
    if args.summary:
        if not db.exists():
            raise SystemExit(f"{db} not found - run ./stages/load.py first")
        con, engine = connect(db, args.engine)
        return summarise(con, engine)

    # Resolve the engine BEFORE touching the existing file (see resolve_engine).
    engine = resolve_engine(args.engine)
    # The DB is derived and disposable: always rebuilt, never migrated.
    if db.exists():
        db.unlink()
    con, engine = connect(db, engine)
    print(f"engine: {engine}  ->  {db}", file=sys.stderr)
    if engine == "duckdb":
        print("  (duckdb builds ~30x slower than sqlite here; to query with duckdb "
              "instead, see docs/duckdb.md)", file=sys.stderr)

    for statement in SCHEMA.strip().split(";"):
        if statement.strip():
            con.execute(statement)

    ld = Loader(con, engine)
    os.chdir(ROOT)               # cache/* globs are repo-relative
    load_people(ld)
    load_releases(ld)
    load_ubiquity(ld)
    load_artist_genres(ld)
    load_songs(ld)
    load_cache(ld)

    if not args.no_listens:
        chosen = Path(args.listens) if args.listens else listens.newest_export(LISTENS_GLOB)
        if chosen and chosen.exists():
            print(f"listens: {chosen.name}", file=sys.stderr)
            load_listens(ld, chosen)
        else:
            print("listens: no export found, skipping (--listens PATH to point at one)",
                  file=sys.stderr)

    ld.insert("meta", ["table_name", "source", "rows", "generated", "loaded_at"], ld.meta)
    # After the rows, never before: see the comment on INDEXES.
    built = 0
    for statement in INDEXES.strip().split(";"):
        if statement.strip():
            con.execute(statement)
            built += 1
    for statement in VIEWS.strip().split(";"):
        if statement.strip():
            con.execute(statement)
    con.commit()

    print(f"\nbuilt {db.name} ({db.stat().st_size / 1e6:.1f} MB, {built} indexes)")
    for table, n in sorted(ld.counts.items(), key=lambda kv: -kv[1]):
        print(f"  {table:<24}{n:>8}")
    print("\nsee docs/store.md for queries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
