"""stages/co_artists.py: what reaches the list, and what is filtered on the way.

The judgements are in policy -- `MADE_TOGETHER` and `NOT_ARTISTS`, tested in
test_policy.py. What this file pins is that the stage APPLIES them on read,
which is where D15 puts a filter: the row stays in the store, so a label that
turns out to be wrong costs a different query rather than a rewalk.

The corpus behind the fixtures is Bjork's, from the 2026-10-20 walk. 20 of her
35 co-artists came off "Army Of Me", a remix album where each of 20 remixers
holds one track, and every one of them read as an artist whose own record she
had appeared on -- with a fluent sentence each since D21, which is what makes a
wrong row convincing rather than obvious.

test_explain.py covers the same stage from the other end: the sentence it
writes once a row has earned its place.
"""

from __future__ import annotations

import sqlite3
import sys

import pytest

import stages.co_artists as co_artists
import stages.load as load

SEED = 27940
SEED_NAME = "Björk"


@pytest.fixture
def store(tmp_path):
    """A store with the real SCHEMA, and a helper that writes one co-artist.

    Rows go in directly rather than through load.py, which has its own tests:
    what these need is a store whose contents each say exactly one thing.
    """
    path = tmp_path / "music.db"
    con = sqlite3.connect(path)
    for statement in load.SCHEMA.strip().split(";"):
        if statement.strip():
            con.execute(statement)
    con.execute("INSERT INTO seeds (seed_qobuz_id, name) VALUES (?, ?)",
                (SEED, SEED_NAME))

    def co_artist(key, name, albums):
        """One co-artist and their shared albums, as (title, provenance, date).

        The two counts are derived here the way discover.py derives them, so a
        compilation lands in neither -- it says whose record it is not.
        """
        con.execute(
            "INSERT INTO co_artists (seed_qobuz_id, person_key, name, albums,"
            " seed_records, their_records, first_seen, last_seen)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (SEED, key, name, len(albums),
             sum(a[1] == "own" for a in albums),
             sum(a[1] == "guest" for a in albums),
             min(a[2] for a in albums), max(a[2] for a in albums)))
        for title, provenance, date in albums:
            con.execute(
                "INSERT INTO co_artist_albums (seed_qobuz_id, person_key,"
                " album_id, title, date, provenance) VALUES (?, ?, ?, ?, ?, ?)",
                (SEED, key, title, title, date, provenance))

    def credit(album_id, key, role, track_id=1):
        con.execute(
            "INSERT INTO credits (album_id, track_id, track_title, person_key,"
            " role, role_class) VALUES (?, ?, ?, ?, ?, '')",
            (album_id, track_id, album_id, key, role))

    class Handle:
        def __init__(self):
            self.path = path
            self.co_artist = co_artist
            self.credit = credit

        def commit(self):
            con.commit()

    return Handle()


@pytest.fixture
def run(store, monkeypatch, capsys):
    """The stage over this store, as (stdout, stderr)."""
    def invoke(*args):
        store.commit()
        monkeypatch.setattr(sys, "argv",
                            ["co_artists.py", "--db", str(store.path), *args])
        assert co_artists.main() == 0
        return capsys.readouterr()
    return invoke


# ---- a record nobody holds ----------------------------------------------


def test_a_co_artist_reached_only_through_a_compilation_is_not_one(store, run):
    """Dr. Gunni remixed a Bjork track on Army Of Me. She did not appear on
    his record, and he did not appear on hers."""
    store.co_artist("dr. gunni", "Dr. Gunni",
                    [("Army Of Me", "compilation", "2005-01-01")])
    said = run()
    assert "Dr. Gunni" not in said.out
    # And the reason given is the real one. An empty list because you play
    # everybody is a result; an empty one because nothing survived the filters
    # is not the same thing and used to print the same sentence.
    assert "no co-appearance here is a record somebody holds" in said.out


def test_the_compilation_is_not_counted_as_a_co_appearance_either(store, run):
    """The total under the list is what somebody would check, so a filtered
    row must not still be in the number -- 121 co-appearances became 97."""
    store.co_artist("dr. gunni", "Dr. Gunni",
                    [("Army Of Me", "compilation", "2005-01-01")])
    store.co_artist("thom yorke", "Thom Yorke",
                    [("Biophilia", "own", "2011-01-01")])
    assert "1 artists, from 1 co-appearances" in run().out


def test_a_real_record_survives_a_compilation_beside_it(store, run):
    """Patrick Wolf is on Army Of Me AND made a record with her. The album
    nobody holds is dropped; he is not."""
    store.co_artist("patrick wolf", "Patrick Wolf",
                    [("Army Of Me", "compilation", "2005-01-01"),
                     ("Vulnicura", "own", "2015-01-01")])
    said = run().out
    assert "Patrick Wolf" in said
    assert "Army Of Me" not in said
    assert "Vulnicura" in said


