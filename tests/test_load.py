"""stages/load.py: the largest file in the repo, and the one with no tests.

299 statements at 0% until now. It is also the easiest of the six uncovered
files to reach, because nothing in it fetches: every input is JSON on disk or a
zip, so the only fixtures needed are small files and a tmp_path.

What is worth asserting here is not "it inserts rows" but the handful of places
the shape of the data is DECIDED, because each is a silent choice that a query
later depends on:

  identity        a person is keyed normalise(primary name), inherited from
                  discover.py rather than invented here, and `releases` is
                  keyed (album_id, source) because the two pools hold colliding
                  Qobuz ids.
  merging         five files contribute to one `people` row, last writer wins
                  per field unless the field is explicitly preserved, and
                  `sources` is what makes a merged row visible as merged.
  absence         a missing file is skipped, not an error. A malformed one
                  warns and is skipped. Neither may take the build down, since
                  the whole contract of this file is that rebuilding is cheap
                  and always works.
  dedup           three of the six junction tables are deduplicated and three
                  are not. That asymmetry is a bug, it is measurable, and it is
                  pinned below with xfail rather than described in a comment.
"""

from __future__ import annotations

import json
import sqlite3
import zipfile

import pytest

import stages.load as load


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A Loader over a real sqlite file with the real SCHEMA applied.

    Not an in-memory DB: `connect` takes a path and main() unlinks it, so the
    file case is the one worth exercising. DATA is redirected at a tmp dir and
    the cwd is moved, because load_cache globs `cache/*` RELATIVELY -- main()
    chdirs to ROOT before calling it, which is a seam worth reproducing rather
    than working around.
    """
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(load, "DATA", data)
    monkeypatch.setattr(load, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)

    con, engine = load.connect(tmp_path / "test.db", "sqlite")
    for statement in load.SCHEMA.strip().split(";"):
        if statement.strip():
            con.execute(statement)

    class Handle:
        def __init__(self):
            self.data = data
            self.tmp = tmp_path
            self.con = con
            self.ld = load.Loader(con, engine)

        def write(self, name, obj):
            (data / name).write_text(json.dumps(obj))

        def cache(self, sub, name, obj):
            d = tmp_path / "cache" / sub
            d.mkdir(parents=True, exist_ok=True)
            (d / name).write_text(json.dumps(obj))

        def rows(self, table, cols="*"):
            return con.execute(f"SELECT {cols} FROM {table}").fetchall()

        def one(self, sql):
            return con.execute(sql).fetchone()

        def count(self, table):
            return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    return Handle()


# ---- the DDL itself ------------------------------------------------------


def test_the_schema_the_indexes_and_the_views_all_execute(store):
    """One test for 150 lines of SQL that nothing else would catch a typo in --
    and the views in particular, since they name columns the schema has to have."""
    for block in (load.INDEXES, load.VIEWS):
        for statement in block.strip().split(";"):
            if statement.strip():
                store.con.execute(statement)
    tables = {r[0] for r in store.rows("sqlite_master", "name")}
    assert {"people", "releases", "songs", "credits", "listens"} <= tables
    assert {"v_releases_scored", "v_people", "v_songs_by_others"} <= tables


def test_every_index_is_created_after_the_rows_not_in_the_schema(store):
    """The 2s rebuild depends on it: an index in SCHEMA is maintained per
    INSERT across 216k rows. If one migrates into SCHEMA this fails."""
    assert "CREATE INDEX" not in load.SCHEMA
    assert load.INDEXES.count("CREATE INDEX") == 45


def test_the_indexes_name_only_real_columns(store):
    """A typo in an index column is silent at write time and only surfaces when
    the statement runs, which is once per build, at the end, after the work."""
    for statement in load.INDEXES.strip().split(";"):
        if statement.strip():
            store.con.execute(statement)       # raises on an unknown column


# ---- helpers ------------------------------------------------------------


def test_joined_folds_a_list_into_one_column():
    assert load.joined(["Producer", "Bass"]) == "Producer | Bass"
    assert load.joined([1, 2]) == "1 | 2"


def test_joined_turns_nothing_into_null_rather_than_an_empty_string():
    """NULL and '' answer differently in SQL: COUNT(col) skips one and not the
    other, which is how docs/store.md's coverage queries read."""
    assert load.joined([]) is None
    assert load.joined(None) is None


def test_role_rows_takes_the_dict_form_most_files_use():
    rows = load.role_rows("jorge drexler", {"Producer": 3, "Bass": 1})
    assert rows[0] == ("jorge drexler", "Producer", "producer", "production", 1.0, 3)
    assert rows[1][-1] == 1


