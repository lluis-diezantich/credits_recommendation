"""Is a release on a label you follow news? Pure, offline, and the whole
judgement behind the label radar.

The other three radars start from a PERSON and ask the store what they
released. That works because Qobuz files a release under its billed artists,
and it is why `core/appearances.py` had to search the track index instead the
moment the question became "what are they credited on" (D42).

A producer has neither. Qobuz files nothing under them, and the track index
does not reliably carry their credit -- measured 2026-10-31 over six producers
with producer-only credits, where the index returned 4 of 4, 2 of 2, 0 of 2, 5
of 6, 2 of 3 and 0 of 2 of the albums known to credit them. `Aidan Cullen` is
the clean case: 54 index rows, so nothing was truncated, and the album
`album/get` credits him `Producer` on is simply absent.

So this radar runs the loop the other way round. A LABEL is something Qobuz
does index, completely and newest-first, so the catalogue narrows the store to
a few hundred releases a week and the CREDITS decide which of them to print.
That split is the whole design: the label is the query, the credit is the
judgement, and the judgement is here rather than wedged into the fetch loop --
same reason `core.radar.verdict` and `core.appearances.verdict` are (D2).

Not a second copy of core/appearances.py, though the two answer neighbouring
questions. That module asks "is a credit on somebody else's record worth
printing", starting from a watched artist and DENYING the roles that are not
performances. This one starts from a label nobody you watch is billed on, and
KEEPS one family of roles: the producers and mixers your artists use. A denylist
cannot be inverted into an allowlist -- 65 of 124 role tokens in the Drexler
corpus are in no table at all (core/credits.py) -- so the two sets are written
separately and only the role_key folding is shared.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from core.appearances import is_retrospective
from core.credits import parse_performers
from core.names import normalise
from core.paths import DATA

LABELS_FILE = DATA / "labels.json"
PEOPLE_FILE = DATA / "producers.json"


def role_key(role: str) -> str:
    """Fold spelling variants: 'Co- Producer' and 'MixingEngineer' both match.

    Cherry-picked from `policy.role_key` on the `ranking` branch, which is the
    one function from that file this needs and carries no threshold with it.

    It is also the fix for a bug `data/appearances-backfill.md` records against
    `core/appearances.py`: that module spells its denylist CamelCase and
    compares through `normalise()`, which does not collapse spaces, so
    `Sampled Artist` and `Beat maker` miss the list and printed as genuine
    appearances. Every role token here goes through this instead, so
    `Executive Producer`, `ExecutiveProducer` and `executive  producer` are one
    key.
    """
    return "".join(ch for ch in role.lower() if ch.isalnum())


#: Role families, by `role_key`. The `production` slice is lifted from
#: `policy.ROLE_CLASS` on `ranking` and the rest is here to make the funnel
#: explain itself: a producer you follow credited as `Composer` on a label
#: release is a COVER of a song they wrote, not a record they made, and the
#: radar has to be able to say which it threw away.
#:
#: `engineering` is deliberately its own family rather than folded into
#: production, because that fold is a measured defect of the archived pipeline:
#: 73% of its referrals arrived through MIXING rather than production (5,347
#: mixed-by against 1,678 producer), and an industrial masterer -- Fred
#: Kevorkian, 1,070 records -- links everything to everything. `--credit`
#: decides whether to count it; the default is production alone.
ROLE_FAMILY: dict[str, str] = {
    **{r: "production" for r in (
        "producer", "coproducer", "production", "executiveproducer",
        "producedby", "additionalproduction", "vocalproducer")},
    **{r: "engineering" for r in (
        "engineer", "recordingengineer", "mixedby", "mixer", "mixingengineer",
        "assistantengineer", "asstrecordingengineer", "masteredby",
        "masteringengineer", "masterer", "studiopersonnel", "programmer",
        "programming", "additionalprogramming")},
    **{r: "writing" for r in (
        "composer", "lyricist", "composerlyricist", "writtenby", "adapter",
        "author", "writer", "songwriter", "arranger", "instrumentarranger",
        "vocalarranger", "musicpublisher", "publisher", "sampledartist")},
    **{r: "billing" for r in (
        "mainartist", "main", "featuredartist", "associatedperformer",
        "performer", "performance", "artist")},
}

#: Everything else is an instrument, which is what the remainder genuinely is:
#: see `core/credits.py` for why an allowlist of instruments was measured and
#: rejected.
DEFAULT_FAMILY = "performance"

FAMILIES = ("production", "engineering", "writing", "billing", "performance")


def family_of(role: str) -> str:
    """Which family one role token belongs to."""
    return ROLE_FAMILY.get(role_key(role), DEFAULT_FAMILY)


@dataclass(frozen=True)
class Credit:
    """One person's credits across one label release, folded over its tracks."""

    name: str
    roles: tuple[str, ...]
    tracks: int

    def families(self) -> set[str]:
        return {family_of(role) for role in self.roles}

    def describe(self) -> str:
        """The roles, as the report prints them. Ordered as Qobuz sent them."""
        return ", ".join(self.roles)


