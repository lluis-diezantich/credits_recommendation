"""stages/discover.py: own record or guest spot, and who the seed is billed with.

The first tests this file has had. `album_billing` is the only decision in it
that is not plumbing, and it was extracted to be testable for the reason
todo.md gives: Qobuz files a guest spot inside the GUEST's discography, so
artist/get on a seed returns records the seed did not make, and discovery
credited everyone aboard as having worked on the seed's records. 15 of
Drexler's 62 albums and 3 of Perez Cruz's 44 are somebody else's.

The titles cannot be the test -- only 5 of those 15 say "feat." -- so these
fixtures deliberately carry titles that point the wrong way, to pin that the
billing is what decides and the title is never read.

The orchestration around it (main(), the fetch loop) is still uncovered, and
that is what it IS now that the decision has moved out.
"""

from __future__ import annotations

from stages.discover import album_billing, fold_editions

SEED = {"jorge drexler"}


def track(performers: str) -> dict:
    return {"id": 1, "title": "t", "performers": performers}


def test_a_record_the_seed_is_billed_on_is_their_own():
    tracks = [track("Jorge Drexler, MainArtist, Vocal - Borja Barrueta, Drums")] * 3
    assert album_billing(tracks, SEED) == ("own", [])


def test_a_record_the_seed_is_not_billed_on_belongs_to_whoever_is():
    """The leak, in one case: the seed sang on Lau Noah's record, so she is the
    artist he made a record WITH -- not a person who worked on his."""
    tracks = [track("Lau Noah, MainArtist, Vocal - Jorge Drexler, Vocal")]
    assert album_billing(tracks, SEED) == ("guest", ["Lau Noah"])


def test_the_title_is_never_read():
    """5 of the 15 guest albums say "feat." and the other 10 do not, so a title
    test catches a third of them. Billing catches all 15."""
    says_nothing = [track("Perota Chingo, MainArtist - Jorge Drexler, Vocal")]
    says_feat = [track("Lau Noah, MainArtist - Jorge Drexler, Vocal")]
    assert album_billing(says_nothing, SEED)[0] == "guest"
    assert album_billing(says_feat, SEED)[0] == "guest"


def test_a_guest_on_the_seeds_own_record_is_still_a_co_appearance():
    """The direction todo.md did not count: 23 of Drexler's co-appearances are
    guests on HIS records, and they hit 57% against real listening."""
    tracks = [track("Jorge Drexler, MainArtist - C. Tangana, MainArtist"),
              track("Jorge Drexler, MainArtist, Vocal")]
    assert album_billing(tracks, SEED) == ("own", ["C. Tangana"])


def test_one_track_of_twenty_does_not_make_it_the_seeds_record():
    """Why the rule is a share and not "is the seed billed anywhere on it".
    No album in either corpus is in between, so this case is the floor's only
    witness -- see policy.OWN_ALBUM_MAIN_SHARE. One artist holds 19 of the 20,
    so the record is theirs: this is a guest spot and not a compilation."""
    tracks = ([track("Jorge Drexler, MainArtist")]
              + [track("Various Hands, MainArtist")] * 19)
    provenance, others = album_billing(tracks, SEED)
    assert provenance == "guest"
    assert others == ["Various Hands"]


def test_a_record_nobody_holds_is_neither_the_seeds_nor_anybody_elses():
    """Army Of Me, in the shape Qobuz returns it: 20 tracks, a different
    remixer billed on each, Bjork filed as the composer throughout. Every one
    of the 20 read as an artist whose own record she had appeared on."""
    tracks = [track(f"Remixer {i}, MainArtist - Jorge Drexler, Composer")
              for i in range(20)]
    provenance, others = album_billing(tracks, SEED)
    assert provenance == "compilation"
    assert len(others) == 20


def test_a_four_way_single_is_not_a_compilation():
    """"WE PRAY" is four artists on one track, so each of them holds the whole
    record -- the opposite shape from 20 artists on 20 tracks, and the reason
    the test counts the top HOLDER rather than the artists."""
    tracks = [track("Coldplay, MainArtist - Burna Boy, MainArtist - "
                    "Elyanna, MainArtist - Jorge Drexler, MainArtist")]
    provenance, others = album_billing(tracks, SEED)
    assert provenance == "own"
    assert others == ["Coldplay", "Burna Boy", "Elyanna"]