def test_role_rows_takes_the_bare_list_form_watchlist_unresolved_uses():
    """Two shapes arrive here, and the count is NULL for the list form rather
    than a fabricated 0 -- "we were not told" is not "told zero"."""
    rows = load.role_rows("x", ["Producer", "Mastered by"])
    assert [r[-1] for r in rows] == [None, None]
    assert [r[3] for r in rows] == ["production", "engineering"]


def test_role_rows_attaches_policys_weight_and_class_at_load_time():
    """So a query can filter on role_class without importing policy.py."""
    (row,) = load.role_rows("x", {"Mastered by": 1})
    assert row[2:5] == ("masteredby", "engineering", 0.15)


def test_role_rows_of_nothing_is_nothing():
    assert load.role_rows("x", None) == []
    assert load.role_rows("x", {}) == []


def test_load_json_warns_and_returns_none_on_a_malformed_file(tmp_path, capsys):
    """A half-written file must not take the build down. This is the whole
    reason missing and broken inputs are skipped rather than raised."""
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load.load_json(bad) is None
    assert "skipping bad.json" in capsys.readouterr().err


def test_load_json_warns_and_returns_none_on_a_missing_file(tmp_path, capsys):
    assert load.load_json(tmp_path / "nope.json") is None
    assert "skipping nope.json" in capsys.readouterr().err


# ---- Loader -------------------------------------------------------------


def test_the_loader_counts_a_table_it_was_given_no_rows_for(store):
    """0 and absent are different in the summary: a table that loaded nothing
    is evidence the input was empty, not that the step did not run."""
    store.ld.insert("people", ["person_key"], [])
    assert store.ld.counts["people"] == 0


def test_the_loader_accumulates_across_calls(store):
    """load_releases inserts into `releases` once per pool, so the count has to
    add rather than replace or the summary under-reports by a whole file."""
    store.ld.insert("discogs_candidates", ["name", "releases"], [("a", 1)])
    store.ld.insert("discogs_candidates", ["name", "releases"], [("b", 2), ("c", 3)])
    assert store.ld.counts["discogs_candidates"] == 3
    assert store.count("discogs_candidates") == 3


def test_note_records_the_generated_stamp_the_source_file_carried(store):
    store.ld.note("people", "discovery_1.json", 5, "2026-09-01T10:00:00")
    (table, source, rows, generated, loaded_at) = store.ld.meta[0]
    assert (table, source, rows, generated) == ("people", "discovery_1.json", 5,
                                                "2026-09-01T10:00:00")
    assert loaded_at                      # stamped at load time, not from the file


# ---- engine -------------------------------------------------------------


def test_auto_resolves_to_sqlite_and_not_to_whatever_is_installed():
    """Deliberate: pip installing duckdb for the query side must not silently
    turn a 2s build into a 69s one."""
    assert load.resolve_engine("auto") == "sqlite"
    assert load.resolve_engine("sqlite") == "sqlite"


def test_a_missing_duckdb_fails_before_the_old_build_is_deleted(monkeypatch):
    """resolve_engine is separate from connect() for exactly this: main()
    unlinks the DB before rebuilding, so an engine that cannot be had must
    raise first or it takes a working build down with it."""
    import builtins
    real = builtins.__import__

    def no_duckdb(name, *a, **k):
        if name == "duckdb":
            raise ImportError("no duckdb")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_duckdb)
    with pytest.raises(SystemExit, match="duckdb not installed"):
        load.resolve_engine("duckdb")


def test_connect_returns_the_engine_it_actually_opened(tmp_path):
    con, engine = load.connect(tmp_path / "x.db", "sqlite")
    assert engine == "sqlite"
    assert isinstance(con, sqlite3.Connection)


# ---- load_people --------------------------------------------------------


def test_a_person_is_keyed_on_the_normalised_primary_name(store):
    """Inherited from discover.py rather than invented here, so the store does
    not hold a second identity model. Accents and case fold."""
    store.write("discovery_1.json", {"generated": "g", "people": [
        {"names": ["Jorge Drexler"], "stats": {"albums": 6, "top_role": "Producer"}}]})
    load.load_people(store.ld)
    assert store.rows("people", "person_key, name") == [("jorge drexler", "Jorge Drexler")]


def test_an_explicit_key_in_the_file_wins_over_deriving_one(store):
    store.write("discovery_1.json", {"people": [
        {"key": "chosen key", "names": ["Ignored Name"]}]})
    load.load_people(store.ld)
    assert store.one("SELECT person_key FROM people") == ("chosen key",)


