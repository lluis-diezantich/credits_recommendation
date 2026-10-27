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
    assert load.INDEXES.count("CREATE INDEX") == 36


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


def test_the_name_mints_the_key_and_a_stored_one_does_not_win(store):
    """Reversed deliberately. A discovery file's `key` was minted by whichever
    normalise() was current when discover.py wrote it, while `credits` mints
    fresh on every load -- so trusting the stored one made the two disagree
    for every name holding a quote and split the person in half. D25 is the
    general case, and the quote change is what made it bite.
    """
    store.write("discovery_1.json", {"people": [
        {"key": "stale key", "names": ["Mark \u201cSpike\u201d Stent"]}]})
    load.load_people(store.ld)
    assert store.one("SELECT person_key FROM people") == ("mark spike stent",)


def test_both_quote_spellings_of_one_person_load_as_one_row(store):
    """The defect this fixes: the corpus holds the same person with a straight
    apostrophe and a typographic one, and they keyed differently."""
    store.write("discovery_1.json", {"people": [
        {"names": ["Oscar D\u2019Le\u00f3n"], "stats": {"albums": 2}}]})
    store.write("discovery_2.json", {"people": [
        {"names": ["Oscar D'Le\u00f3n"], "stats": {"albums": 3}}]})
    load.load_people(store.ld)
    assert store.count("people") == 1
    assert store.one("SELECT person_key FROM people") == ("oscar dleon",)


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


def test_ubiquity_rows_carry_the_match_kind(store):
    """`match` is in the table because only 'exact' is trusted: a query that
    read total_releases alone would believe 1 release for Travis Scott."""
    store.write("ubiquity.json", {"generated": "2026-10-24", "people": [
        {"person_key": "snoop dogg", "name": "Snoop Dogg", "discogs_id": 1,
         "discogs_name": "Snoop Dogg", "match": "exact", "total_releases": 9796},
        {"person_key": "travis scott", "name": "Travis Scott", "discogs_id": 2,
         "discogs_name": "Travis Scott", "match": "ambiguous",
         "total_releases": 1}]})
    load.load_ubiquity(store.ld)

    assert store.count("ubiquity") == 2
    rows = dict(store.con.execute(
        "SELECT person_key, match FROM ubiquity").fetchall())
    assert rows == {"snoop dogg": "exact", "travis scott": "ambiguous"}


def test_a_store_with_no_ubiquity_file_still_builds(store):
    """The file costs 1,160 Discogs requests at 25/min, so a fresh clone must
    not need it. Every reader goes through policy.ubiquity_factor(), which is
    neutral on a missing count."""
    load.load_ubiquity(store.ld)
    assert store.count("ubiquity") == 0


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


# ---- dedup, now symmetric across all six junction tables ----------------
#
# Every junction table is assembled by appending from several files, so a person
# in both discovery_*.json and watchlist.json contributes the same album twice.
# Three of the six inserts deduplicated and three did not, which cost 777
# person_albums rows for 563 distinct triples. All six now go through
# deduped(), and these are the regression tests -- including for the three that
# were already right, since the fix moved those onto the shared helper too.


def test_a_name_from_two_files_is_stored_once(store):
    store.write("discovery_1.json", {"people": [{"names": ["Dup"]}]})
    store.write("discovery_2.json", {"people": [{"names": ["Dup"]}]})
    load.load_people(store.ld)
    assert store.count("person_names") == 1


def test_a_class_from_two_files_is_stored_once(store):
    store.write("discovery_1.json", {"people": [
        {"names": ["Dup"], "classes": ["production"]}]})
    store.write("discovery_2.json", {"people": [
        {"names": ["Dup"], "classes": ["production"]}]})
    load.load_people(store.ld)
    assert store.count("person_classes") == 1


def test_a_role_from_two_files_is_stored_once(store):
    store.write("discovery_1.json", {"people": [
        {"names": ["Dup"], "roles": {"Producer": 2}}]})
    store.write("discovery_2.json", {"people": [
        {"names": ["Dup"], "roles": {"Producer": 2}}]})
    load.load_people(store.ld)
    assert store.count("person_roles") == 1