def credits_by(tracks: list[tuple[str, str]], wanted: dict[str, str]) -> list[Credit]:
    """Every credit held on this release by anybody in `wanted`.

    `tracks` is [(title, performers)] from `album/get` -- the same call that
    establishes the release's real date, so the credits cost no extra request.

    `wanted` is {normalised name: name as you spell it}, because the printed
    row should say the name you know the person by rather than whichever
    spelling this particular record used. Folded through `core.names` for the
    reason that module exists: one performers string spells the same person two
    ways.

    Ordered by track count, most first, so a caller naming ONE person on a
    record that credits three names the one who did the most work on it.
    """
    held: dict[str, list[str]] = {}
    counted: dict[str, set[str]] = {}
    for title, performers in tracks:
        for person, roles in parse_performers(performers or ""):
            key = wanted.get(normalise(person))
            if key is None or not roles:
                continue
            # Keyed on the name YOU spell, not the one this record used. Both
            # spellings of one person reach here on the same release -- Qobuz
            # credits `Carles Campi Campón` on one track and `Carles Campón` on
            # the next -- and keying on the record's spelling made that two
            # rows, each with half the roles and half the track count.
            held.setdefault(key, []).extend(roles)
            # A set, because one track can credit the same person twice: the
            # two spellings above both appear on the opening track of
            # `Universos paralelos`, and counting occurrences said 2 tracks of
            # a 1-track single.
            counted.setdefault(key, set()).add(title)
    found = [Credit(name=name, roles=tuple(dict.fromkeys(roles)),
                    tracks=len(counted[name]))
             for name, roles in held.items()]
    return sorted(found, key=lambda c: (-c.tracks, c.name))


#: Where a catalogue stops being a label and starts being a distributor. Above
#: this, a label says nothing about a record: measured 2026-10-31 over the 60
#: labels your watchlist released on in a year, where 7 labels with catalogues
#: over 2,000 produced 245 of the 340 candidates in a fortnight -- Sony Music
#: Entertainment alone 128, from a catalogue Qobuz reports as 10,000.
#:
#: A threshold, not a blocklist of names, because the names are not the point
#: and would need maintaining: `WM Spain`, `Universal Music Latino` and
#: `BMG Rights Management (US) LLC` all behave like Sony here and none of them
#: look like it in the file.
MAJOR_CATALOGUE = 2000

#: Below this, a "label" is usually one artist's own releases -- `Jose Gonzalez`
#: (12), `Chuwi, LLC` (7), `Rosalia` (3), `ALERTA TROMBÓN, SL` (6) are all in
#: the measured 60. Watching them is watching an artist you already watch, so
#: they cost a request to tell you what the Friday radar has already said.
#:
#: Expressed as "how many of YOUR artists released on it", not as catalogue
#: size: `Napa` has 11 releases and is a real label with one artist on your
#: list, while `Brainfeeder` has 257 and two. The test that separates those is
#: the same one, and it is deliberately permissive -- 1 is allowed, and what it
#: rejects is the self-release where the label name IS the artist name.
MIN_YOUR_ARTISTS = 1