def test_one_person_in_three_files_is_one_row_that_says_so(store):
    """The merge is the point of this loader. `sources` is what makes a row
    assembled from three files visible as such rather than looking native."""
    store.write("discovery_1.json", {"people": [
        {"names": ["Carles Campi Campon"], "stats": {"albums": 4}}]})
    store.write("watchlist.json", {"artists": [
        {"name": "Carles Campi Campon", "qobuz_id": 77,
         "resolved": {"via": "autosuggest", "confidence": "exact"}}]})
    store.write("discogs_watchlist.json", {"recovered": [
        {"names": ["Carles Campi Campon"], "discogs_id": 12,
         "discogs_total_releases": 45,
         "selectivity": {"score": 1.0, "band": "selective"}}]})
    load.load_people(store.ld)

    assert store.count("people") == 1
    row = store.one("SELECT qobuz_id, discogs_id, albums, selectivity_band, sources "
                    "FROM people")
    assert row == (77, 12, 4, "selective",
                   "discogs_watchlist.json | discovery_1.json | watchlist.json")


def test_a_later_file_does_not_overwrite_what_an_earlier_one_knew(store):
    """watchlist.json preserves albums/tracks/top_role with `row.get(x) or ...`,
    because discovery_*.json is the file that actually counted them."""
    store.write("discovery_1.json", {"people": [
        {"names": ["X"], "stats": {"albums": 21, "top_role": "Producer"}}]})
    store.write("watchlist.json", {"artists": [
        {"name": "X", "stats": {"albums": 1, "top_role": "Bass"}}]})
    load.load_people(store.ld)
    assert store.one("SELECT albums, top_role FROM people") == (21, "Producer")


def test_person_sources_is_a_junction_so_multi_seed_filtering_is_a_having(store):
    """"keep people who appear in 3+ discovery graphs" is a HAVING COUNT(*) on
    this table, and unanswerable against the joined `sources` string."""
    store.write("discovery_1.json", {"people": [{"names": ["Shared"]}]})
    store.write("discovery_2.json", {"people": [{"names": ["Shared"]},
                                                {"names": ["Only Here"]}]})
    load.load_people(store.ld)
    assert store.one("SELECT COUNT(*) FROM person_sources WHERE person_key='shared'"
                     ) == (2,)
    assert store.one("SELECT person_key FROM person_sources GROUP BY person_key "
                     "HAVING COUNT(*) >= 2") == ("shared",)


def test_the_unresolved_are_loaded_with_their_reason_not_dropped(store):
    """They are the input to resolve_discogs.py, so losing them here would hide
    the 44% of people Qobuz cannot see."""
    store.write("watchlist.json", {"unresolved": [
        {"names": ["Nobody"], "reason": "no_exact_match", "albums": 3,
         "roles": ["Producer"]}]})
    load.load_people(store.ld)
    assert store.one("SELECT name, unresolved_reason, albums FROM people"
                     ) == ("Nobody", "no_exact_match", 3)
    assert store.one("SELECT n FROM person_roles") == (None,)   # list form, no count


def test_an_artists_own_name_is_not_a_name_variant_unless_listed(store):
    """watchlist.json's artist branch reads `name_variants`, never `name`, so
    person_names holds only what the file called a variant."""
    store.write("watchlist.json", {"artists": [
        {"name": "Primary", "name_variants": ["Primary", "Alt Spelling"]}]})
    load.load_people(store.ld)
    assert {r[0] for r in store.rows("person_names", "name")} == {"Primary",
                                                                  "Alt Spelling"}


def test_a_discogs_name_is_added_as_a_variant(store):
    store.write("discogs_watchlist.json", {"recovered": [
        {"names": ["Mauro Refosco"], "discogs_name": "Mauro (5)"}]})
    load.load_people(store.ld)
    assert {r[0] for r in store.rows("person_names", "name")} == {"Mauro Refosco",
                                                                  "Mauro (5)"}


def test_worked_with_edges_are_loaded_with_their_kind(store):
    """The 123 edges that name the people joining disjoint scenes."""
    store.write("discogs_watchlist.json", {"recovered": [
        {"names": ["P"], "worked_with": [
            {"name": "Other", "releases": 4, "roles": ["Bass", "Producer"]}]}]})
    load.load_people(store.ld)
    assert store.rows("person_edges", "person_key, other_name, releases, roles, kind"
                      ) == [("p", "Other", 4, "Bass | Producer", "worked_with")]