def test_the_seeds_hold_is_counted_over_every_name_they_are_filed_under():
    """D23 gave the seed a SET of keys, and summing per key would split one
    artist's hold over two spellings and read a record they plainly own as a
    record nobody holds."""
    both = {"jorge drexler", "jorge drexler prada"}
    tracks = [track("Jorge Drexler, MainArtist"),
              track("Jorge Drexler, MainArtist"),
              track("Jorge Drexler Prada, MainArtist"),
              track("Jorge Drexler Prada, MainArtist")]
    assert album_billing(tracks, both) == ("own", [])


def test_an_album_nobody_is_billed_on_is_unknown_rather_than_guest():
    """Absence of evidence. All 500 cached tracks carry a MainArtist, so this
    is a guard with no instance -- and the failure it guards against is
    relabelling a whole discography as somebody else's."""
    assert album_billing([track("Borja Barrueta, Drums")], SEED) == ("unknown", [])


def test_tracks_with_no_credits_at_all_do_not_count_against_the_share():
    """An uncredited track is not a track billed to somebody else."""
    tracks = [track("Jorge Drexler, MainArtist"), track(""), track("")]
    assert album_billing(tracks, SEED) == ("own", [])


def test_a_co_artist_billed_on_every_track_is_named_once():
    tracks = [track("Jorge Drexler, MainArtist - Kevin Johansen, MainArtist")] * 11
    assert album_billing(tracks, SEED) == ("own", ["Kevin Johansen"])


def test_the_first_spelling_of_a_name_wins():
    """Keyed on normalise(), like everything else here, so the accented and
    bare spellings are one artist and the one Qobuz printed first is kept."""
    tracks = [track("Jorge Drexler, MainArtist - Anavitória, MainArtist"),
              track("Jorge Drexler, MainArtist - Anavitoria, MainArtist")]
    assert album_billing(tracks, SEED) == ("own", ["Anavitória"])


def test_every_name_the_seed_is_credited_under_counts_as_the_seed():
    """The defect the Bjork probe found: Qobuz files a record under whichever
    name the label used, so reading only the performing name made
    "Bjork Gudmundsdottir" -- 120 of her 148 own albums -- her own biggest
    collaborator, and would file those albums as guest spots."""
    tracks = [track("Björk Guðmundsdóttir, MainArtist, Vocal")]
    # normalise() drops the eth rather than transliterating it, so the key is
    # "gumundsdottir". MusicBrainz happens to list both spellings, which is
    # why the real run catches it either way -- but the key is what matches.
    assert album_billing(tracks, {"bjork", "bjork gumundsdottir"}) == ("own", [])
    # and with only the performing name, the same album reads as somebody else's
    assert album_billing(tracks, {"bjork"}) == ("guest", ["Björk Guðmundsdóttir"])


def test_the_seed_is_never_their_own_co_appearance_however_it_is_spelled():
    """`seed_key` arrives normalised; the billing does not. "Silvia Perez Cruz"
    must not be billed alongside "Sílvia Pérez Cruz"."""
    tracks = [track("Sílvia Pérez Cruz, MainArtist, Vocal")]
    assert album_billing(tracks, {"silvia perez cruz"}) == ("own", [])


# ---- editions -----------------------------------------------------------


def album(album_id, title, date, provenance="own"):
    return {"album_id": album_id, "title": title, "date": date,
            "provenance": provenance}


def test_one_single_under_five_ids_counts_once():
    """"WE PRAY" is five album ids, so Coldplay, Burna Boy, Elyanna and tINI
    each scored five co-appearances off one song -- and a ranker would have
    put them at the top of the Little Simz list on the strength of it."""
    editions = [album(f"id{n}", "WE PRAY ", "2024-09-01") for n in range(5)]
    assert len(fold_editions(editions)) == 1


def test_the_earliest_edition_is_the_one_kept():
    """The original, not whichever reissue sorted first."""
    kept = fold_editions([album("b", "Debut", "2015-01-01"),
                          album("a", "Debut", "1993-07-05")])
    assert [a["album_id"] for a in kept] == ["a"]


def test_different_records_are_not_folded():
    kept = fold_editions([album("a", "Vespertine", "2001-08-27"),
                          album("b", "Homogenic", "1997-09-22")])
    assert len(kept) == 2


def test_folding_is_on_the_normalised_title():
    """Trailing space and case are how Qobuz spells the same release twice."""
    assert len(fold_editions([album("a", "WE PRAY ", "2024-09-01"),
                              album("b", "we pray", "2024-09-02")])) == 1


def test_the_output_is_ordered_by_date():
    kept = fold_editions([album("c", "Z", "2020-01-01"), album("a", "A", "1990-01-01")])
    assert [a["title"] for a in kept] == ["A", "Z"]


def test_no_albums_folds_to_nothing():
    assert fold_editions([]) == []