def watch_verdict(entry: dict) -> str:
    """Why one label is or is not scanned: watched, muted, major or self.

        muted    `"watch": false` in the file. Yours, and you can lift it.
        major    catalogue over MAJOR_CATALOGUE. A fact about the catalogue.
        self     the label name is one of your artists' names -- a self-release
                 or an artist-owned imprint, which the artist radar covers.
        watched  scanned.

    Pure and lifted out of the comprehension it used to live in, for the same
    reason `core.favourites.watch_verdict` is: this is the actual judgement
    about where the radar looks, and a mute is yours while a catalogue size is
    a fact, so the two must stay separately readable.
    """
    if entry.get("watch") is False:
        return "muted"
    if (entry.get("catalogue") or 0) > MAJOR_CATALOGUE:
        return "major"
    if entry.get("self_release"):
        return "self"
    if len(entry.get("artists") or []) < MIN_YOUR_ARTISTS:
        return "thin"
    return "watched"


def fold_editions(albums: list[dict]) -> list[dict]:
    """One row per release, not per edition, keeping the earliest of each.

    Cherry-picked from `stages/discover.py` on the `ranking` branch, where it
    was measured against Björk's discography: 141 album ids for 99 titles. A
    label catalogue has the same shape for the same reason -- `data/retro-90d.md`
    shows *Before The World Blows* twice, hi-res and not -- and here it saves a
    REQUEST per duplicate rather than a double-counted credit, because the fold
    happens before `album/get` is spent on the candidate.

    Folded on normalise(title), which is the only key two editions share: there
    is no release-group id in what Qobuz returns. Coarse on purpose, and the
    known cost is that a genuine reissue with a different track list folds into
    the original.
    """
    folded: dict[str, dict] = {}
    for album in sorted(albums, key=lambda a: (a.get("release_date_original") or "")[:10]):
        folded.setdefault(normalise(album.get("title") or ""), album)
    return list(folded.values())


#: Repackage markers NOT in `core.appearances.RETROSPECTIVE_PATTERNS`. Kept
#: apart because that tuple was measured against D42's sample and the Qobuz
#: radar's funnel rests on it. Found by the first run here: *La Quiniela del
#: Día (Remastered 2026)*, which `album_detail`'s date cannot catch because the
#: remaster genuinely is new.
REMASTER_PATTERNS = ("remaster", "remasterizado", "anniversary edition",
                     "deluxe edition", "reissue", "edicion especial",
                     "edición especial")


def is_reissue(title: str) -> bool:
    """Does the title say "old recordings, new delivery"?

    Both lists, because `core.appearances.is_retrospective` already holds the
    eleven patterns D42 measured and there is no reason to spell them twice.
    """
    low = (title or "").lower()
    return is_retrospective(title) or any(p in low for p in REMASTER_PATTERNS)


#: Titles that mean "somebody else's finished record, reworked". D30 decided
#: this on `ranking` and decided it on ROLES -- a `Re-Mixer`-only credit, which
#: `ROLE_FAMILY` already drops. This is the other shape: a real `Producer`
#: credit on a release that is itself a rework.
#:
#: Measured 2026-10-31 over three corpora of release titles: 8 of the Friday
#: radar's 238 in 90 days, 1 of this radar's 33, 0 of D42's 43. `edit`,
#: `version` and `dub` are left out -- a salsa version is a re-recording, and
#: three titles cannot say which way those should go.
REMIX_PATTERNS = ("remix", "rmx", "re-mix")


def is_remix(title: str) -> bool:
    """Is this release a rework of a finished record rather than a new one?"""
    low = (title or "").lower()
    return any(pattern in low for pattern in REMIX_PATTERNS)


#: Why a label release is or is not news, in the order a candidate meets the
#: tests. `yours` first because it is not a judgement about credits at all, and
#: `absent` before the family tests for the same reason.
VERDICTS = ("credit", "absent", "yours", "writing", "sideline", "reissue",
            "remix")


def earned(credits: list[Credit], families: set[str]) -> Credit | None:
    """The credit that makes this release news: who to NAME in the report.

    Not `credits[0]`. That is whoever worked on the most tracks, and the first
    full run printed three rows against the wrong person because of it -- *Día
    de Muertos* was kept for somebody's `Producer` credit and attributed to
    Cachorro López, `Music Director`, who had more tracks. The same shape as
    `core.appearances`' billed-credit preference, and for the same reason: the
    row has to say the thing that put it there.
    """
    wanted = [credit for credit in credits if credit.families() & families]
    return wanted[0] if wanted else None