def test_the_same_album_from_two_files_is_stored_once(store):
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
    """main() end to end with no inputs at all: the tables, the 56 indexes and
    the views all exist, and nothing raised. This is the contract -- the build
    runs over whatever happens to be on disk.

    56, not 36: 20 of the primary keys are themselves unique indexes. 21
    tables carry a key, but `seeds` keys on INTEGER PRIMARY KEY, which aliases
    the rowid and creates no index at all. Counted, not quoted -- the numbers
    moved when `ubiquity` and `artist_genres` landed, and a stale one here
    reads as a regression."""
    db = store.tmp / "out.db"
    monkeypatch.setattr(load, "LISTENS_GLOB", str(store.tmp / "no_such_*.zip"))
    monkeypatch.setattr("sys.argv", ["load.py", "--db", str(db)])
    assert load.main() == 0

    con = sqlite3.connect(db)
    kinds = con.execute("SELECT type, COUNT(*) FROM sqlite_master GROUP BY type"
                        ).fetchall()
    assert dict(kinds)["index"] == 56
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


def test_an_edge_from_two_files_is_stored_once(store):
    """The third table that was missing its dedup. A person recovered twice
    brought their whole worked_with list along twice with them."""
    edge = {"name": "Other", "releases": 4, "roles": ["Bass"]}
    store.write("discogs_watchlist.json", {"recovered": [
        {"names": ["Dup"], "worked_with": [edge, edge]}]})
    load.load_people(store.ld)
    assert store.count("person_edges") == 1


def test_deduping_keeps_rows_that_only_look_alike(store):
    """Distinct on the WHOLE tuple, not on a prefix of it. Stated on
    person_roles because that is where it is load-bearing: the same person and
    role arrives with a count from one file and without one from another, and
    those are two rows -- which is also why that table has no primary key."""
    store.write("discovery_1.json", {"people": [
        {"names": ["P"], "roles": {"Producer": 3}}]})
    store.write("watchlist.json", {"artists": [
        {"name": "P", "roles": ["Producer"]}]})
    load.load_people(store.ld)
    assert set(store.rows("person_roles", "n")) == {(3,), (None,)}


def test_dedup_survives_the_nulls_that_make_sorting_impossible(store):
    """Why deduped() uses dict.fromkeys. These rows mix None with int and str in
    one column, and sorted(set(...)) -- the fix that looks right -- raises
    TypeError on them instead of deduplicating anything:

        person_roles.n   None for watchlist.json's bare-list role form, an int
                         for the {role: count} form every other file uses
        person_albums    date/tracks/roles absent on some rows and present on
                         others, for the same person and the same album
    """
    album = {"album_id": "a1", "title": "T", "date": "2020-01-01", "tracks": 10,
             "roles": ["Producer"]}
    store.write("discovery_1.json", {"people": [
        {"names": ["P"], "roles": {"Producer": 3}, "albums": [album]}]})
    store.write("watchlist.json", {"artists": [
        {"name": "P", "roles": ["Producer"], "appearances": [album]}]})
    load.load_people(store.ld)                   # must not raise

    # set(), not sorted() -- sorting these is the very thing that raises
    assert set(store.rows("person_roles", "n")) == {(None,), (3,)}
    assert store.count("person_albums") == 1     # identical tuples, collapsed


def test_deduped_is_order_preserving_so_a_rebuild_is_reproducible(store):
    """A bare set() would order rows by Python's per-process string hash seed,
    so two builds of the same inputs would differ. dict.fromkeys does not."""
    assert load.deduped([("b", 2), ("a", 1), ("b", 2), ("c", 3), ("a", 1)]) == [
        ("b", 2), ("a", 1), ("c", 3)]
    assert load.deduped([]) == []


# ---- primary keys -------------------------------------------------------
#
# They could not go on until the loader stopped inserting duplicate rows. Now
# that it has, 16 of the 21 tables carry one, and the five without are each
# without for a stated reason rather than by omission.