def test_collaborator_candidates_carry_the_signal_they_were_scored_on(store):
    store.write("discogs_watchlist.json", {"collaborator_candidates": [
        {"name": "Cand", "releases": 9, "via": [
            {"name": "Via Person", "discogs_id": 5, "roles": ["Producer"],
             "person_seed_albums": 3, "role_weight": 1.0, "selectivity": 0.6,
             "selectivity_band": "moderate"}]}]})
    load.load_people(store.ld)
    assert store.rows("discogs_candidates") == [("Cand", 9)]
    assert store.one("SELECT person_key, role_weight, selectivity_band "
                     "FROM discogs_candidate_via") == ("via person", 1.0, "moderate")


def test_people_with_no_files_at_all_loads_nothing_and_does_not_raise(store):
    """The contract: this stage runs over whatever the others left behind."""
    load.load_people(store.ld)
    assert store.count("people") == 0


def test_a_malformed_people_file_is_skipped_and_the_rest_still_load(store, capsys):
    (store.data / "discovery_bad.json").write_text("{truncated")
    store.write("discovery_ok.json", {"people": [{"names": ["Fine"]}]})
    load.load_people(store.ld)
    assert store.count("people") == 1
    assert "skipping discovery_bad.json" in capsys.readouterr().err


# ---- the dedup asymmetry (a real bug, pinned) ---------------------------
#
# names, sources and classes are inserted through set(); roles, albums and
# edges are not. Measured on the real build: person_names 281/281 distinct,
# person_classes 396/396, but person_roles 923/612 and person_albums 777/563.
#
# xfail(strict=True) rather than asserting the duplicate: these say what the
# loader SHOULD do, they fail today, and the day the three missing set() calls
# land they will pass and pytest will report the xpass as a failure -- which is
# the reminder to delete the marker. Asserting `== 2` instead would quietly
# cement the bug as the specification.


def test_a_name_from_two_files_is_stored_once(store):
    store.write("discovery_1.json", {"people": [{"names": ["Dup"]}]})
    store.write("discovery_2.json", {"people": [{"names": ["Dup"]}]})
    load.load_people(store.ld)
    assert store.count("person_names") == 1      # set() applied here


def test_a_class_from_two_files_is_stored_once(store):
    store.write("discovery_1.json", {"people": [
        {"names": ["Dup"], "classes": ["production"]}]})
    store.write("discovery_2.json", {"people": [
        {"names": ["Dup"], "classes": ["production"]}]})
    load.load_people(store.ld)
    assert store.count("person_classes") == 1    # and here


@pytest.mark.xfail(strict=True, reason="person_roles is inserted without set(); "
                                       "923 rows for 612 distinct pairs in the real build")
def test_a_role_from_two_files_should_be_stored_once(store):
    store.write("discovery_1.json", {"people": [
        {"names": ["Dup"], "roles": {"Producer": 2}}]})
    store.write("discovery_2.json", {"people": [
        {"names": ["Dup"], "roles": {"Producer": 2}}]})
    load.load_people(store.ld)
    assert store.count("person_roles") == 1


@pytest.mark.xfail(strict=True, reason="person_albums is inserted without set(); "
                                       "777 rows for 563 distinct triples, identical")
def test_the_same_album_from_two_files_should_be_stored_once(store):
    album = {"album_id": "a1", "title": "T", "date": "2020-01-01", "tracks": 10,
             "roles": ["Producer"]}
    store.write("discovery_1.json", {"people": [{"names": ["Dup"], "albums": [album]}]})
    store.write("watchlist.json", {"artists": [
        {"name": "Dup", "appearances": [album]}]})
    load.load_people(store.ld)
    assert store.count("person_albums") == 1


# ---- load_releases ------------------------------------------------------


def test_both_pools_land_in_one_table_tagged_by_source(store):
    store.write("pool.json", {"pool": [{"album_id": "a1", "title": "Q"}]})
    store.write("pool_discogs.json", {"pool": [{"album_id": "d1", "title": "D"}]})
    load.load_releases(store.ld)
    assert set(store.rows("releases", "album_id, source")) == {("a1", "qobuz"),
                                                               ("d1", "discogs")}


def test_the_same_album_id_in_both_pools_is_two_rows_not_a_collision(store):
    """Both pools hold QOBUZ ids reached by different paths, so album_id alone
    is not unique -- which is why the table is keyed (album_id, source)."""
    store.write("pool.json", {"pool": [{"album_id": "same", "via": {"name": "via-q"}}]})
    store.write("pool_discogs.json", {"pool": [
        {"album_id": "same", "via": {"name": "via-d"}}]})
    load.load_releases(store.ld)
    assert store.count("releases") == 2
    assert set(store.rows("releases", "source, via_name")) == {("qobuz", "via-q"),
                                                               ("discogs", "via-d")}


