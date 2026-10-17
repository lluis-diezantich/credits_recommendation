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
import sys
import zipfile
from pathlib import Path

from core.credits import parse_performers
from core.names import normalise
from core.paths import DATA, ROOT
from policy import role_class, role_key, role_weight

DB_DEFAULT = DATA / "music.db"
# The export lives OUTSIDE the repo (README:78). Found, not required.
LISTENS_GLOB = str(ROOT.parent / "listenbrainz_*.zip")


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
    person_key TEXT, name TEXT, qobuz_id INTEGER, discogs_id INTEGER,
    watch BOOLEAN, cover_source_only BOOLEAN,
    albums INTEGER, tracks INTEGER, top_role TEXT, first_seen TEXT, last_seen TEXT,
    resolved_via TEXT, resolved_confidence TEXT, unresolved_reason TEXT,
    discogs_total_releases INTEGER, selectivity REAL, selectivity_band TEXT,
    sources TEXT);
CREATE TABLE person_names   (person_key TEXT, name TEXT);
CREATE TABLE person_sources (person_key TEXT, source TEXT);
CREATE TABLE person_classes (person_key TEXT, class TEXT);
CREATE TABLE person_roles   (person_key TEXT, role TEXT, role_key TEXT,
                             role_class TEXT, role_weight REAL, n INTEGER);
CREATE TABLE person_albums  (person_key TEXT, album_id TEXT, title TEXT,
                             date TEXT, tracks INTEGER, roles TEXT);
CREATE TABLE person_edges   (person_key TEXT, other_name TEXT, releases INTEGER,
                             roles TEXT, kind TEXT);

-- releases (candidate pool) --------------------------------------------
CREATE TABLE releases (
    album_id TEXT, source TEXT, title TEXT, date TEXT, tracks INTEGER,
    hires BOOLEAN, streamable BOOLEAN, label TEXT, genre TEXT,
    via_name TEXT, via_qobuz_id INTEGER, via_path TEXT, via_top_role TEXT,
    via_seed_albums INTEGER, via_through TEXT,
    sig_score REAL, sig_role_weight REAL, sig_selectivity REAL,
    sig_selectivity_band TEXT, sig_person_seed_albums INTEGER,
    sig_embedded REAL, sig_flags TEXT);
CREATE TABLE release_artists (album_id TEXT, source TEXT, name TEXT);

-- songs (writing_*.json) ----------------------------------------------
CREATE TABLE songs (
    song_key TEXT, artist_query TEXT, title TEXT, tier TEXT,
    tier_disagreement BOOLEAN, own_recording BOOLEAN,
    performer_count INTEGER, performer_count_excl_mills INTEGER, flags TEXT);
CREATE TABLE song_titles       (song_key TEXT, artist_query TEXT, title TEXT);
CREATE TABLE song_roles        (song_key TEXT, artist_query TEXT, role TEXT);
CREATE TABLE song_tier_votes   (song_key TEXT, artist_query TEXT, tier TEXT, n INTEGER);
CREATE TABLE song_co_composers (song_key TEXT, artist_query TEXT, name TEXT, n INTEGER);
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
CREATE TABLE discogs_candidates (name TEXT, releases INTEGER);
CREATE TABLE discogs_candidate_via (
    name TEXT, person_name TEXT, person_key TEXT, discogs_id INTEGER, roles TEXT,
    person_seed_albums INTEGER, role_weight REAL, selectivity REAL,
    selectivity_band TEXT);

-- listens --------------------------------------------------------------
CREATE TABLE listens (
    listened_at INTEGER, listened_date TEXT, year INTEGER,
    track_name TEXT, artist_name TEXT, artist_key TEXT, release_name TEXT,
    recording_mbid TEXT, artist_mbid TEXT, release_mbid TEXT);
"""

VIEWS = """
CREATE VIEW v_releases_scored AS
SELECT source, album_id, title, date, label, genre, via_name, via_top_role,
       sig_score, sig_selectivity_band, sig_flags
FROM releases;

