"""core/appearances.py: is a credit on somebody else's record news?

Every string here is a real `performers` value or a real album title from the
D42 backfill, because the decisions this module makes were all derived from
that run and a synthetic example would not have caught any of them.
"""

from __future__ import annotations

from core.appearances import (
    Credit,
    appearance_key,
    credits_for,
    is_retrospective,
    verdict,
)

# The credit that prompted the whole thing: a track-level feature that never
# appears in the guest's own discography.
ANANTA = ("Miguel Atwood-Ferguson, MainArtist, RecordingArranger, Other, "
          "AdditionalEngineer, MixingEngineer, Producer, ComposerLyricist - "
          "Aja Monet, FeaturedArtist, SpokenWord, ComposerLyricist - "
          "Peter Jacobson, AdditionalEngineer - Chad Gordon, RecordingEngineer")

# A cover. The watched artist wrote the song and is on none of it, which is the
# single biggest category of false positive -- 96 of 238 in D42.
COVER = ('Wanna, MainArtist - Jhon Stiven Lizcano Montoya "Mr Montoya", '
         "Composer, Writer - Mon Laferte, ComposerLyricist")


class TestCreditsFor:
    def test_a_featured_guest_is_found_by_name(self):
        found = credits_for([("a force", ANANTA)], "aja monet")
        assert len(found) == 1
        assert found[0].track == "a force"
        assert "FeaturedArtist" in found[0].roles

    def test_the_name_is_matched_through_core_names(self):
        """The watchlist spells her "aja monet"; Qobuz spells her "Aja Monet"."""
        assert credits_for([("a force", ANANTA)], "AJA   MONET")

    def test_somebody_not_on_the_record_gets_nothing(self):
        assert credits_for([("a force", ANANTA)], "Jorge Drexler") == []

    def test_roles_from_several_tracks_stay_separate(self):
        found = credits_for([("one", ANANTA), ("two", ANANTA)], "aja monet")
        assert [c.track for c in found] == ["one", "two"]

    def test_a_track_with_no_performers_string_is_skipped(self):
        assert credits_for([("one", ""), ("two", ANANTA)], "aja monet") == [
            Credit(track="two", roles=("FeaturedArtist", "SpokenWord",
                                       "ComposerLyricist"))]

    def test_repeated_roles_are_folded_but_ordered(self):
        doubled = "Aja Monet, FeaturedArtist, FeaturedArtist, SpokenWord"
        assert credits_for([("x", doubled)], "aja monet")[0].roles == (
            "FeaturedArtist", "SpokenWord")


class TestRoleClass:
    def test_a_feature_is_both_billed_and_a_performance(self):
        credit = credits_for([("a force", ANANTA)], "aja monet")[0]
        assert credit.billed
        assert credit.performance

    def test_a_songwriter_credit_is_neither(self):
        credit = credits_for([("Culpables", COVER)], "Mon Laferte")[0]
        assert not credit.billed
        assert not credit.performance

    def test_a_session_player_performs_without_being_billed(self):
        """Yussef Dayes on Daley's *Strange Nature* is a real find, and `Drums`
        is in no allowlist anybody would write -- hence the denylist."""
        credit = Credit(track="Consequences", roles=("Drums",))
        assert credit.performance
        assert not credit.billed

    def test_an_unknown_instrument_still_counts_as_performing(self):
        """65 of 124 role tokens in the Drexler corpus are in no table, and
        nearly all are genuine. An allowlist would discard them."""
        assert Credit(track="x", roles=("Berimbau",)).performance
        assert Credit(track="x", roles=("Spanish Guitar",)).performance

    def test_a_producer_is_not_performing(self):
        assert not Credit(track="x", roles=("Producer",)).performance

    def test_one_performance_role_among_writer_roles_is_enough(self):
        credit = Credit(track="x", roles=("ComposerLyricist", "Vocals"))
        assert credit.performance