def test_the_tables_whose_key_is_real_have_one(store):
    """A key is the only thing that makes the store self-checking: without one,
    a loader that starts duplicating rows again is invisible until somebody
    notices a count is too high."""
    keyed = {}
    for (name,) in store.con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"):
        cols = [r[1] for r in store.con.execute(f"PRAGMA table_info({name})") if r[5]]
        if cols:
            keyed[name] = cols

    assert keyed["people"] == ["person_key"]
    assert keyed["person_names"] == ["person_key", "name"]
    assert keyed["person_albums"] == ["seed_qobuz_id", "person_key", "album_id"]
    assert keyed["person_edges"] == ["person_key", "other_name", "kind"]
    assert keyed["releases"] == ["album_id", "source"]
    assert keyed["songs"] == ["song_key", "artist_query"]
    # (person, seed) -- the grain albums and tracks are measured at, and the
    # key that stops one seed's numbers overwriting another's.
    assert keyed["person_seeds"] == ["person_key", "seed_qobuz_id"]
    # Everything per-seed is keyed by the seed, so a second seed adds rows
    # instead of overwriting the first -- the lesson of person_seeds.
    assert keyed["seeds"] == ["seed_qobuz_id"]
    assert keyed["co_artists"] == ["seed_qobuz_id", "person_key"]
    assert keyed["co_artist_albums"] == ["seed_qobuz_id", "person_key", "album_id"]
    # One row per person, not per (person, seed): how prolific somebody is on
    # Discogs is a fact about them and does not vary by which seed found them.
    assert keyed["ubiquity"] == ["person_key"]
    # Keyed on (mbid, genre): MusicBrainz returns a genre once per artist, and
    # a duplicate would mean the cache file was written twice.
    assert keyed["artist_genres"] == ["mbid", "genre"]
    assert len(keyed) == 21


def test_the_five_without_a_key_are_the_five_with_a_reason(store):
    """person_roles needs a merge decision (a count against a NULL), tracks and
    credits are still duplicated inside the cache, song_performers has a
    nullable column in its only candidate key, and meta/listens have no natural
    key at all. If one of these grows a key, this test is where it is argued."""
    unkeyed = {name for (name,) in store.con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")
        if not any(r[5] for r in store.con.execute(f"PRAGMA table_info({name})"))}
    assert unkeyed == {"person_roles", "song_performers", "tracks", "credits",
                       "listens", "meta"}


def test_releases_is_keyed_on_album_and_source_because_the_ids_collide(store):
    """The key states the thing the docstring explains: both pools hold Qobuz
    ids reached by different paths, so album_id alone is not an identity."""
    store.write("pool.json", {"pool": [{"album_id": "same"}]})
    store.write("pool_discogs.json", {"pool": [{"album_id": "same"}]})
    load.load_releases(store.ld)                 # must not raise
    assert store.count("releases") == 2


def test_a_duplicate_row_now_fails_the_build_instead_of_being_written(store):
    """The whole point. Previously this wrote two rows and nothing said so."""
    with pytest.raises(SystemExit) as caught:
        store.ld.insert("person_names", ["person_key", "name"],
                        [("p", "Dup"), ("p", "Dup")])
    assert "UNIQUE constraint failed" in str(caught.value)


def test_the_failure_names_the_table_and_the_offending_row(store):
    """sqlite says "UNIQUE constraint failed: person_albums.person_key,
    person_albums.album_id" and names no row. Over a 216k-row build that is not
    a place to go looking, so insert() finds the duplicate and prints it."""
    row = (41620, "jorge drexler", "a1", "Title", "2020-01-01", 10, "Producer")
    with pytest.raises(SystemExit) as caught:
        store.ld.insert("person_albums",
                        ["seed_qobuz_id", "person_key", "album_id", "title",
                         "date", "tracks", "roles"],
                        [row, row])
    message = str(caught.value)
    assert "person_albums" in message
    assert "'person_key': 'jorge drexler'" in message
    assert "'album_id': 'a1'" in message
    assert "deduped()" in message                # where to go and fix it


def test_a_violation_is_raised_rather_than_skipped(store):
    """Never swallowed: it means the loader produced data its own schema says
    is impossible, and a store that is wrong in a way no query reveals is worse
    than no store."""
    with pytest.raises(SystemExit):
        store.ld.insert("songs",
                        ["song_key", "artist_query", "title"],
                        [("s1", "q", "A"), ("s1", "q", "B")])


def test_a_clean_insert_is_unaffected_by_the_guard(store):
    store.ld.insert("person_names", ["person_key", "name"],
                    [("p", "One"), ("p", "Two"), ("q", "One")])
    assert store.count("person_names") == 3