def test_the_signal_is_flattened_into_sortable_columns(store):
    """A ranker orders on sig_score, so it cannot live inside a JSON blob."""
    store.write("pool.json", {"pool": [{"album_id": "a1", "via": {
        "name": "P", "qobuz_id": 5, "top_role": "Producer", "seed_albums": 3,
        "signal": {"score": 0.42, "role_weight": 1.0, "selectivity": 0.6,
                   "selectivity_band": "moderate", "person_seed_albums": 3,
                   "embedded": 0.3, "flags": ["single_token_name"]}}}]})
    load.load_releases(store.ld)
    assert store.one("SELECT sig_score, sig_selectivity_band, sig_flags FROM releases"
                     ) == (0.42, "moderate", "single_token_name")


def test_absent_hires_becomes_false_rather_than_null(store):
    """bool() is applied on the way in, so `hires IS NULL` is never the query
    anyone has to write -- at the cost of not distinguishing absent from false."""
    store.write("pool.json", {"pool": [{"album_id": "a1"}]})
    load.load_releases(store.ld)
    assert store.one("SELECT hires, streamable FROM releases") == (0, 0)


def test_the_credited_artists_are_their_own_table(store):
    store.write("pool.json", {"pool": [
        {"album_id": "a1", "artists": ["One", "Two"]}]})
    load.load_releases(store.ld)
    assert store.rows("release_artists", "album_id, source, name") == [
        ("a1", "qobuz", "One"), ("a1", "qobuz", "Two")]


def test_a_missing_pool_is_skipped(store):
    store.write("pool.json", {"pool": [{"album_id": "a1"}]})
    load.load_releases(store.ld)           # no pool_discogs.json at all
    assert store.count("releases") == 1


# ---- load_songs ---------------------------------------------------------


def test_the_artist_query_comes_from_the_file_not_the_filename(store):
    store.write("writing_jorge-drexler.json",
                {"artist": {"query": "Jorge Drexler"}, "songs": [{"song": "s1"}]})
    load.load_songs(store.ld)
    assert store.one("SELECT artist_query FROM songs") == ("Jorge Drexler",)


def test_the_filename_is_the_fallback_when_the_file_does_not_say(store):
    store.write("writing_someone.json", {"songs": [{"song": "s1"}]})
    load.load_songs(store.ld)
    assert store.one("SELECT artist_query FROM songs") == ("writing_someone",)


def test_a_songs_tier_and_its_votes_are_both_kept(store):
    """The tier is the verdict and the votes are the disagreement behind it;
    tier_disagreement is the flag that says to look at the votes."""
    store.write("writing_x.json", {"songs": [
        {"song": "s1", "title": "T", "tier": "lyrics_only",
         "tier_disagreement": True, "tier_votes": {"lyrics_only": 3, "authored": 1}}]})
    load.load_songs(store.ld)
    assert store.one("SELECT tier, tier_disagreement FROM songs") == ("lyrics_only", 1)
    assert set(store.rows("song_tier_votes", "tier, n")) == {("lyrics_only", 3),
                                                             ("authored", 1)}


def test_a_performer_with_no_albums_is_still_a_row(store):
    """`or [None]` -- the performer is the fact, the album is the detail. Losing
    them would undercount the covers of a song."""
    store.write("writing_x.json", {"songs": [
        {"song": "s1", "performers": [{"name": "Someone", "covers_mill": False}]}]})
    load.load_songs(store.ld)
    assert store.one("SELECT performer_name, performer_key, album_title, covers_mill "
                     "FROM song_performers") == ("Someone", "someone", None, 0)


def test_a_performer_on_three_albums_is_three_rows(store):
    store.write("writing_x.json", {"songs": [
        {"song": "s1", "performers": [
            {"name": "Someone", "albums": ["A", "B", "C"]}]}]})
    load.load_songs(store.ld)
    assert store.count("song_performers") == 3


def test_covers_mills_are_flagged_not_dropped(store):
    """A flag rather than a filter: 9 of the 19 performers of one song are
    these, so dropping them here would make the cover count unreconstructable."""
    store.write("writing_x.json", {"songs": [{"song": "s1", "performers": [
        {"name": "Real Artist", "covers_mill": False},
        {"name": "Karaoke Band", "covers_mill": True}]}]})
    load.load_songs(store.ld)
    assert store.count("song_performers") == 2
    assert store.one("SELECT performer_name FROM song_performers WHERE covers_mill"
                     ) == ("Karaoke Band",)


# ---- load_cache ---------------------------------------------------------


