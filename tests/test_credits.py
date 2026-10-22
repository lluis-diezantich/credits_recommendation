"""core/credits.py: splitting the Qobuz `performers` string.

The other half of the untested pair in todo.md, and the subtler half. The
mechanical part -- "Name, Role - Name, Role" -- is one line and hard to get
wrong. What needs the coverage is the packed-segment heuristic, which is the
only place in the project that GUESSES, and which fails in two directions:

  false role      a co-artist packed into a role slot becomes a role. Nothing
                  downstream rejects it: role_weight has no entry, so it scores
                  INSTRUMENT_WEIGHT and role_class files it under performance.
  lost credit     over-eager filtering drops a genuine instrument. 65 of the
                  124 role tokens in the Drexler corpus are in no policy table,
                  so an allowlist would discard real credits wholesale.

The heuristic trades the first for safety from the second, and catches 9 of the
~13 packed segments in that corpus. Both the catch and the four it cannot catch
are asserted below, because the limitation is the design and a future change
that "fixes" it is a change to what the pools contain.
"""

from __future__ import annotations

from core.credits import main_artists, parse_performers

# ---- the mechanical part -------------------------------------------------


def test_the_shape_from_the_module_docstring():
    assert parse_performers(
        "Jorge Drexler, MainArtist, Vocal - Ana Prada, Voices"
    ) == [("Jorge Drexler", ["MainArtist", "Vocal"]),
          ("Ana Prada", ["Voices"])]


def test_one_person_one_role():
    assert parse_performers("Carlos Casacuberta, Bass") == [
        ("Carlos Casacuberta", ["Bass"])]


def test_a_name_with_no_roles_is_still_a_person():
    """It happens, and dropping them would lose a collaborator entirely. The
    caller decides what an empty role list is worth -- policy.person_role_weight
    scores it 0.0, so it gates itself out without being invisible."""
    assert parse_performers("Jorge Drexler") == [("Jorge Drexler", [])]


def test_padding_is_stripped_from_names_and_roles():
    assert parse_performers("  Jorge Drexler ,  Vocal  -  Ana Prada , Guitar ") == [
        ("Jorge Drexler", ["Vocal"]), ("Ana Prada", ["Guitar"])]


def test_empty_fields_are_dropped_rather_than_becoming_blank_roles():
    """Trailing and doubled commas appear in the real strings. A "" role would
    reach role_weight(), which returns the instrument fallback for it."""
    assert parse_performers("Jorge Drexler, Vocal,, - Ana Prada, Guitar,") == [
        ("Jorge Drexler", ["Vocal"]), ("Ana Prada", ["Guitar"])]


def test_an_empty_string_is_no_people_not_one_nameless_person():
    assert parse_performers("") == []
    assert parse_performers("   ") == []
    assert parse_performers(" - ") == []


def test_role_order_is_preserved_because_the_caller_reads_the_first_one():
    """policy.person_role_weight takes roles[0] as "what they mainly are". If
    this reordered, every person's weight would come from an arbitrary credit."""
    assert parse_performers("X, Producer, Guitar, Vocal")[0][1] == [
        "Producer", "Guitar", "Vocal"]


def test_a_hyphen_inside_a_name_does_not_split_it():
    """The separator is " - " with spaces, which is what makes this safe. Both
    the hyphenated surname and the role spelling "Written-by" survive it."""
    assert parse_performers("Jean-Luc Ponty, Violin") == [
        ("Jean-Luc Ponty", ["Violin"])]
    assert parse_performers("Jorge Drexler, Written-by") == [
        ("Jorge Drexler", ["Written-by"])]


def test_the_raw_strings_are_returned_unfolded():
    """The module imports neither policy nor core.names on purpose: it returns
    what Qobuz sent and the caller decides how to normalise. A folded role here
    would break role_class, which does its own folding."""
    assert parse_performers("JORGE DREXLER, MixingEngineer") == [
        ("JORGE DREXLER", ["MixingEngineer"])]


# ---- the packed-segment heuristic ---------------------------------------


def test_a_co_artist_packed_into_a_role_slot_is_not_treated_as_a_role():
    """The bug this exists for. Without it "Rueda de Candombe" becomes a role,
    scores INSTRUMENT_WEIGHT by falling off every table, and hands a group a
    performance class they never earned."""
    assert parse_performers(
        "Jorge Drexler, Rueda de Candombe, AssociatedPerformer"
        " - Rueda de Candombe, MainArtist, AssociatedPerformer"
    ) == [("Jorge Drexler", ["AssociatedPerformer"]),
          ("Rueda de Candombe", ["MainArtist", "AssociatedPerformer"])]