def test_the_first_duplicate_helper_reports_nothing_when_there_is_nothing(store):
    assert load.Loader._first_duplicate("t", ["a"], [("x",), ("y",)]) is None
    assert load.Loader._first_duplicate("t", ["a", "b"], [("x", 1), ("x", 1)]) == {
        "a": "x", "b": 1}


def test_no_index_duplicates_a_primary_key(store):
    """A PK is itself a unique index, so an index on its leftmost prefix is
    maintained for nothing. Fifteen were dropped when the keys went on; this is
    what notices if one comes back."""
    for statement in load.INDEXES.strip().split(";"):
        if statement.strip():
            store.con.execute(statement)
    for (table,) in store.con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"):
        pk = [r[1] for r in store.con.execute(f"PRAGMA table_info({table})") if r[5]]
        if not pk:
            continue
        for (idx,) in store.con.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=? "
                "AND name LIKE 'ix_%'", (table,)):
            cols = [r[2] for r in store.con.execute(f"PRAGMA index_info({idx})")]
            assert cols != pk[:len(cols)], f"{idx} duplicates the key of {table}"


def test_a_full_build_still_satisfies_every_key_it_declares(store, monkeypatch):
    """End to end over inputs that overlap the way the real files do: one person
    in three files, one album reached twice, one release in both pools."""
    album = {"album_id": "a1", "title": "T", "date": "2020-01-01", "tracks": 9,
             "roles": ["Producer"]}
    store.write("discovery_1.json", {"people": [
        {"names": ["P"], "classes": ["production"], "roles": {"Producer": 2},
         "albums": [album]}]})
    store.write("discovery_2.json", {"people": [
        {"names": ["P"], "classes": ["production"], "roles": {"Producer": 2},
         "albums": [album]}]})
    store.write("watchlist.json", {"artists": [
        {"name": "P", "name_variants": ["P"], "appearances": [album]}]})
    store.write("pool.json", {"pool": [{"album_id": "x1", "artists": ["A"]}]})
    store.write("pool_discogs.json", {"pool": [{"album_id": "x1", "artists": ["A"]}]})

    db = store.tmp / "out.db"
    monkeypatch.setattr(load, "LISTENS_GLOB", str(store.tmp / "none_*.zip"))
    monkeypatch.setattr("sys.argv", ["load.py", "--db", str(db)])
    assert load.main() == 0

    con = sqlite3.connect(db)
    assert con.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert con.execute("SELECT COUNT(*) FROM person_albums").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM releases").fetchone() == (2,)


def test_two_seeds_may_disagree_about_one_album_because_they_are_not_wrong(store):
    """This used to fail the build, and the key was wrong rather than the data.

    `provenance` is a fact about (album, SEED): "Oral (Olof Dreijer Remix)" is
    Bjork's OWN record and a guest spot for ROSALIA, and Noah Goldstein and
    Sega Bodega are credited on it in both walks. Keyed (person_key, album_id)
    those two rows collided, and the sixth seed is where that finally happened.
    D28 put the seed in the key, which is D19's grain argument reaching the one
    table it had missed.
    """
    store.write("discovery_1.json", {
        "seed": {"qobuz_id": 27940, "name": "Björk"},
        "people": [{"names": ["P"], "albums": [
            {"album_id": "a1", "title": "Oral", "provenance": "own"}]}]})
    store.write("discovery_2.json", {
        "seed": {"qobuz_id": 219860, "name": "ROSALÍA"},
        "people": [{"names": ["P"], "albums": [
            {"album_id": "a1", "title": "Oral", "provenance": "guest"}]}]})

    load.load_people(store.ld)
    assert dict(store.rows("person_albums", "seed_qobuz_id, provenance")) == {
        27940: "own", 219860: "guest"}


def test_one_seed_claiming_an_album_twice_still_fails_the_build_loudly(store):
    """What the key protects now. A seed's own walk writing the same (person,
    album) twice means the loader produced data its schema forbids, and loud is
    the right failure -- the alternative is a count that double-counts an album
    where no query would reveal it."""
    row = (41620, "p", "a1", "own", "Libertad", "2020-01-01", 13, "Producer")
    with pytest.raises(SystemExit) as caught:
        store.ld.insert("person_albums",
                        ["seed_qobuz_id", "person_key", "album_id", "provenance",
                         "title", "date", "tracks", "roles"],
                        [row, (*row[:6], 15, "Producer")])
    assert "person_albums" in str(caught.value)
    assert "UNIQUE constraint failed" in str(caught.value)