def verdict(album_artist_ids: set[str], watched_ids: set[str],
            credits: list[Credit], families: set[str],
            title: str = "") -> str:
    """Why a release on a watched label is or is not worth printing.

        yours      billed to an artist you already watch. The Friday radar's
                   first pass has it, and reporting it here would print the
                   same record under two sources.
        absent     nobody you follow is in the credits. This is most of a label
                   catalogue and it is the expected outcome, not a failure.
        writing    credited, but only as composer/lyricist/publisher -- a cover
                   of something they wrote, or a sample cleared. The biggest
                   false-positive category in D42 at 96 of 238.
        sideline   credited in a family you did not ask for. With the default
                   `--credit production` this is the mixing and mastering work
                   that the archived pipeline measured as 73% of its referrals.
        reissue    really produced by them, on a repackage of old recordings.
        remix      really produced by them, on a rework of a finished record.
                   Both last, because they are guesses about the record where
                   every test above them is a fact about the credits.
        credit     news.

    `families` is what the run counts as news, so the caller decides whether
    engineering is a sideline or the point without this function growing a
    flag. Pure, and the order IS the funnel: each outcome is the reason a row
    stopped, so counting them gives back a table rather than one number.
    """
    if album_artist_ids & watched_ids:
        return "yours"
    if not credits:
        return "absent"
    held = set().union(*(credit.families() for credit in credits))
    if held & families:
        if is_reissue(title):
            return "reissue"
        return "remix" if is_remix(title) else "credit"
    if held <= {"writing"}:
        return "writing"
    return "sideline"


#: Names that are not a person. Qobuz ships these in the credit slot and they
#: are the most dangerous rows in the file, because they match on records that
#: have nothing to do with anybody: `Not Documented` holds 7 credits across 5
#: of the watched artists and `Unknown` holds 10 across 3, so either one would
#: report a release whenever a label left its credits blank.
#:
#: Exact names after `normalise`, not a pattern. A first cut used a regex and
#: matched `Navarro` and `Molina` on `n/?a\b` -- a loose pattern here throws
#: away real producers, which is the same lesson `core/credits.py` records
#: about allowlisting roles.
PLACEHOLDER_NAMES = frozenset({
    "not documented", "unknown", "unknown artist", "various", "various artists",
    "traditional", "n/a", "na", "not applicable", "no artist", "anonymous",
    "public domain", "composer", "producer",
})

#: Shorter than this and a "name" is a fragment rather than a person. The file
#: holds `Jr`, `KJ` and `JD`, which are a suffix and two sets of initials that
#: came off a split name, and a two-character credit matches far too much.
MIN_NAME_LENGTH = 3

#: Records somebody must be credited on before this looks for their new work.
#: 723 of 1,538 people held exactly one when measured 2026-10-31, and those
#: rows are the weakest in the report. One credit does not establish that an
#: artist chose to work with somebody.
#:
#: COUNTED ACROSS EVERY CREDITED FAMILY. Counting production alone was tried
#: and the 90-day backfill measured it down: it dropped Marta Salogni (9
#: credits, 0 as Producer -- she MIXES for these artists) and Neal Pogue (10,
#: 0), and with them the two best rows. The list asks "is this person crew",
#: where a mixing credit is evidence; `verdict` asks "did they produce THIS
#: record", per release.
MIN_PERSON_RECORDS = 2

#: Every verdict `person_verdict` can return, "watched" first.
PERSON_REASONS = ("watched", "muted", "junk", "yourself", "thin")


