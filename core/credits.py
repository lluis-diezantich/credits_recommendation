"""Parsing the Qobuz per-track `performers` string. One copy, in core/.

This was written twice: `parse_performers()` in stages/discover.py and
`credits_by_person()` in stages/writing.py, which is how core/names.py came to
exist in the first place ("normalise in three files under two spellings"). The
second copy was the more careful one, and the drift showed: discover.py scored
collaborator names as instrument credits for as long as both existed.

It belongs in core/ rather than policy.py because there is no judgement here.
Splitting "Name, Role - Name, Role" is mechanical; what a role is WORTH is the
contestable part, and that stays in policy.py. It imports no policy, and what
it RETURNS is still the raw strings Qobuz sent, for the caller to fold -- but it
folds names internally now, with core.names, because one string spells the same
artist two ways and the comparison below has to see through that.

    parse_performers("Jorge Drexler, MainArtist, Vocal - Ana Prada, Voices")
    -> [("Jorge Drexler", ["MainArtist", "Vocal"]), ("Ana Prada", ["Voices"])]
"""
from __future__ import annotations

from core.names import normalise


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

    TWO WAYS THAT TEST USED TO MISS, both found 2026-10-22 in the three seeds
    walked after it was written, and both fixed by `names_a_co_artist`:

        Conrad Taylor, ..., Re-Mixer - Rosalia, MainArtist, ... -
        Conrad Taylor, ROSALÍA, Björk & Yves Tumor, AssociatedPerformer

      - ONE STRING, TWO SPELLINGS. "ROSALÍA" is a head of this very string,
        as "Rosalia". An exact comparison does not see it, so an artist's name
        became a role and reached the printed explanation: "credited on 1
        track (re-mixer, rosalía, björk & yves tumor)", which is exactly what
        D21 promised an explanation would never say.
      - NAMES JOINED WITH "&". "Björk & Yves Tumor" is two heads in one token
        and is no head at all, so each side is tested on its own.

    This also catches the three the docstring used to call uncatchable --
    "Angeles Toledano", "Ruben Blades", "Americo Young". They were never
    role-slot-only; they head segments of their own, spelled with the accents
    the role slot drops.

    Measured over all of cache/credits and cache/search: 18 distinct tokens,
    29 occurrences, and every one of them is an artist name. No instrument,
    no genuine role. The allowlist objection above is why that mattered enough
    to measure rather than assume.
    """
    segments = [[part.strip() for part in segment.split(",") if part.strip()]
                for segment in credits.split(" - ")]
    folded = {normalise(parts[0]) for parts in segments if parts}
    people = []
    for parts in segments:
        if not parts:
            continue
        roles = [token for token in parts[1:]
                 if not names_a_co_artist(token, parts[0], folded)]
        people.append((parts[0], roles))
    return people


def names_a_co_artist(token: str, head: str, folded: set[str]) -> bool:
    """Is this role-slot token actually somebody's name?

    `folded` is every segment head in the same string, normalised. A token is
    a name when it matches one of them, or when it is several of them joined
    with "&" -- and never when it matches its OWN head, which is a string
    repeating itself rather than naming a collaborator.
    """
    key = normalise(token)
    if not key or key == normalise(head):
        return False
    if key in folded:
        return True
    pieces = [normalise(piece) for piece in token.split("&")]
    return len(pieces) > 1 and all(piece in folded for piece in pieces)


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