def test_the_derived_watchlist_is_not_a_second_source_for_an_album(store):
    """watchlist.json's `appearances` is a copy of the discovery pass it was
    resolved from -- 191 rows on the real corpus, all 191 already present and
    none unique -- so it contributes no album row.

    It used to, harmlessly, while the two files agreed. They stopped agreeing
    when the alias map changed a merged person's counts and this derived file
    still held the pre-merge ones, which turned a redundant row into a failed
    build. One fact, one source (D25)."""
    store.write("watchlist.json", {"artists": [{"name": "P", "appearances": [
        {"album_id": "a1", "title": "Libertad", "tracks": 13}]}]})
    load.load_people(store.ld)
    assert store.count("person_albums") == 0
    # The person still arrives -- only the album row is dropped.
    assert store.rows("people", "name")[0] == ("P",)


# ---- the shortlist columns ----------------------------------------------


def test_the_referring_person_being_first_billed_is_stored_as_a_fact(store):
    """policy.shortlisted needs it and SQL cannot derive it: the comparison is
    against normalise(), which sqlite does not have. 5,862 of the 7,860 pooled
    rows are the referring person's own record."""
    store.write("pool.json", {"pool": [
        {"album_id": "a1", "title": "Their own", "artists": ["Borja Barrueta"],
         "via": {"name": "Borja Barrueta", "top_role": "Drums", "signal": {}}},
        {"album_id": "a2", "title": "Somebody else's",
         "artists": ["Juanfe Pérez", "Borja Barrueta"],
         "via": {"name": "Borja Barrueta", "top_role": "Drums", "signal": {}}}]})
    load.load_releases(store.ld)
    assert dict(store.rows("releases", "album_id, via_is_first_artist")) == {
        "a1": 1, "a2": 0}


def test_the_first_artist_test_sees_through_an_accent(store):
    """Keyed on normalise(), like release_artists.name_key -- lower(name) calls
    every accented artist a different person."""
    store.write("pool.json", {"pool": [
        {"album_id": "a1", "title": "x", "artists": ["Anavitória"],
         "via": {"name": "Anavitoria", "top_role": "Vocals", "signal": {}}}]})
    load.load_releases(store.ld)
    assert store.rows("releases", "via_is_first_artist")[0][0] == 1


def test_the_referral_classes_come_from_whichever_role_the_source_recorded(store):
    """The Discogs path records which credit referred, the Qobuz path only the
    person's top role. Both answer "what was this reached through"."""
    store.write("pool.json", {"pool": [
        {"album_id": "a1", "title": "x", "artists": ["Someone"],
         "via": {"name": "Borja Barrueta", "top_role": "Drums", "signal": {}}}]})
    store.write("pool_discogs.json", {"pool": [
        {"album_id": "a2", "title": "y", "artists": ["Someone"],
         "via": {"name": "Morgan", "top_role": "Producer",
                 "through_roles": ["Mixed by", "Producer"], "signal": {}}}]})
    load.load_releases(store.ld)
    assert dict(store.rows("releases", "album_id, via_referral_classes")) == {
        "a1": "performance", "a2": "engineering | production"}


def test_a_row_with_no_referring_role_gets_no_classes(store):
    """joined() returns NULL for an empty list, so the filter in docs/store.md
    excludes it rather than matching an empty string."""
    store.write("pool.json", {"pool": [
        {"album_id": "a1", "title": "x", "artists": ["Someone"],
         "via": {"name": "Nobody", "signal": {}}}]})
    load.load_releases(store.ld)
    assert store.rows("releases", "via_referral_classes")[0][0] is None


def test_the_through_roles_reach_the_store_at_all(store):
    """They were in pool_discogs.json and in no column, so "which credit
    referred this" was unanswerable from the store."""
    store.write("pool_discogs.json", {"pool": [
        {"album_id": "a1", "title": "x", "artists": ["Someone"],
         "via": {"name": "Morgan", "through": ["Carles Campi Campón"],
                 "through_roles": ["Producer"], "signal": {}}}]})
    load.load_releases(store.ld)
    assert store.rows("releases", "via_through, via_through_roles")[0] == (
        "Carles Campi Campón", "Producer")