def test_the_search_cache_filename_is_parsed_back_into_store_and_query(store):
    """<store>_<query>_<offset>, with %20 decoded. The query is what joins a
    cached page back to the person it was fetched for."""
    store.cache("search", "gb-en_Jorge%20Drexler_200.json", {"items": [
        {"title": "Track", "performers": "", "album": {"id": "al1", "title": "Alb"},
         "performer": {"name": "Jorge Drexler"}}]})
    load.load_cache(store.ld)
    assert store.one("SELECT store, query, album_id, album_title FROM tracks"
                     ) == ("gb-en", "Jorge Drexler", "al1", "Alb")


def test_the_performers_string_is_expanded_into_one_row_per_person_and_role(store):
    """This is the table the rest of the repo does not have, and it goes through
    core.credits.parse_performers, so the co-artist rule applies here too."""
    store.cache("search", "gb-en_Q_0.json", {"items": [
        {"title": "T", "album": {"id": "al1"},
         "performers": "Jorge Drexler, MainArtist, Vocal - Ana Prada, Guitar"}]})
    load.load_cache(store.ld)
    assert set(store.rows("credits", "person_name, role, role_class")) == {
        ("Jorge Drexler", "MainArtist", "billing"),
        ("Jorge Drexler", "Vocal", "performance"),
        ("Ana Prada", "Guitar", "performance")}


def test_a_packed_co_artist_does_not_become_a_role_in_the_store(store):
    """The parse_performers heuristic, asserted through the loader: without it
    "Rueda de Candombe" lands in `credits.role` scoring INSTRUMENT_WEIGHT."""
    store.cache("search", "gb-en_Q_0.json", {"items": [
        {"title": "T", "album": {"id": "al1"},
         "performers": "Jorge Drexler, Rueda de Candombe, AssociatedPerformer"
                       " - Rueda de Candombe, MainArtist"}]})
    load.load_cache(store.ld)
    assert "Rueda de Candombe" not in {r[0] for r in store.rows("credits", "role")}


def test_the_credits_cache_is_a_list_of_tracks_and_carries_a_track_id(store):
    """The two cache dirs have different shapes -- search is {items: [...]} and
    credits is a bare list -- and only credits knows a track id."""
    store.cache("credits", "gb-en_album1.json",
                [{"id": 99, "title": "T", "performers": "P, Producer"}])
    load.load_cache(store.ld)
    assert store.one("SELECT source, store, album_id, track_id, role FROM credits"
                     ) == ("credits", "gb-en", "album1", 99, "Producer")


def test_a_search_credit_has_no_track_id_and_says_so(store):
    """8,806 of the 11,926 credit rows in the real build. NULL rather than 0,
    because track/search does not return one."""
    store.cache("search", "gb-en_Q_0.json", {"items": [
        {"title": "T", "album": {"id": "al1"}, "performers": "P, Producer"}]})
    load.load_cache(store.ld)
    assert store.one("SELECT track_id FROM credits") == (None,)


def test_an_empty_cache_is_not_an_error(store):
    load.load_cache(store.ld)
    assert store.count("tracks") == 0 and store.count("credits") == 0


# ---- load_listens -------------------------------------------------------