def test_a_role_earned_on_a_compilation_is_not_evidence(store, run):
    """The sentence names what the person did on the records the two of them
    made together, so a remix credit on a various-artists album cannot become
    one of them."""
    store.co_artist("patrick wolf", "Patrick Wolf",
                    [("Army Of Me", "compilation", "2005-01-01"),
                     ("Vulnicura", "own", "2015-01-01")])
    store.credit("Army Of Me", "patrick wolf", "Remixer")
    store.credit("Vulnicura", "patrick wolf", "Guitar")
    said = run().out
    assert "(guitar)" in said and "remixer" not in said


def test_the_list_is_ordered_by_records_somebody_holds(store, run):
    """Not by `albums`, which counts a sleeve two artists are both printed on:
    ranking by it put four artists at the top of the Little Simz list on the
    strength of one single stored five times, and would do the same for a
    remix compilation."""
    store.co_artist("compiled", "Compiled",
                    [(f"Army Of Me {n}", "compilation", "2005-01-01")
                     for n in range(5)]
                    + [("Real Record", "own", "2005-02-01")])
    store.co_artist("thom yorke", "Thom Yorke",
                    [("Nattura", "guest", "2008-01-01"),
                     ("Biophilia", "own", "2011-01-01")])
    said = run().out
    assert said.index("Thom Yorke") < said.index("Compiled")


# ---- billings that are not an artist ------------------------------------


def test_a_billing_that_is_not_an_artist_is_dropped_and_named(store, run):
    """Named on stderr rather than silently: a hand list that quietly grows is
    how a real collaborator disappears without anybody noticing."""
    store.co_artist("colors", "Colors",
                    [("Capitana - A COLORS SHOW", "own", "2026-01-01")])
    store.co_artist("thom yorke", "Thom Yorke",
                    [("Biophilia", "own", "2011-01-01")])
    said = run()
    assert "Colors" not in said.out
    assert "1 billing(s) dropped as not an artist: Colors" in said.err
    assert "1 artists, from 1 co-appearances" in said.out


def test_the_drop_is_reported_where_json_output_stays_parseable(store, run):
    """--json is the handoff to anything downstream, so the note goes to
    stderr and the document stays a document."""
    import json
    store.co_artist("colors", "Colors",
                    [("Capitana - A COLORS SHOW", "own", "2026-01-01")])
    said = run("--json")
    assert json.loads(said.out) == []
    assert "Colors" in said.err


def test_nothing_left_at_all_still_explains_itself(store, run):
    """The empty case the stage already handled, now reachable by filtering
    rather than only by having played everybody -- and it used to claim the
    wrong reason for it."""
    store.co_artist("colors", "Colors",
                    [("Capitana - A COLORS SHOW", "own", "2026-01-01")])
    said = run().out
    assert "nothing to show" in said
    assert "already play" not in said


def test_a_billing_with_nothing_musical_behind_it_is_dropped(store, run):
    """Liniers draws on stage at Drexler's live shows and is billed for it.
    Caught by rule rather than by name since the role classes were fixed."""
    store.co_artist("liniers", "Liniers",
                    [("No Voy a Ser Yo", "own", "2025-01-01")])
    store.credit("No Voy a Ser Yo", "liniers", "MainArtist")
    store.credit("No Voy a Ser Yo", "liniers", "Designer")
    store.co_artist("thom yorke", "Thom Yorke",
                    [("Biophilia", "own", "2011-01-01")])
    said = run()
    assert "Liniers" not in said.out
    assert "1 billing(s) dropped as not an artist: Liniers" in said.err
    assert "1 artists, from 1 co-appearances" in said.out


def test_a_guest_who_also_drew_the_sleeve_is_kept(store, run):
    store.co_artist("rosie lowe", "Rosie Lowe",
                    [("So Human", "guest", "2016-01-01")])
    store.credit("So Human", "rosie lowe", "Designer")
    store.credit("So Human", "rosie lowe", "Vocalist")
    assert "Rosie Lowe" in run().out


def test_a_co_artist_with_no_role_credit_at_all_is_kept(store, run):
    """Billing-only is 57 of 132 rows, and the sentence for them is honest
    without a role clause."""
    store.co_artist("twice", "Twice", [("WE PRAY", "own", "2025-01-01")])
    assert "Twice" in run().out


def test_the_report_groups_by_seed_instead_of_interleaving(store, run):
    """One header per seed. A purely global order printed the same seed's
    header once per run of its rows -- five seeds interleaved gave "Björk"
    four separate times."""
    store.co_artist("thom yorke", "Thom Yorke",
                    [("Biophilia", "own", "2011-01-01")])
    store.co_artist("david arnold", "David Arnold",
                    [("Play Dead", "own", "1993-01-01"),
                     ("Greatest Hits", "own", "2002-01-01")])
    said = run().out
    # The header, not every mention: the sentences name the seed too.
    headers = [line for line in said.splitlines() if line == SEED_NAME]
    assert len(headers) == 1
    # And inside the group the stronger co-appearance still comes first.
    assert said.index("David Arnold") < said.index("Thom Yorke")