def test_the_stored_score_is_not_penalised_twice(store):
    """sig_score arrives already multiplied by sig_match_confidence, and the
    column exists so a reader can undo it rather than repeat it. The old
    docs/store.md query multiplied by 0.1 itself, which after this change
    would have squared the penalty."""
    store.write("pool_discogs.json", {"pool": [
        {"album_id": "a1", "title": "x", "artists": ["Someone"],
         "via": {"name": "Morgan", "signal": {
             "score": 0.1, "match_confidence": 0.1,
             "flags": ["single_token_name"]}}}]})
    load.load_releases(store.ld)
    score, confidence = store.rows("releases", "sig_score, sig_match_confidence")[0]
    assert (score, confidence) == (0.1, 0.1)
    assert score / confidence == 1.0        # the raw referrer score, recovered


def test_both_catalogue_sizes_reach_the_store(store):
    """Fetched and dropped until now, and the only corroboration the Discogs
    path has: a session player matched to an artist holding 400 albums."""
    store.write("pool_discogs.json", {"pool": [
        {"album_id": "a1", "title": "x", "artists": ["Someone"],
         "via": {"name": "Morgan", "albums_count": 412, "discogs_releases": 3,
                 "signal": {}}}]})
    load.load_releases(store.ld)
    assert store.rows("releases", "via_albums_count, via_discogs_releases")[0] == (412, 3)


def test_a_pool_written_before_these_fields_still_loads(store):
    """The pools are regenerated by a run, so the store has to read both
    shapes until that run happens."""
    store.write("pool.json", {"pool": [
        {"album_id": "a1", "title": "x", "artists": ["Someone"],
         "via": {"name": "Borja Barrueta", "top_role": "Drums",
                 "signal": {"score": 0.8, "flags": []}}}]})
    load.load_releases(store.ld)
    assert store.rows(
        "releases", "sig_score, sig_match_confidence, via_albums_count")[0] == (
        0.8, None, None)


def test_the_seed_album_count_lands_in_one_column_from_either_path(store):
    """The pools name it differently -- `person_seed_albums` on the Discogs
    path, `seed_albums` on the Qobuz one -- and before this half the column
    read NULL with nothing saying why."""
    store.write("pool.json", {"pool": [
        {"album_id": "a1", "title": "x", "artists": ["Someone"],
         "via": {"name": "Juan Campodónico", "signal": {
             "seed_albums": 6, "own_albums": 6, "embedded": 0.6}}}]})
    store.write("pool_discogs.json", {"pool": [
        {"album_id": "a2", "title": "y", "artists": ["Someone"],
         "via": {"name": "Morgan", "signal": {
             "person_seed_albums": 21, "embedded": 1.0}}}]})
    load.load_releases(store.ld)
    assert dict(store.rows("releases", "album_id, sig_person_seed_albums")) == {
        "a1": 6, "a2": 21}


def test_a_referrer_who_only_guested_is_visible_as_zero_own_albums(store):
    """5 of 50 referrers in the Drexler pool are like this: they never worked
    on one of his records, they were on records he guested on. They scored
    non-zero until the embedding was computed from own_albums."""
    store.write("pool.json", {"pool": [
        {"album_id": "a1", "title": "x", "artists": ["Someone"],
         "via": {"name": "Çantamarta", "signal": {
             "seed_albums": 2, "own_albums": 0, "embedded": 0.0, "score": 0.0}}}]})
    load.load_releases(store.ld)
    assert store.rows("releases", "sig_own_albums, sig_embedded, sig_score")[0] == (
        0, 0.0, 0.0)


# ---- one person, several seeds -------------------------------------------


def two_seeds(store):
    """The same person on 13 of one seed's albums and 1 of another's, which is
    Fred Kevorkian exactly: he masters for both."""
    for seed_id, seed, albums, tracks in ((41620, "Jorge Drexler", 13, 42),
                                          (656411, "Sílvia Pérez Cruz", 1, 1)):
        store.write(f"discovery_{seed_id}.json", {
            "seed": {"qobuz_id": seed_id, "name": seed},
            "people": [{"key": "fred kevorkian", "names": ["Fred Kevorkian"],
                        "classes": ["production"], "roles": {"Mastering Engineer": tracks},
                        "albums": [], "stats": {
                            "albums": albums, "own_albums": albums, "tracks": tracks,
                            "top_role": "Mastering Engineer",
                            "first": "2017-07-07" if seed_id == 41620 else "2026-03-13",
                            "last": "2026-03-13" if seed_id == 41620 else "2026-03-13"}}]})