class TestIsRetrospective:
    def test_titles_that_mean_old_recordings_new_delivery(self):
        for title in ["Manuel Turizo: Lo Mejor de MT",
                      "Rise Up! Hamilton: The Anthology",
                      "Camilo: El Setlist 2026",
                      "Planet Hemp - As Melhores",
                      "El Porvenir Remixes",
                      "BABY GANGSTA - From THE FIRST TAKE",
                      "Exploding In Slow Motion: The Complete Recordings"]:
            assert is_retrospective(title), title

    def test_a_long_album_is_just_a_long_album(self):
        """The first cut used `>= 15 tracks` and threw away three genuine guest
        spots. Nothing here looks at the track count at all."""
        for title in ["Papela Funk", "Chrysalis", "MudaH",
                      "Ananta: Spirit Of Coltrane"]:
            assert not is_retrospective(title), title

    def test_case_does_not_matter(self):
        assert is_retrospective("LO MEJOR DE")

    def test_a_live_album_is_not_assumed_to_be_old(self):
        """"En Vivo" is deliberately not a pattern: a live record can be new
        material, and D42's live covers were writer-only and already gone."""
        assert not is_retrospective("Desde El Rancho (En Vivo)")

    def test_no_title_is_not_a_retrospective(self):
        assert not is_retrospective("")


class TestVerdict:
    def test_a_feature_on_a_new_record_is_news(self):
        credited = credits_for([("a force", ANANTA)], "aja monet")
        assert verdict("Ananta: Spirit Of Coltrane", credited) == "appearance"

    def test_a_name_the_index_matched_but_the_credits_do_not(self):
        """Qobuz's track index matched "Ajá John Arias" for "aja monet"."""
        assert verdict("Culpables", []) == "absent"

    def test_a_cover_is_a_writer_credit(self):
        credited = credits_for([("Culpables", COVER)], "Mon Laferte")
        assert verdict("Culpables", credited) == "writer"

    def test_a_real_performance_on_a_repackage(self):
        credited = credits_for([("Tattoo", "Camilo, MainArtist - "
                                           "Rauw Alejandro, MainArtist")],
                               "Rauw Alejandro")
        assert verdict("Camilo: El Setlist 2026", credited) == "retrospective"

    def test_a_cover_on_a_compilation_counts_as_the_cover_it_is(self):
        """`writer` is checked before `retrospective` so the funnel attributes
        it to the reason that actually disqualifies it."""
        credited = credits_for([("Culpables", COVER)], "Mon Laferte")
        assert verdict("Lo Mejor de Alguien", credited) == "writer"


class TestAppearanceKey:
    def test_the_same_record_under_two_ids_folds(self):
        """*Ananta* and Napa's *Semitropico* each came back twice under
        different Qobuz ids, and would have printed twice."""
        assert (appearance_key("Miguel Atwood-Ferguson", "Ananta: Spirit Of Coltrane")
                == appearance_key("Miguel Atwood-Ferguson", "Ananta: Spirit of Coltrane"))

    def test_two_different_records_do_not_fold(self):
        assert appearance_key("Sean Shibe", "The Winch") != \
               appearance_key("Sean Shibe", "The Abider")

    def test_the_same_title_by_different_artists_does_not_fold(self):
        assert appearance_key("Napa", "Semitrópico") != \
               appearance_key("Someone Else", "Semitrópico")


class TestIsCompilation:
    def test_various_artists_is_a_compilation(self):
        from core.appearances import is_compilation
        assert is_compilation("Various Artists")
        assert is_compilation("various artists")

    def test_a_named_artist_is_not(self):
        from core.appearances import is_compilation
        assert not is_compilation("Miguel Atwood-Ferguson")
        assert not is_compilation("")


class TestVerdictOnContainers:
    def test_a_real_credit_on_a_various_artists_record_is_a_compilation(self):
        """91 of 142 performance credits in D42. The credit is genuine -- they
        are billed MainArtist on their own track -- so no role rule sees it."""
        credited = credits_for([("Fusion", "Jorge Drexler, MainArtist")],
                               "Jorge Drexler")
        assert verdict("Canciones para recordar", credited,
                       "Various Artists") == "compilation"

    def test_the_same_credit_on_a_named_record_is_news(self):
        credited = credits_for([("Fusion", "Jorge Drexler, MainArtist")],
                               "Jorge Drexler")
        assert verdict("Someone's Album", credited, "Someone") == "appearance"

    def test_a_cover_on_a_compilation_is_still_the_cover(self):
        credited = credits_for([("Culpables", COVER)], "Mon Laferte")
        assert verdict("Whatever", credited, "Various Artists") == "writer"

    def test_no_album_artist_given_falls_back_to_the_title_rules(self):
        credited = credits_for([("a force", ANANTA)], "aja monet")
        assert verdict("Ananta", credited) == "appearance"
