"""core/explain.py and stages/co_artists.py: the sentence, and the facts in it.

Every clause has to be traceable to a row, so the tests are mostly about what
the sentence must NOT say: no pronouns for people whose gender the store does
not know, no "e.g." in front of the only record there is, no role clause built
out of billing credits, and no plural when there is one of something.
"""

from __future__ import annotations

import sqlite3

import pytest

import stages.co_artists as mod
import stages.load as load
from core.explain import co_artist_sentence, role_phrase, year

SEED = "Jorge Drexler"


# ---- the sentence -------------------------------------------------------


def test_the_shape_from_the_module_docstring():
    assert co_artist_sentence(
        "Juan Falú", "Sílvia Pérez Cruz", 4, 0, tracks=13,
        roles=["Guitar", "Producer"],
        example=("Chacarera de las Piedras", "2024-10-25"), plays=0
    ) == ("Juan Falú is billed on 4 of Sílvia Pérez Cruz's records, credited on "
          "13 tracks (guitar, producer) - e.g. Chacarera de las Piedras (2024). "
          "Never played.")


def test_the_seed_guesting_on_their_record_reads_the_other_way_round():
    """The two directions are different claims. This one is the seed CHOOSING
    to appear on somebody else's album."""
    assert co_artist_sentence("Lau Noah", SEED, 0, 1) == (
        f"{SEED} appears on Lau Noah's own record.")


def test_the_seed_guesting_on_several_of_their_records_is_plural():
    assert co_artist_sentence("Carmen Linares", SEED, 0, 2) == (
        f"{SEED} appears on 2 of Carmen Linares's own records.")


def test_both_directions_are_counted_together():
    assert co_artist_sentence("Kevin Johansen", SEED, 1, 1).startswith(
        f"Kevin Johansen and {SEED} share 2 records: 1 of {SEED}'s and "
        "1 of Kevin Johansen's")


def test_no_pronoun_is_ever_invented():
    """The store knows names, not genders, so the name is repeated where a
    pronoun would go. Getting this wrong misgenders a real person."""
    for own, guest in ((4, 0), (0, 1), (1, 1), (0, 0)):
        said = co_artist_sentence("Lau Noah", SEED, own, guest, plays=0)
        assert not any(f" {w} " in f" {said} " for w in
                       ("his", "her", "hers", "he", "she", "him"))


def test_one_record_is_not_an_example():
    """"e.g." in front of the only record there is overstates the evidence."""
    one = co_artist_sentence("Lau Noah", SEED, 0, 1, example=("Libertad", "2023-01-01"))
    assert "- Libertad (2023)" in one and "e.g." not in one
    many = co_artist_sentence("C. Tangana", SEED, 2, 0, example=("Tocarte", "2021-10-28"))
    assert "- e.g. Tocarte (2021)" in many


def test_one_of_something_is_never_plural():
    assert "one of" in co_artist_sentence("X", SEED, 1, 0)
    assert "records" in co_artist_sentence("X", SEED, 2, 0)
    assert co_artist_sentence("X", SEED, 1, 0, tracks=1, roles=["Guitar"]).endswith(
        "credited on 1 track (guitar).")


def test_a_role_clause_needs_both_a_role_and_a_track_count():
    """Half the evidence is not evidence: "credited on 13 tracks" with no role
    says nothing, and a role with no count cannot be checked."""
    assert "credited on" not in co_artist_sentence("X", SEED, 2, 0, tracks=13)
    assert "credited on" not in co_artist_sentence("X", SEED, 2, 0, roles=["Guitar"])


def test_a_credit_is_named_in_the_words_a_listener_uses():
    assert role_phrase(["Composer"]) == "writer"
    assert role_phrase(["Background Vocal"]) == "backing vocals"


def test_an_unmapped_credit_is_printed_rather_than_guessed():
    """65 of the corpus's 124 role tokens are in no table. A verb lexicon with
    a guessy fallback produces "played mastering engineer"."""
    assert role_phrase(["Berimbau"]) == "berimbau"
    assert role_phrase(["Mastering Engineer"]) == "mastering engineer"


def test_the_same_credit_twice_is_named_once():
    assert role_phrase(["Guitar", "guitar", "Vocals"]) == "guitar, vocals"