def test_the_dropped_co_artist_is_not_re_emitted_from_the_packed_segment():
    """It already heads its own segment with a fuller role list -- that is the
    positive evidence the heuristic runs on. Re-emitting it would double-count
    its tracks and add nothing."""
    people = parse_performers(
        "Jorge Drexler, Rueda de Candombe, AssociatedPerformer"
        " - Rueda de Candombe, MainArtist")
    assert [name for name, _ in people].count("Rueda de Candombe") == 1


def test_an_instrument_is_never_dropped_because_it_heads_no_segment():
    """The other direction, and the one that matters more: instruments are
    open-ended, so the test has to be evidence the string carries rather than a
    vocabulary. None of these appear in any policy table."""
    assert parse_performers(
        "Jorge Drexler, Spanish Guitar, Berimbau, Wurlitzer, Theremin"
    ) == [("Jorge Drexler", ["Spanish Guitar", "Berimbau", "Wurlitzer",
                             "Theremin"])]


def test_a_token_matching_its_own_name_slot_is_kept():
    """`token != parts[0]` -- the self-reference guard. Without it a person
    credited "Foo, Foo, Guitar" would have their own name filtered out of their
    role list, which is harmless, and the guard makes it explicit instead."""
    assert parse_performers("Foo, Foo, Guitar") == [("Foo", ["Foo", "Guitar"])]


def test_the_evidence_must_be_in_the_same_string():
    """A segment head in one record says nothing about a role token in another,
    and the function sees one string at a time -- so this is a statement that
    the heuristic has no memory, which is what keeps it predictable."""
    assert parse_performers("Jorge Drexler, Rueda de Candombe, Vocal") == [
        ("Jorge Drexler", ["Rueda de Candombe", "Vocal"])]


def test_the_four_it_cannot_catch_stay_uncaught():
    """"Angeles Toledano", "Ruben Blades" and "Americo Young" appear ONLY in a
    role slot, so the string holds no evidence to catch them with. Guessing from
    capitalisation would put every instrument at risk -- a worse trade. Asserted
    so the known false-role rate is visible rather than folklore."""
    assert parse_performers(
        "Jorge Drexler, Angeles Toledano, AssociatedPerformer"
    ) == [("Jorge Drexler", ["Angeles Toledano", "AssociatedPerformer"])]


def test_a_head_only_filters_other_segments_not_the_whole_string():
    """Three segments, where the middle one's head is packed into the first.
    Only that token goes; the third segment's identical-looking role stays,
    because it is a role there."""
    assert parse_performers(
        "A, B, Guitar - B, MainArtist - C, Guitar"
    ) == [("A", ["Guitar"]), ("B", ["MainArtist"]), ("C", ["Guitar"])]


def test_every_segment_head_survives_as_a_person():
    """The invariant worth holding whatever the heuristic does: filtering
    happens in the role slot only, so the set of people is exactly the set of
    heads. A person lost here is a collaborator missing from the pool."""
    credits = ("Jorge Drexler, Rueda de Candombe, AssociatedPerformer"
               " - Rueda de Candombe, MainArtist"
               " - Ana Prada, Voices")
    heads = [segment.split(",")[0].strip() for segment in credits.split(" - ")]
    assert [name for name, _ in parse_performers(credits)] == heads


# ---- who the record is BY ------------------------------------------------


def test_main_artists_from_the_module_docstring():
    assert main_artists(
        "Jorge Drexler, MainArtist, Vocal - Ana Prada, Voices") == ["Jorge Drexler"]


def test_several_artists_share_the_billing_in_the_order_given():
    assert main_artists(
        "Jorge Drexler, MainArtist - C. Tangana, MainArtist, Vocal"
    ) == ["Jorge Drexler", "C. Tangana"]


def test_a_track_with_no_billing_names_nobody():
    """Not an error: 0 of the 500 cached tracks are like this, and
    policy.album_provenance calls a whole album of them "unknown"."""
    assert main_artists("Borja Barrueta, Drums - Matias Cella, Producer") == []
    assert main_artists("") == []


def test_the_role_is_matched_whatever_its_case():
    assert main_artists("Lau Noah, mainartist") == ["Lau Noah"]
    assert main_artists("Lau Noah, MAINARTIST") == ["Lau Noah"]


