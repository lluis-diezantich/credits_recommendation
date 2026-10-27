"""core/names.py -- the key every identity in this project is minted from.

Its own file because `normalise` is the one function a change to breaks
everything downstream: a key that moves re-splits a person the old key merged,
which is what docs/adr/D25 exists to prevent and docs/adr/D40 is about.
"""

from __future__ import annotations

import pytest

from core.names import normalise, strip_discogs_suffix

# ---- what it has always done --------------------------------------------


def test_accents_are_stripped_and_case_folded():
    assert normalise("Sílvia Pérez Cruz") == "silvia perez cruz"
    assert normalise("JORGE DREXLER") == "jorge drexler"


def test_whitespace_is_collapsed_not_merely_trimmed():
    assert normalise("  Carles   Campi  Campon ") == "carles campi campon"


def test_a_name_with_nothing_in_it_is_the_empty_key():
    assert normalise("") == ""
    assert normalise("   ") == ""


# ---- quotes: the defect D40 fixed ---------------------------------------


@pytest.mark.parametrize("written", ["Oscar D’León", "Oscar D'León",
                                     "OSCAR D’LEON", "Oscar DʼLeón"])
def test_every_apostrophe_spelling_mints_one_key(written):
    """The measured defect: the NFKD pass drops a typographic apostrophe,
    which has no ASCII form, and keeps a straight one. So his 238 listens were
    keyed `oscar d'leon` and his profile row `oscar dleon`, and no lookup
    between the two ever matched. Four artists lost their play history.
    """
    assert normalise(written) == "oscar dleon"


@pytest.mark.parametrize("written,expected", [
    ("Guns N’ Roses", "guns n roses"),
    ("Guns N' Roses", "guns n roses"),
    ("Mother’s Cake", "mothers cake"),
    ("Mother's Cake", "mothers cake"),
    ("Adolescent’s Orquesta", "adolescents orquesta"),
])
def test_the_artists_that_lost_their_plays(written, expected):
    assert normalise(written) == expected


@pytest.mark.parametrize("written", ['MARK “SPIKE” STENT',
                                     'Mark "Spike" Stent',
                                     "Mark 'Spike' Stent"])
def test_a_nickname_in_quotes_reads_the_same_whichever_quotes_were_used(written):
    """Removed rather than folded to one form. Folding would have produced
    `mark 'spike' stent` and kept a decoration nothing wants; removing gives
    what the typographic spelling already produced, so 142 of the 166 keys
    that moved landed where the other spelling already was.
    """
    assert normalise(written) == "mark spike stent"


def test_removal_merges_the_pairs_the_corpus_holds_twice():
    """Eight pairs in the corpus are one person under two spellings, and each
    would otherwise need a hand entry in data/aliases.json. One already had
    one -- Jórunn Viðar's "two apostrophes standing in for one accent"."""
    for a, b in [("Me'Shell Ndegéocello", "Meshell Ndegeocello"),
                 ('Hector "El Father"', "Hector El Father"),
                 ("Bonnie 'Prince' Billy", "Bonnie Prince Billy"),
                 ('Santana "The Golden Boy"', "Santana The Golden Boy")]:
        assert normalise(a) == normalise(b), (a, b)


def test_two_different_people_are_still_two_keys():
    """The risk removal carries. Checked over every name in the corpus when
    D40 was measured: the only keys that met were the eight pairs above."""
    assert normalise("Toni Pérez Diz") != normalise("Félix Pérez Diz")
    assert normalise("Lucas Piedracueva") != normalise("Lucas Piedra")


def test_a_quote_is_not_turned_into_a_space():
    """`O'Quin` is one word. Replacing the quote with a space would make it
    two and collide with everything else called "O Quin"."""
    assert normalise("Kyle O’Quin") == "kyle oquin"
    assert normalise("Niamh O'Sullivan") == "niamh osullivan"


# ---- the Discogs decorations, which are a different job -----------------


def test_discogs_decorations_are_stripped_by_their_own_function():
    """Not normalise's job: these are Discogs' numbering, not a name key, and
    the two were separate before the quote change and stay separate."""
    assert strip_discogs_suffix("Mauro (5)") == "Mauro"
    assert strip_discogs_suffix("Valeria Castro*") == "Valeria Castro"
