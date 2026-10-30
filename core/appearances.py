"""Is a credit on somebody ELSE's record news? Pure, offline, and the whole
judgement behind the second half of the Qobuz radar.

The radar's first pass walks a watched artist's own discography, which is what
Qobuz files under them. A feature does not land there: `a force` on Miguel
Atwood-Ferguson's *Ananta* credits aja monet as `FeaturedArtist, SpokenWord`
and never appears in her `artist/get` page at all. The second pass finds those
by searching the track index for her NAME, which drags in everything that
merely looks like her name, so three decisions stand between a search hit and
a printed row. They are here, as functions, rather than wedged into the fetch
loop -- same reason `core.radar.verdict` is (D2).

The order those decisions are applied is the funnel D42 measured, so
`verdict()` returns them as named outcomes and the caller counts them.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.credits import parse_performers
from core.names import normalise

#: Roles that are not performing on the record. A DENYLIST, not an allowlist of
#: instruments, and that direction is the lesson `core/credits.py` already
#: learned the hard way: 65 of the 124 role tokens in the Drexler corpus appear
#: in no table, and nearly all are genuine (Spanish Guitar, Berimbau, Theremin,
#: Wurlitzer). An allowlist discards real credits to catch a dozen bad ones.
#:
#: This set is the entire reason the second pass is usable. Every karaoke,
#: piano and cumbia version of "Tu Falta de Querer" credits Mon Laferte as
#: `ComposerLyricist` and nothing else; so does every cover. D42 measured 96 of
#: 238 credited hits as writer-only, and that is what this removes.
WRITER_ROLES = frozenset({
    "composer", "composerlyricist", "lyricist", "writer", "songwriter",
    "author", "producer", "executiveproducer", "coproducer", "arranger",
    "recordingarranger", "programmer", "engineer", "mixingengineer",
    "masteringengineer", "recordingengineer", "additionalengineer",
    "recordingsecondengineer", "assistantengineer", "musicpublisher",
    "publisher", "a&r", "sampledartist", "remixer", "re-mixer",
})

#: The spellings that mean "this record is billed as featuring them". Kept
#: apart from the rest so the report can say WHY a row is there: a billing is
#: a collaboration, a `Drums` credit is session work, and the two are worth
#: different attention even though both are performances.
BILLED_ROLES = frozenset({
    "mainartist", "featuredartist", "featuredvocals", "featuredvocalist",
    "leadvocalist", "vocalist", "vocals", "withvocals", "spokenword",
    "rapvocalist",
})

#: Titles that mean "old recordings, new delivery". Measured against D42's 45
#: albums: these eleven patterns catch the 16 repackages without touching a
#: real release.
#:
#: Deliberately NOT a track-count rule. The first cut of this used `>= 15
#: tracks` and threw away three genuine guest spots on genuine albums --
#: Califato 3/4 on Space Surimi's *Papela Funk* (20 tr), Kishi Bashi on
#: Emancipator's *Chrysalis* (16 tr), Rawayana on Carin Leon's *MudaH* (19 tr).
#: A long album is just a long album.
#:
#: "En Vivo" is deliberately absent too. A live album can be new material, and
#: the live covers D42 turned up were all writer-only and already gone by the
#: time this runs.
RETROSPECTIVE_PATTERNS = (
    "lo mejor", "best of", "greatest hits", "grandes exitos", "grandes éxitos",
    "as melhores", "anthology", "the complete", "setlist",
    "remixes", "from the first take",
)

#: How Qobuz bills a record with no single artist. A `Various Artists` album is
#: a compilation by construction, and it was the largest surviving category in
#: D42 by a long way: 91 of 142 performance credits. They are real credits --
#: the watched artist IS billed MainArtist on their own track -- which is why
#: no role rule touches them and why this is a separate test.
#:
#: Checked on `album/get`'s `artist` and not its `artists`, because on a
#: compilation `artists` comes back EMPTY and the name is only in the singular
#: field. Reading the wrong one makes every compilation look like a record by
#: whoever was being searched for, which is how `Canciones para recordar` (32
#: tracks, Various Artists) first printed as a Jorge Drexler album.
COMPILATION_ARTIST = "various artists"


@dataclass(frozen=True)
class Credit:
    """One watched artist's credit on one track of somebody else's record."""

    track: str
    roles: tuple[str, ...]

    @property
    def billed(self) -> bool:
        """Billed as an artist on it, rather than playing on it."""
        return any(normalise(role) in BILLED_ROLES for role in self.roles)

    @property
    def performance(self) -> bool:
        """Performing at all, as opposed to having written or produced it."""
        return any(normalise(role) not in WRITER_ROLES for role in self.roles)

    def describe(self) -> str:
        """The roles, as the report prints them. Ordered as Qobuz sent them."""
        return ", ".join(self.roles)


def credits_for(tracks: list[tuple[str, str]], name: str) -> list[Credit]:
    """Every credit one person holds across an album's tracks.

    `tracks` is [(title, performers)], which is what `album/get` returns per
    track -- the same call that establishes the album's real date, so this
    costs no extra request.

    Matching is on the normalised name, through `core.names`, because one
    performers string spells the same artist two ways and the watchlist spells
    it a third ("aja monet" against Qobuz's "Aja Monet").
    """
    wanted = normalise(name)
    found = []
    for title, performers in tracks:
        roles: list[str] = []
        for person, person_roles in parse_performers(performers or ""):
            if normalise(person) == wanted:
                roles += person_roles
        if roles:
            found.append(Credit(track=title, roles=tuple(dict.fromkeys(roles))))
    return found


def is_retrospective(title: str) -> bool:
    """Does the title say "old recordings, new delivery"?

    Substring, case-folded, and nothing cleverer. `Disc 2` and `Flavorz Pack`
    are also repackages and are NOT here: the first is a disc of a set that
    may itself be new, and the second is one label's word for a remix bundle.
    Both were in D42's sample and both are left to be re-measured rather than
    guessed at from one week.
    """
    low = (title or "").lower()
    return any(pattern in low for pattern in RETROSPECTIVE_PATTERNS)


def is_compilation(album_artist: str) -> bool:
    """Is this a record with no single artist behind it?"""
    return normalise(album_artist) == normalise(COMPILATION_ARTIST)


def verdict(album_title: str, credits: list[Credit], album_artist: str = "") -> str:
    """Why a search hit is or is not an appearance worth printing.

        absent          the name never appears in the credits -- a search
                        false positive. Qobuz's track index matched "Ajá John
                        Arias" for "aja monet" on two records.
        writer          credited, but only as composer/lyricist/producer. This
                        is every cover of their songs, and it is the biggest
                        single category (96 of 238 in D42).
        compilation     billed Various Artists. A real credit on a record that
                        is a container, not a release.
        retrospective   really performing, on a repackage of old recordings.
        appearance      news.

    Pure, and the order is the funnel: each outcome is the reason the row
    stopped, so counting them gives back D42's table rather than one number.
    `absent` first because it is not a judgement about music at all; `writer`
    before the two container tests because a cover ON a compilation should
    count as the cover it is; and `compilation` before `retrospective` because
    "Various Artists" is a fact about the record where the title patterns are a
    guess about it.
    """
    if not credits:
        return "absent"
    if not any(credit.performance for credit in credits):
        return "writer"
    if is_compilation(album_artist):
        return "compilation"
    if is_retrospective(album_title):
        return "retrospective"
    return "appearance"


def appearance_key(album_artist: str, album_title: str) -> str:
    """What makes two rows the same release, for dedup.

    NOT the album id. Qobuz carries the same record under several ids per
    storefront -- D42 hit this on *Ananta: Spirit Of Coltrane* and on Napa's
    *Semitropico*, each of which came back twice under different ids and would
    have printed twice. `core.radar` dedups on id and cannot see this, so the
    second pass folds on artist and title before handing rows over.
    """
    return f"{normalise(album_artist)}|{normalise(album_title)}"