def person_verdict(entry: dict, yours: frozenset[str] = frozenset()) -> str:
    """Why one person is or is not looked for: watched, muted, junk, yourself, thin.

        muted      `"watch": false` in the file. Yours, and you can lift it.
        junk       a placeholder or a name fragment, not a person.
        yourself   an artist you already watch, producing their own record.
                   Rosalía, C. Tangana and Kaytranada all hold `Producer` on
                   their own releases, and the Friday radar has those.
        thin       fewer than MIN_PERSON_RECORDS production credits.
        watched    looked for.

    Same split as `core.favourites.watch_verdict`: the mute is yours and comes
    first, and everything after it is a fact about the entry.
    """
    if entry.get("watch") is False:
        return "muted"
    name = (entry.get("name") or "").strip()
    if normalise(name) in PLACEHOLDER_NAMES or len(name) < MIN_NAME_LENGTH:
        return "junk"
    if yours and {normalise(n) for n in [name, *(entry.get("names") or [])]} & yours:
        return "yourself"
    # `albums`, which counts every credited family. `production` is recorded
    # beside it and deliberately NOT read here -- see MIN_PERSON_RECORDS for
    # the backfill that measured that difference.
    if (entry.get("albums") or 0) < MIN_PERSON_RECORDS:
        return "thin"
    return "watched"


@dataclass
class People:
    """Who to look for, and who was left out of the file and why."""

    names: dict[str, str]
    excluded: dict[str, int]
    #: {name as you spell it: the artists of YOURS they have worked for}. The
    #: reason a row lands: "James Ford - Producer" is a stranger, and "James
    #: Ford, who produces Björk" is a recommendation. Straight from the `for`
    #: field the discovery files fill in, so it names the artists this person
    #: was actually found through rather than anything inferred.
    worked_for: dict[str, list[str]] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.kept) + sum(self.excluded.values())

    @property
    def kept(self) -> set[str]:
        """The distinct people kept, as opposed to the spellings they go by."""
        return set(self.names.values())

    def report(self) -> dict:
        return {"kept": len(self.kept), "entries": self.total, **self.excluded}


def _read(path: Path, key: str) -> list[dict]:
    """Entries from one hand-edited JSON file, or [] when there is no file yet.

    Same stance as `core.favourites.load` and `core.state`: a file that cannot
    be read degrades to an empty watchlist, which the radar turns into its own
    "nothing to watch" message, rather than a traceback halfway through a run.
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        print(f"warning: ignoring unreadable {path.name} ({error})", file=sys.stderr)
        return []
    if isinstance(data, dict):
        return data.get(key) or []
    return data or []


@dataclass
class Watchlist:
    """The labels to scan, and what was left out of the scan and why."""

    ids: dict[int, str]
    excluded: dict[str, int]

    @property
    def total(self) -> int:
        return len(self.ids) + sum(self.excluded.values())

    def report(self) -> dict:
        """The counts, in the shape `radars/report.py` already reads.

        `ids` and `entries` rather than anything label-specific, because
        `watchlist_line` is written against those two keys for every radar and
        a second spelling would mean a second formatter.
        """
        return {"ids": len(self.ids), "entries": self.total, **self.excluded}


def labels(path: Path = LABELS_FILE) -> Watchlist:
    """{label id: name} to scan, with the exclusions counted by reason."""
    keep: dict[int, str] = {}
    left: dict[str, int] = {}
    for entry in _read(path, "labels"):
        if not entry.get("id"):
            continue
        reason = watch_verdict(entry)
        if reason == "watched":
            keep[int(entry["id"])] = entry.get("name") or str(entry["id"])
        else:
            left[reason] = left.get(reason, 0) + 1
    return Watchlist(ids=keep, excluded=left)


def people(path: Path = PEOPLE_FILE,
           yours: frozenset[str] = frozenset()) -> People:
    """Who to look for, with the exclusions counted by reason.

    `names` maps every spelling a person was credited under to the ONE name the
    report should print, which is what lets `credits_by` fold two spellings on
    one record onto a single row.

    `yours` is the normalised names of the artists you already watch, passed in
    rather than read here so this stays a function of its arguments -- the
    radar knows the watchlist, and a hidden read of it would make the same file
    answer two different questions.
    """
    wanted: dict[str, str] = {}
    left: dict[str, int] = {}
    worked_for: dict[str, list[str]] = {}
    for entry in _read(path, "people"):
        name = entry.get("name")
        if not name:
            continue
        reason = person_verdict(entry, yours)
        if reason != "watched":
            left[reason] = left.get(reason, 0) + 1
            continue
        for spelling in [name, *(entry.get("names") or [])]:
            wanted.setdefault(normalise(spelling), name)
        worked_for[name] = list(entry.get("for") or [])
    return People(names=wanted, excluded=left, worked_for=worked_for)