def test_a_second_seed_no_longer_overwrites_the_first(store):
    """The defect: load_people updated the same `people` row per discovery
    file, so the last one won and 13 Drexler albums silently became the 1 from
    a Pérez Cruz record. 14 people are in both files."""
    two_seeds(store)
    load.load_people(store.ld)
    assert store.rows("people", "albums, own_albums, tracks, seeds")[0] == (14, 14, 43, 2)


def test_the_per_seed_numbers_are_both_kept(store):
    """Summing answers "how much work in total" and loses "how embedded in
    THIS seed's catalogue", which is what the scoring means. Both now exist."""
    two_seeds(store)
    load.load_people(store.ld)
    assert dict(store.rows("person_seeds", "seed_name, albums")) == {
        "Jorge Drexler": 13, "Sílvia Pérez Cruz": 1}


def test_the_dates_span_every_seed(store):
    two_seeds(store)
    load.load_people(store.ld)
    assert store.rows("people", "first_seen, last_seen")[0] == ("2017-07-07", "2026-03-13")


def test_the_top_role_comes_from_the_seed_they_did_most_on(store):
    """Not from whichever file sorted last: what someone mainly is should come
    from where they did the most work."""
    store.write("discovery_1.json", {
        "seed": {"qobuz_id": 1, "name": "A"},
        "people": [{"key": "p", "names": ["P"], "stats": {
            "albums": 10, "tracks": 10, "top_role": "Producer"}}]})
    store.write("discovery_2.json", {
        "seed": {"qobuz_id": 2, "name": "B"},
        "people": [{"key": "p", "names": ["P"], "stats": {
            "albums": 1, "tracks": 1, "top_role": "Guitar"}}]})
    load.load_people(store.ld)
    assert store.rows("people", "top_role, albums, seeds")[0] == ("Producer", 11, 2)


def test_the_watchlist_does_not_double_count_its_own_seed(store):
    """watchlist.json is DERIVED from a discovery file, so adding its counts
    would count that seed twice. First-wins there, summed only over seeds."""
    store.write("discovery_41620.json", {
        "seed": {"qobuz_id": 41620, "name": "Jorge Drexler"},
        "people": [{"key": "fred kevorkian", "names": ["Fred Kevorkian"],
                    "stats": {"albums": 13, "tracks": 42}}]})
    store.write("watchlist.json", {"artists": [
        {"name": "Fred Kevorkian", "qobuz_id": 1, "watch": True,
         "stats": {"albums": 13, "tracks": 42}}]})
    load.load_people(store.ld)
    assert store.rows("people", "albums, tracks, seeds")[0] == (13, 42, 1)


# ---- the seed, and who the seed made records with ------------------------


def discovery_with_co_artists(store):
    store.write("discovery_41620.json", {
        "generated": "2026-10-20",
        "seed": {"qobuz_id": 41620, "name": "Jorge Drexler", "store": "gb-en",
                 "releases": 63, "albums_own": 48, "albums_guest": 15,
                 "albums_compilation": 0, "albums_unbilled": 0,
                 "tracks": 265, "credited_tracks": 265},
        "people": [{"key": "borja barrueta", "names": ["Borja Barrueta"],
                    "stats": {"albums": 10, "own_albums": 10, "tracks": 25},
                    "albums": [{"album_id": "a1", "title": "Eco", "date": "2004-01-01",
                                "provenance": "own", "tracks": 3, "roles": ["Drums"]}]}],
        "co_artists": [
            {"key": "lau noah", "names": ["Lau Noah"],
             "albums": [{"album_id": "g1", "title": "Libertad", "date": "2023-01-01",
                         "provenance": "guest"}],
             "stats": {"albums": 1, "their_records": 1, "seed_records": 0,
                       "first": "2023-01-01", "last": "2023-01-01"}},
            {"key": "c. tangana", "names": ["C. Tangana"],
             "albums": [{"album_id": "o1", "title": "Tocarte", "date": "2021-10-28",
                         "provenance": "own"}],
             "stats": {"albums": 1, "their_records": 0, "seed_records": 1,
                       "first": "2021-10-28", "last": "2021-10-28"}}]})


