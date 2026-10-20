"""Parsing the Qobuz per-track `performers` string. One copy, in core/.

This was written twice: `parse_performers()` in stages/discover.py and
`credits_by_person()` in stages/writing.py, which is how core/names.py came to
exist in the first place ("normalise in three files under two spellings"). The
second copy was the more careful one, and the drift showed: discover.py scored
collaborator names as instrument credits for as long as both existed.

It belongs in core/ rather than policy.py because there is no judgement here.
Splitting "Name, Role - Name, Role" is mechanical; what a role is WORTH is the
contestable part, and that stays in policy.py. For the same reason this module
imports neither policy nor core.names: it returns the raw strings Qobuz sent,
and the caller decides how to fold them.

    parse_performers("Jorge Drexler, MainArtist, Vocal - Ana Prada, Voices")
    -> [("Jorge Drexler", ["MainArtist", "Vocal"]), ("Ana Prada", ["Voices"])]
"""
from __future__ import annotations


def parse_performers(credits: str) -> list[tuple[str, list[str]]]:
    """"Name, Role1, Role2 - Name, Role1" -> [(name, [roles])].

    Qobuz also emits a COLLABORATION form, where several artists share one role
    and are packed into a single segment ahead of it:

        Jorge Drexler, Rueda de Candombe, AssociatedPerformer
        Jorge Drexler, Angeles Toledano, Julio Cobelli, AssociatedPerformer

    Taking parts[1:] as roles turns "Rueda de Candombe" into a role, and nothing
    downstream rejects it: policy.role_weight() has no entry, so it silently
    returns INSTRUMENT_WEIGHT (0.8) -- the very silent-fallback failure that
    policy.py was written to end -- while role_class() files it under
    "performance", handing a writer a performance class they never earned.

    An allowlist is not the fix. 65 of the 124 role tokens in the Drexler corpus
    appear in no table in policy.py, and nearly all are genuine: Spanish Guitar,
    Timpani, Berimbau, Wurlitzer, Theremin, MusicPublisher, A&R. Instruments are
    open-ended, so a strict vocabulary would discard real credits to catch a
    dozen bad ones.

    The test is positive evidence instead: a token is a co-artist only if it
    ALSO heads a segment of its own in the SAME string. Instruments never do.
    And because it heads its own segment it is already credited there, with a
    fuller role list ("Rueda de Candombe, MainArtist, AssociatedPerformer"), so
    it is dropped here rather than re-emitted -- re-emitting would double-count
    its tracks and add nothing.

    Catches 9 of the ~13 packed segments in that corpus. The rest ("Angeles
    Toledano", "Ruben Blades", "Americo Young") appear ONLY in a role slot, so
    the string holds no evidence to catch them with; guessing from
    capitalisation would put every instrument at risk, a worse trade.

    Removing those tokens changed 0 rows of discovery_41620.json: every packed
    segment in the corpus has the seed in the name slot, and discover.py drops
    the seed as not their own collaborator.
    """
    segments = [[part.strip() for part in segment.split(",") if part.strip()]
                for segment in credits.split(" - ")]
    heads = {parts[0] for parts in segments if parts}
    people = []
    for parts in segments:
        if not parts:
            continue
        roles = [token for token in parts[1:]
                 if not (token in heads and token != parts[0])]
        people.append((parts[0], roles))
    return people


# Qobuz's spelling of the billing credit, lowercased. The one role token this
# module knows by name, because "who is this record BY" is a question about the
# string's shape rather than about what a credit is worth.
MAIN_ARTIST = "mainartist"


def main_artists(credits: str) -> list[str]:
    """The names billed MainArtist in one performers string, in order.

        main_artists("Jorge Drexler, MainArtist, Vocal - Ana Prada, Voices")
        -> ["Jorge Drexler"]

    Mechanical, like parse_performers, and for the same reason: it reports who
    Qobuz says holds the role and rules on nothing. Whether an album that bills
    the seed somewhere is the seed's OWN record is a judgement about how much
    of the album they hold -- policy.album_provenance -- because Qobuz files a
    guest spot inside the guest's discography, so "the seed is billed here" and
    "the seed made this" are different questions.
    """
    return [name for name, roles in parse_performers(credits)
            if any(role.lower() == MAIN_ARTIST for role in roles)]