def listens_zip(path, entries):
    """A ListenBrainz export: listens/<year>/<month>.jsonl inside a zip."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, lines in entries.items():
            zf.writestr(name, "\n".join(json.dumps(x) if not isinstance(x, str) else x
                                        for x in lines))
    return path


def listen(ts=1700000000, track="Track", artist="Jorge Drexler", **extra):
    md = {"track_name": track, "artist_name": artist,
          "release_name": extra.pop("release", "Album"),
          "mbid_mapping": extra.pop("mapping", {})}
    return {"listened_at": ts, "track_metadata": md, **extra}


def test_a_listen_is_loaded_with_its_date_and_year_materialised(store):
    """`year` comes from the PATH and `listened_date` from the timestamp. Both
    are materialised rather than computed per query, because the honest
    evaluation is a time split and that is a windowed join."""
    z = listens_zip(store.tmp / "lb.zip", {"listens/2023/11.jsonl": [listen()]})
    load.load_listens(store.ld, z)
    assert store.one("SELECT year, listened_date, artist_key FROM listens"
                     ) == (2023, "2023-11-14", "jorge drexler")


def test_the_musicbrainz_ids_are_lifted_out_of_the_mapping(store):
    """The only MusicBrainz identifiers anywhere in the project, and the half of
    a crosswalk whose other half is the ISRC the cache does not keep."""
    z = listens_zip(store.tmp / "lb.zip", {"listens/2023/1.jsonl": [listen(
        mapping={"recording_mbid": "rec-1", "artist_mbids": ["art-1", "art-2"],
                 "release_mbid": "rel-1"})]})
    load.load_listens(store.ld, z)
    assert store.one("SELECT recording_mbid, artist_mbid, release_mbid FROM listens"
                     ) == ("rec-1", "art-1", "rel-1")


def test_only_the_first_artist_mbid_is_kept(store):
    """A column, not a junction: the export gives a list and the store takes
    one. Worth knowing before anybody joins on it."""
    z = listens_zip(store.tmp / "lb.zip", {"listens/2023/1.jsonl": [
        listen(mapping={"artist_mbids": []})]})
    load.load_listens(store.ld, z)
    assert store.one("SELECT artist_mbid FROM listens") == (None,)


def test_everything_outside_the_listens_directory_is_ignored(store):
    """Exports carry other files, and a stray .json at the root would otherwise
    be parsed as a listen."""
    z = listens_zip(store.tmp / "lb.zip", {
        "listens/2023/1.jsonl": [listen()],
        "user.json": ['{"name": "someone"}'],
        "listens/2023/notes.txt": ["not jsonl"]})
    load.load_listens(store.ld, z)
    assert store.count("listens") == 1


def test_a_corrupt_line_is_skipped_and_the_rest_of_the_file_loads(store):
    """190k lines out of a zip: one bad line must not cost the other 189,999."""
    z = listens_zip(store.tmp / "lb.zip", {"listens/2023/1.jsonl": [
        listen(ts=1700000000), "{truncated", "", listen(ts=1700000001)]})
    load.load_listens(store.ld, z)
    assert store.count("listens") == 2


def test_a_listen_with_no_timestamp_gets_no_date(store):
    z = listens_zip(store.tmp / "lb.zip", {"listens/2023/1.jsonl": [
        {"track_metadata": {"track_name": "T", "artist_name": "A"}}]})
    load.load_listens(store.ld, z)
    assert store.one("SELECT listened_at, listened_date, year FROM listens"
                     ) == (None, None, 2023)


# ---- main and summarise -------------------------------------------------


def test_summarise_of_a_db_nobody_built_says_so(store, capsys):
    assert load.summarise(store.con, "sqlite") == 1
    assert "meta is empty" in capsys.readouterr().out


def test_summarise_prints_a_row_per_loaded_table(store, capsys):
    store.ld.note("people", "discovery_1.json", 5, "2026-09-01")
    store.ld.insert("meta", ["table_name", "source", "rows", "generated", "loaded_at"],
                    store.ld.meta)
    assert load.summarise(store.con, "sqlite") == 0
    out = capsys.readouterr().out
    assert "people" in out and "discovery_1.json" in out and "5" in out


def test_a_full_build_from_nothing_produces_an_empty_but_valid_store(store, monkeypatch):
    """main() end to end with no inputs at all: the tables, the 45 indexes and
    the views all exist, and nothing raised. This is the contract -- the build
    runs over whatever happens to be on disk."""
    db = store.tmp / "out.db"
    monkeypatch.setattr(load, "LISTENS_GLOB", str(store.tmp / "no_such_*.zip"))
    monkeypatch.setattr("sys.argv", ["load.py", "--db", str(db)])
    assert load.main() == 0

    con = sqlite3.connect(db)
    kinds = con.execute("SELECT type, COUNT(*) FROM sqlite_master GROUP BY type"
                        ).fetchall()
    assert dict(kinds)["index"] == 45
    assert dict(kinds)["view"] == 4


def test_a_build_rewrites_rather_than_appends_to_an_existing_file(store, monkeypatch):
    """The DB is derived and disposable: always rebuilt, never migrated. A
    second run must not double every row."""
    db = store.tmp / "out.db"
    store.write("pool.json", {"pool": [{"album_id": "a1"}]})
    monkeypatch.setattr(load, "LISTENS_GLOB", str(store.tmp / "none_*.zip"))
    monkeypatch.setattr("sys.argv", ["load.py", "--db", str(db)])
    assert load.main() == 0
    assert load.main() == 0
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM releases").fetchone() == (1,)


def test_summary_mode_on_a_db_that_does_not_exist_tells_you_to_build_one(store,
                                                                         monkeypatch):
    monkeypatch.setattr("sys.argv",
                        ["load.py", "--db", str(store.tmp / "nope.db"), "--summary"])
    with pytest.raises(SystemExit, match="not found"):
        load.main()


def test_the_listens_export_is_found_by_glob_and_loaded(store, monkeypatch):
    """Found, not required: the export lives outside the repo."""
    listens_zip(store.tmp / "listenbrainz_2026.zip",
                {"listens/2024/1.jsonl": [listen()]})
    db = store.tmp / "out.db"
    monkeypatch.setattr(load, "LISTENS_GLOB", str(store.tmp / "listenbrainz_*.zip"))
    monkeypatch.setattr("sys.argv", ["load.py", "--db", str(db)])
    assert load.main() == 0
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM listens").fetchone() == (1,)


def test_no_listens_skips_the_only_slow_part(store, monkeypatch):
    listens_zip(store.tmp / "listenbrainz_2026.zip",
                {"listens/2024/1.jsonl": [listen()]})
    db = store.tmp / "out.db"
    monkeypatch.setattr(load, "LISTENS_GLOB", str(store.tmp / "listenbrainz_*.zip"))
    monkeypatch.setattr("sys.argv", ["load.py", "--db", str(db), "--no-listens"])
    assert load.main() == 0
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM listens").fetchone() == (0,)


# ---- the remaining branches ---------------------------------------------
#
# What is left uncovered after these is the duckdb path in connect(), which is
# two lines of delegation behind an optional dependency, and the notice printed
# alongside it. Both need duckdb installed to reach and neither decides the
# shape of anything.


def test_the_people_discogs_cannot_resolve_either_are_still_recorded(store):
    """The end of the line for a name: Qobuz could not see them and neither
    could Discogs. Recorded with the reason rather than dropped, because the
    alternative is a name that silently stops existing after two stages."""
    store.write("discogs_watchlist.json", {"still_unresolved": [
        {"names": ["Ghost", "Ghost Variant"], "reason": "not_found",
         "discogs_id": 7}]})
    load.load_people(store.ld)
    assert store.one("SELECT name, unresolved_reason, discogs_id FROM people"
                     ) == ("Ghost", "not_found", 7)
    assert store.count("person_names") == 2
    assert store.one("SELECT source FROM person_sources"
                     ) == ("discogs_watchlist.json:still_unresolved",)


def test_a_malformed_pool_is_skipped_and_the_other_one_still_loads(store, capsys):
    (store.data / "pool.json").write_text("{truncated")
    store.write("pool_discogs.json", {"pool": [{"album_id": "d1"}]})
    load.load_releases(store.ld)
    assert store.rows("releases", "album_id, source") == [("d1", "discogs")]
    assert "skipping pool.json" in capsys.readouterr().err


def test_a_malformed_writing_file_is_skipped(store, capsys):
    (store.data / "writing_bad.json").write_text("{truncated")
    store.write("writing_ok.json", {"songs": [{"song": "s1"}]})
    load.load_songs(store.ld)
    assert store.count("songs") == 1
    assert "skipping writing_bad.json" in capsys.readouterr().err


def test_a_malformed_cache_entry_is_skipped_in_both_directories(store, capsys):
    """cache/ is the corpus and the one thing never regenerated, so a truncated
    write there must cost that file and nothing else."""
    (store.tmp / "cache" / "search").mkdir(parents=True)
    (store.tmp / "cache" / "credits").mkdir(parents=True)
    (store.tmp / "cache" / "search" / "gb-en_Bad_0.json").write_text("{truncated")
    (store.tmp / "cache" / "credits" / "gb-en_bad.json").write_text("[truncated")
    store.cache("search", "gb-en_Good_0.json", {"items": [
        {"title": "T", "album": {"id": "al1"}, "performers": "P, Producer"}]})
    store.cache("credits", "gb-en_good.json",
                [{"id": 1, "title": "T", "performers": "Q, Bass"}])
    load.load_cache(store.ld)

    assert store.count("tracks") == 1
    assert set(store.rows("credits", "person_name")) == {("P",), ("Q",)}
    err = capsys.readouterr().err
    assert "skipping gb-en_Bad_0.json" in err and "skipping gb-en_bad.json" in err


def test_summary_mode_reads_an_existing_db_without_rebuilding_it(store, monkeypatch):
    """--summary must not touch the file: it is the one mode that runs against
    a build somebody is still using."""
    db = store.tmp / "out.db"
    store.write("pool.json", {"pool": [{"album_id": "a1"}]})
    monkeypatch.setattr(load, "LISTENS_GLOB", str(store.tmp / "none_*.zip"))
    monkeypatch.setattr("sys.argv", ["load.py", "--db", str(db)])
    assert load.main() == 0
    before = db.stat().st_mtime_ns

    monkeypatch.setattr("sys.argv", ["load.py", "--db", str(db), "--summary"])
    assert load.main() == 0
    assert db.stat().st_mtime_ns == before