def test_featuredartist_is_not_mainartist():
    """A feature is a billing credit and not authorship of the record. The
    question here is who the record is BY, and Qobuz answers it with one role."""
    assert main_artists("Ana Tijoux, FeaturedArtist") == []


def test_a_co_artist_packed_into_a_role_slot_is_not_billed_by_accident():
    """The packed-segment form above, now reaching a function that reads roles
    by name: "Rueda de Candombe" sits in a role slot, and parse_performers
    drops it there because it heads its own segment -- so it is billed from
    that segment and never from the seed's."""
    packed = ("Jorge Drexler, Rueda de Candombe, MainArtist"
              " - Rueda de Candombe, MainArtist, AssociatedPerformer")
    assert main_artists(packed) == ["Jorge Drexler", "Rueda de Candombe"]


# ---- a name in the role slot, spelled differently -----------------------


def test_the_same_artist_spelled_two_ways_in_one_string_is_not_a_role():
    """Berghain (Remix), as Qobuz returns it: "ROSALÍA" sits in a role slot and
    "Rosalia" heads a segment of the same string. An exact comparison does not
    see it, and the name reached the printed explanation as a role -- "credited
    on 1 track (re-mixer, rosalia, bjork & yves tumor)"."""
    said = dict(parse_performers(
        "Conrad Taylor, MainArtist, Re-Mixer - Rosalia, MainArtist - "
        "Conrad Taylor, ROSALÍA, AssociatedPerformer"))
    assert said["Conrad Taylor"] == ["AssociatedPerformer"]


def test_two_names_joined_with_an_ampersand_are_both_names():
    """"Björk & Yves Tumor" is two heads in one token and no head at all, so
    each side is tested on its own."""
    said = dict(parse_performers(
        "Rosalia, MainArtist - Bjork, MainArtist - Yves Tumor, MainArtist - "
        "Rosalia, Björk & Yves Tumor, AssociatedPerformer"))
    assert said["Rosalia"] == ["AssociatedPerformer"]


def test_an_ampersand_token_with_one_side_unknown_stays_a_role():
    """Positive evidence only: if the string does not name both sides, it does
    not hold the evidence to call the token a billing."""
    said = dict(parse_performers(
        "Bjork, MainArtist - Bjork, Björk & Somebody Else, AssociatedPerformer"))
    assert "Björk & Somebody Else" in said["Bjork"]


def test_a_token_matching_its_own_head_is_still_a_role():
    """A string repeating itself is not a collaborator, and dropping the token
    would lose a real role on a segment that has only one."""
    said = dict(parse_performers("Bjork, Bjork - Mark Bell, Composer"))
    assert said["Bjork"] == ["Bjork"]


def test_an_instrument_is_never_mistaken_for_a_name():
    """The allowlist objection in the module docstring, as a test: 65 of 124
    role tokens in one corpus are in no policy table and nearly all are
    genuine, so the fold must not widen what counts as a name."""
    said = dict(parse_performers(
        "Jorge Drexler, Spanish Guitar, Berimbau, Theremin - Borja Barrueta, Timpani"))
    assert said["Jorge Drexler"] == ["Spanish Guitar", "Berimbau", "Theremin"]


def test_two_names_joined_with_feat_are_both_names():
    """Same shape as "&" with a different joiner, and it reached a printed
    explanation: "credited on 1 track (nicki nicole feat. nathy peluso)"."""
    said = dict(parse_performers(
        "Christina Aguilera, MainArtist - Nicki Nicole, MainArtist - "
        "Nathy Peluso, MainArtist - "
        "Christina Aguilera, Nicki Nicole feat. Nathy Peluso, AssociatedPerformer"))
    assert said["Christina Aguilera"] == ["AssociatedPerformer"]


def test_every_joiner_qobuz_uses_is_split():
    from core.credits import split_billing
    for joined in ("A & B", "A feat. B", "A feat B", "A featuring B"):
        assert split_billing(joined) == ["a", "b"], joined


def test_a_name_with_no_joiner_is_one_piece():
    from core.credits import split_billing
    assert split_billing("Nellee Hooper") == ["nellee hooper"]


def test_a_feat_token_with_one_side_unknown_stays_a_role():
    """Positive evidence only, in the joined case too."""
    said = dict(parse_performers(
        "Amaral, MainArtist - Amaral, Sidonie feat. Dani Martín, AssociatedPerformer"))
    assert "Sidonie feat. Dani Martín" in said["Amaral"]