def test_no_plays_column_means_the_sentence_says_nothing_about_listening():
    """A caller that has not looked it up must not have "Never played" put in
    its mouth."""
    assert co_artist_sentence("X", SEED, 1, 0).endswith("records.")
    assert co_artist_sentence("X", SEED, 1, 0, plays=0).endswith("Never played.")
    assert co_artist_sentence("X", SEED, 1, 0, plays=7).endswith("Played 7 times.")


def test_a_missing_date_leaves_the_year_out_rather_than_printing_empty_brackets():
    assert year(None) == "" and year("") == ""
    assert co_artist_sentence("X", SEED, 0, 1, example=("Untitled", None)) == (
        f"{SEED} appears on X's own record - Untitled.")


# ---- assembled from the store -------------------------------------------


@pytest.fixture
def store(tmp_path):
    """A real store with one seed, one co-artist and their credits."""
    db = tmp_path / "music.db"
    con = sqlite3.connect(db)
    for statement in load.SCHEMA.strip().split(";"):
        if statement.strip():
            con.execute(statement)
    con.execute("INSERT INTO seeds (seed_qobuz_id, name) VALUES (41620, ?)", (SEED,))
    con.execute("""INSERT INTO co_artists (seed_qobuz_id, person_key, name, albums,
                   their_records, seed_records, last_seen)
                   VALUES (41620, 'lau noah', 'Lau Noah', 1, 1, 0, '2023-01-01')""")
    con.execute("""INSERT INTO co_artist_albums (seed_qobuz_id, person_key, album_id,
                   title, date, provenance)
                   VALUES (41620, 'lau noah', 'g1', 'Libertad', '2023-01-01', 'guest')""")
    for role, track in (("MainArtist", 1), ("Guitar", 1), ("Mastering Engineer", 1)):
        con.execute("""INSERT INTO credits (album_id, track_id, track_title,
                       person_key, role, role_class) VALUES ('g1', ?, 'Libertad',
                       'lau noah', ?, '')""", (track, role))
    con.commit()
    return db


def run(db, *args):
    import contextlib
    import io
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        mod.sys.argv = ["co_artists.py", "--db", str(db), *args]
        assert mod.main() == 0
    return out.getvalue()


def test_the_report_names_only_what_the_person_did(store):
    """MainArtist is why they are in the list at all, and Mastering Engineer
    tells a listener nothing. Guitar is the answer."""
    said = run(store)
    assert "(guitar)" in said
    assert "mainartist" not in said and "mastering" not in said


def test_an_artist_you_already_play_is_hidden_unless_asked_for(store):
    con = sqlite3.connect(store)
    con.execute("INSERT INTO listens (artist_key) VALUES ('lau noah')")
    con.commit()
    assert "Lau Noah" not in run(store)
    assert "Played 1 times" in run(store, "--all")


def test_a_store_with_no_such_table_says_to_build_it(tmp_path):
    (tmp_path / "empty.db").write_bytes(b"")
    mod.sys.argv = ["co_artists.py", "--db", str(tmp_path / "empty.db")]
    with pytest.raises(SystemExit, match="load.py"):
        mod.main()


def test_a_co_appearance_with_no_direction_still_says_something_true():
    """Both counts zero should not happen -- a co-artist is in the list
    BECAUSE of a shared record -- but a missing count must not produce "billed
    on 0 records"."""
    assert co_artist_sentence("X", SEED, 0, 0) == f"X is credited alongside {SEED}."


def test_json_is_the_same_facts_the_sentence_was_built_from(store):
    """So anything downstream can re-render rather than parse prose."""
    import json as _json
    rows = _json.loads(run(store, "--json"))
    assert rows[0]["roles"] == ["Guitar"] and rows[0]["on_their_records"] == 1
    assert rows[0]["why"].startswith(f"{SEED} appears on Lau Noah's own record")


def test_nothing_to_show_is_said_rather_than_printing_an_empty_list(store):
    con = sqlite3.connect(store)
    con.execute("INSERT INTO listens (artist_key) VALUES ('lau noah')")
    con.commit()
    assert "nothing to show" in run(store)