CREATE VIEW v_people AS
SELECT p.person_key, p.name, p.qobuz_id, p.discogs_id, p.albums, p.tracks,
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
        if rows:
            marks = ",".join("?" * len(cols))
            self.con.executemany(
                f"INSERT INTO {table} ({','.join(cols)}) VALUES ({marks})", rows)
        self.counts[table] = self.counts.get(table, 0) + len(rows)

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
    people: dict[str, dict] = {}
    names, classes, roles, albums, edges = [], [], [], [], []

    def touch(key: str, source: str) -> dict:
        row = people.setdefault(key, {"person_key": key, "sources": set()})
        row["sources"].add(source)
        return row

    # discovery_*.json - the credit graph itself
    for path in sorted(DATA.glob("discovery_*.json")):
        blob = load_json(path)
        if not blob:
            continue
        for person in blob.get("people") or []:
            key = person.get("key") or normalise((person.get("names") or [""])[0])
            row = touch(key, path.name)
            stats = person.get("stats") or {}
            row.update({
                "name": (person.get("names") or [None])[0],
                "cover_source_only": bool(person.get("cover_source_only")),
                "albums": stats.get("albums"), "tracks": stats.get("tracks"),
                "top_role": stats.get("top_role"),
                "first_seen": stats.get("first"), "last_seen": stats.get("last"),
            })
            names += [(key, n) for n in person.get("names") or []]
            classes += [(key, c) for c in person.get("classes") or []]
            roles += role_rows(key, person.get("roles"))
            for alb in person.get("albums") or []:
                albums.append((key, alb.get("album_id"), alb.get("title"),
                               alb.get("date"), alb.get("tracks"),
                               joined(alb.get("roles"))))
        ld.note("people", path.name, len(blob.get("people") or []), blob.get("generated"))

    # watchlist.json - resolved Qobuz ids, plus the ones that failed to resolve
    wl = load_json(DATA / "watchlist.json") if (DATA / "watchlist.json").exists() else None
    if wl:
        for artist in wl.get("artists") or []:
            key = normalise(artist.get("name") or "")
            row = touch(key, "watchlist.json")
            stats, res = artist.get("stats") or {}, artist.get("resolved") or {}
            row.update({
                "name": row.get("name") or artist.get("name"),
                "qobuz_id": artist.get("qobuz_id"),
                "watch": bool(artist.get("watch")),
                "cover_source_only": bool(artist.get("cover_source_only")),
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
            for alb in artist.get("appearances") or []:
                albums.append((key, alb.get("album_id"), alb.get("title"),
                               alb.get("date"), alb.get("tracks"),
                               joined(alb.get("roles"))))
        for person in wl.get("unresolved") or []:
            key = normalise((person.get("names") or [""])[0])
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
            key = normalise((person.get("names") or [""])[0])
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
            key = normalise((person.get("names") or [""])[0])
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
                                 normalise(via.get("name") or ""), via.get("discogs_id"),
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
            "cover_source_only", "albums", "tracks", "top_role", "first_seen",
            "last_seen", "resolved_via", "resolved_confidence", "unresolved_reason",
            "discogs_total_releases", "selectivity", "selectivity_band", "sources"]
    ld.insert("people", cols,
              [tuple(joined(sorted(r["sources"])) if c == "sources" else r.get(c)
                     for c in cols) for r in people.values()])
    ld.insert("person_names", ["person_key", "name"], sorted(set(names)))
    # A junction rather than a column, because multi-seed intersection is a
    # FILTER: "keep people who appear in 3+ discovery graphs" (README:122) is a
    # HAVING COUNT(*) on this table, and unanswerable against a joined string.
    ld.insert("person_sources", ["person_key", "source"],
              sorted({(k, src) for k, r in people.items() for src in r["sources"]}))
    ld.insert("person_classes", ["person_key", "class"], sorted(set(classes)))
    ld.insert("person_roles",
              ["person_key", "role", "role_key", "role_class", "role_weight", "n"], roles)
    ld.insert("person_albums",
              ["person_key", "album_id", "title", "date", "tracks", "roles"], albums)
    ld.insert("person_edges",
              ["person_key", "other_name", "releases", "roles", "kind"], edges)


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
            rows.append((
                rel.get("album_id"), source, rel.get("title"), rel.get("date"),
                rel.get("tracks"), bool(rel.get("hires")), bool(rel.get("streamable")),
                rel.get("label"), rel.get("genre"),
                via.get("name"), via.get("qobuz_id"), via.get("path"),
                via.get("top_role"), via.get("seed_albums"),
                joined(via.get("through")),
                sig.get("score"), sig.get("role_weight"), sig.get("selectivity"),
                sig.get("selectivity_band"), sig.get("person_seed_albums"),
                sig.get("embedded"), joined(sig.get("flags"))))
            artists += [(rel.get("album_id"), source, a) for a in rel.get("artists") or []]
        ld.insert("releases",
                  ["album_id", "source", "title", "date", "tracks", "hires",
                   "streamable", "label", "genre", "via_name", "via_qobuz_id",
                   "via_path", "via_top_role", "via_seed_albums", "via_through",
                   "sig_score", "sig_role_weight", "sig_selectivity",
                   "sig_selectivity_band", "sig_person_seed_albums", "sig_embedded",
                   "sig_flags"], rows)
        ld.insert("release_artists", ["album_id", "source", "name"], artists)
        ld.note("releases", name, len(rows), blob.get("generated"))


# ---- songs ---------------------------------------------------------------


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
    """
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
                for role in roles:
                    credits.append(("search", store, album.get("id"), None,
                                    track.get("title"), name, normalise(name), role,
                                    role_key(role), role_class(role), role_weight(role)))

    for path in sorted(glob.glob("cache/credits/*.json")):
        stem = Path(path).stem                      # <store>_<album_id>
        store, _, album_id = stem.partition("_")
        blob = load_json(Path(path))
        if not blob:
            continue
        for track in blob:
            for name, roles in parse_performers(track.get("performers") or ""):
                for role in roles:
                    credits.append(("credits", store, album_id, track.get("id"),
                                    track.get("title"), name, normalise(name), role,
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
    load_songs(ld)
    load_cache(ld)

    if not args.no_listens:
        chosen = Path(args.listens) if args.listens else None
        if chosen is None:
            found = sorted(glob.glob(LISTENS_GLOB))
            chosen = Path(found[-1]) if found else None
        if chosen and chosen.exists():
            print(f"listens: {chosen.name}", file=sys.stderr)
            load_listens(ld, chosen)
        else:
            print("listens: no export found, skipping (--listens PATH to point at one)",
                  file=sys.stderr)

    ld.insert("meta", ["table_name", "source", "rows", "generated", "loaded_at"], ld.meta)
    for statement in VIEWS.strip().split(";"):
        if statement.strip():
            con.execute(statement)
    con.commit()

    print(f"\nbuilt {db.name} ({db.stat().st_size / 1e6:.1f} MB)")
    for table, n in sorted(ld.counts.items(), key=lambda kv: -kv[1]):
        print(f"  {table:<24}{n:>8}")
    print("\nsee docs/store.md for queries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