def test_the_top_of_the_funnel_is_now_a_table(store):
    """63 albums, 48 of them his, 15 guest spots: it lived only in the
    discovery JSON, so "what did discovery produce" was not a query."""
    discovery_with_co_artists(store)
    load.load_people(store.ld)
    assert store.rows(
        "seeds", "name, releases, albums_own, albums_guest, people, co_artists"
    )[0] == ("Jorge Drexler", 63, 48, 15, 1, 2)


def discovery_with_a_compilation(store):
    """One seed, one co-artist, reached only through a record nobody holds."""
    store.write("discovery_27940.json", {
        "generated": "2026-10-20",
        "seed": {"qobuz_id": 27940, "name": "Björk", "store": "gb-en",
                 "releases": 153, "albums_own": 148, "albums_guest": 2,
                 "albums_compilation": 1, "albums_unbilled": 2,
                 "tracks": 1800, "credited_tracks": 1700},
        "people": [],
        "co_artists": [
            {"key": "dr. gunni", "names": ["Dr. Gunni"],
             "albums": [{"album_id": "c1", "title": "Army Of Me",
                         "date": "2005-01-01", "provenance": "compilation"}],
             "stats": {"albums": 1, "their_records": 0, "seed_records": 0,
                       "first": "2005-01-01", "last": "2005-01-01"}}]})


def test_a_various_artists_record_reaches_the_store_labelled(store):
    """Stored rather than dropped, so a label that turns out to be wrong costs
    a different WHERE clause and not a rewalk -- the same stance as D15. The
    counts beside it say nobody holds the record: neither direction scored."""
    discovery_with_a_compilation(store)
    load.load_people(store.ld)
    assert store.rows("seeds", "name, albums_compilation")[0] == ("Björk", 1)
    assert store.rows("co_artist_albums", "title, provenance")[0] == (
        "Army Of Me", "compilation")
    assert store.rows("co_artists", "name, albums, seed_records, their_records"
                      )[0] == ("Dr. Gunni", 1, 0, 0)


def test_both_directions_of_a_co_appearance_are_kept(store):
    """"guest" is the seed on their record, "own" is them on the seed's. Both
    are a record the two made together, and the hit rate was measured over
    both -- 59% against the crew graph's 13%."""
    discovery_with_co_artists(store)
    load.load_people(store.ld)
    assert dict(store.rows("co_artists", "name, their_records")) == {
        "Lau Noah": 1, "C. Tangana": 0}
    assert dict(store.rows("co_artist_albums", "title, provenance")) == {
        "Libertad": "guest", "Tocarte": "own"}


def test_a_co_artist_can_be_joined_to_listens_by_key(store):
    """The whole point of keying on normalise(name): the 59% list is only
    checkable against real listening if it shares a key with it."""
    discovery_with_co_artists(store)
    load.load_people(store.ld)
    assert {r[0] for r in store.rows("co_artists", "person_key")} == {
        "lau noah", "c. tangana"}


def test_a_person_album_says_whether_it_was_the_seeds_record(store):
    discovery_with_co_artists(store)
    load.load_people(store.ld)
    assert store.rows("person_albums", "title, provenance")[0] == ("Eco", "own")


def test_a_pool_row_records_which_seed_it_came_from(store):
    """Two pools in one table were indistinguishable in SQL, which is how a
    funnel for one seed could silently count another's rows."""
    store.write("pool.json", {
        "seed": {"qobuz_id": 41620, "name": "Jorge Drexler"},
        "pool": [{"album_id": "a1", "title": "x", "artists": ["Someone"],
                  "via": {"name": "Borja Barrueta", "top_role": "Drums", "signal": {}}}]})
    store.write("pool_discogs.json", {
        "seed": {"qobuz_id": 656411, "name": "Sílvia Pérez Cruz"},
        "pool": [{"album_id": "a2", "title": "y", "artists": ["Someone"],
                  "via": {"name": "Raül Refree", "signal": {}}}]})
    load.load_releases(store.ld)
    assert dict(store.rows("releases", "album_id, seed_qobuz_id")) == {
        "a1": 41620, "a2": 656411}
