"""Is a release on a label you follow news? Pure, offline, and the judgement
behind the label radar.

Qobuz files a release under the artists named on it, never under its producer,
and the track index does not carry production credits reliably -- measured over
six producers, where it returned 0 of 2 for one whose credit `album/get`
confirms. So the radar runs the loop the other way: a label IS indexed, so the
catalogue narrows the store and the credits decide. D44, D45.

Neighbour to `core/appearances.py`, which asks whether a credit on somebody
else's record is worth printing and DENIES the roles that are not performances.
This keeps one family instead -- the producers your artists use -- so the two
sets are written separately and only `role_key` is shared.
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
    """Fold spellings: 'Co- Producer' and 'CoProducer' are one key.

    Cherry-picked from `policy.role_key` on `ranking`. It is also the fix for
    the bug `data/appearances-backfill.md` records: `core/appearances.py`
    compares through `normalise()`, which keeps spaces, so `Sampled Artist`
    missed its denylist and printed.
    """
    return "".join(ch for ch in role.lower() if ch.isalnum())


#: Role families, by `role_key`. `engineering` is apart from `production`
#: because folding them is a measured defect of the archived pipeline: 73% of
#: its referrals came through mixing. `--credit` picks.
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

#: Everything else is an instrument: `core/credits.py` measured why an
#: allowlist of those was rejected.
DEFAULT_FAMILY = "performance"

FAMILIES = ("production", "engineering", "writing", "billing", "performance")


def family_of(role: str) -> str:
    """Which family one role token belongs to."""
    return ROLE_FAMILY.get(role_key(role), DEFAULT_FAMILY)


@dataclass(frozen=True)
class Credit:
    """One person's credits across one release, folded over its tracks."""

    name: str
    roles: tuple[str, ...]
    tracks: int

    def families(self) -> set[str]:
        return {family_of(role) for role in self.roles}

    def describe(self) -> str:
        """The roles, as the report prints them, in the order Qobuz sent."""
        return ", ".join(self.roles)


def credits_by(tracks: list[tuple[str, str]], wanted: dict[str, str]) -> list[Credit]:
    """Every credit on this release held by anybody in `wanted`.

    `tracks` is [(title, performers)] from `album/get`, the same call that
    establishes the real date, so the credits cost no extra request. `wanted`
    maps a normalised spelling to the name you use. Ordered by track count, so
    naming one person on a record that credits three names the right one.
    """
    held: dict[str, list[str]] = {}
    counted: dict[str, set[str]] = {}
    for title, performers in tracks:
        for person, roles in parse_performers(performers or ""):
            key = wanted.get(normalise(person))
            if key is None or not roles:
                continue
            # Keyed on the name YOU use: Qobuz credits `Carles Campi Campón`
            # on one track and `Carles Campón` on the next, and keying on the
            # record's spelling made that two rows with half the roles each.
            held.setdefault(key, []).extend(roles)
            # Titles, not occurrences: both spellings appear on one track, and
            # counting occurrences said 2 tracks of a 1-track single.
            counted.setdefault(key, set()).add(title)
    found = [Credit(name=name, roles=tuple(dict.fromkeys(roles)),
                    tracks=len(counted[name]))
             for name, roles in held.items()]
    return sorted(found, key=lambda c: (-c.tracks, c.name))


#: Where a catalogue stops being a label and starts being a distributor.
#: Measured over the 60 labels your watchlist used in a year: 7 with catalogues
#: over 2,000 produced 245 of 340 candidates in a fortnight, Sony alone 128. A
#: size rather than a list of names, because `WM Spain` and `Universal Music
#: Latino` behave the same way and look nothing like Sony in the file.
MAJOR_CATALOGUE = 2000

#: How many of your artists must use a label. Permissive: `Napa` has 11
#: releases and one of your artists and is a real label. It rejects the entry
#: with none.
MIN_YOUR_ARTISTS = 1


def watch_verdict(entry: dict) -> str:
    """Why one label is or is not scanned: watched, muted, major, self, thin.

    The mute is yours and comes first; everything after is a fact about the
    entry. Same split as `core.favourites.watch_verdict`.
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
    """One row per release, keeping the earliest edition of each.

    Cherry-picked from `stages/discover.py` on `ranking`, measured there
    against Björk's 141 album ids for 99 titles. Here it saves a REQUEST per
    duplicate, since it runs before `album/get`. Folded on normalise(title),
    the only key two editions share: a genuine reissue with a different track
    list folds into the original, which is the known cost.
    """
    folded: dict[str, dict] = {}
    for album in sorted(albums, key=lambda a: (a.get("release_date_original") or "")[:10]):
        folded.setdefault(normalise(album.get("title") or ""), album)
    return list(folded.values())


#: Repackage markers absent from `core.appearances.RETROSPECTIVE_PATTERNS`,
#: which was measured against D42's sample and carries the Qobuz radar's
#: funnel. Found by the first run here: *La Quiniela del Día (Remastered
#: 2026)*, where the delivery and the remaster share a date so `album_detail`
#: cannot catch it.
REMASTER_PATTERNS = ("remaster", "remasterizado", "anniversary edition",
                     "deluxe edition", "reissue", "edicion especial",
                     "edición especial")


def is_reissue(title: str) -> bool:
    """Old recordings, new delivery. Both lists, so neither is spelled twice."""
    low = (title or "").lower()
    return is_retrospective(title) or any(p in low for p in REMASTER_PATTERNS)


#: D30 decided a remix is not a collaboration using ROLES, which `ROLE_FAMILY`
#: already drops. This is the other shape: a real `Producer` credit on a
#: rework. Measured over three corpora of titles -- 8 of the Friday radar's 238
#: in 90 days, 1 of this radar's 33, 0 of D42's 43. `edit`, `version` and `dub`
#: are left out: a salsa version is a re-recording, and three titles cannot say
#: which way they go.
REMIX_PATTERNS = ("remix", "rmx", "re-mix")


def is_remix(title: str) -> bool:
    """Somebody else's finished record, reworked."""
    low = (title or "").lower()
    return any(pattern in low for pattern in REMIX_PATTERNS)


#: Verdicts that still describe a real new release, just not one anybody you
#: follow made. These are the feed (D45).
FEED_VERDICTS = frozenset({"absent", "writing", "sideline"})

#: Kinds the feed carries by default. Singles were 175 of 300 releases in the
#: measured fortnight: dropping them takes the feed from 128 a week to 62, and
#: the cap to 34. Credited rows ignore this, since the producer rows are mostly
#: singles -- Marta Salogni on Westerman's `L/C`.
FEED_KINDS = frozenset({"Album", "EP"})

#: Why a release is or is not news, in the order a candidate meets the tests.
VERDICTS = ("credit", "absent", "yours", "writing", "sideline", "reissue",
            "remix")


def earned(credits: list[Credit], families: set[str]) -> Credit | None:
    """The credit that makes this news: who to NAME in the report.

    Not `credits[0]`, which is whoever worked on the most tracks: the first run
    printed three rows against the wrong person, attributing *Día de Muertos*
    to its `Music Director`.
    """
    wanted = [credit for credit in credits if credit.families() & families]
    return wanted[0] if wanted else None


def verdict(album_artist_ids: set[str], watched_ids: set[str],
            credits: list[Credit], families: set[str],
            title: str = "") -> str:
    """Why a release on a watched label is or is not a credited row.

        yours      credited to an artist you watch, so the Friday radar has it
        absent     nobody you follow is on it. Most of a catalogue
        writing    composer or publisher only: a cover, or a sample cleared.
                   96 of 238 in D42
        sideline   a family this run did not ask for, which under
                   `--credit production` is the mixing and mastering work
        reissue    produced by them, on a repackage
        remix      produced by them, on a rework
        credit     news

    The order is the funnel, and each outcome is where a row stopped, so
    counting them gives a table rather than one number. Facts about the
    billing and the credits come before guesses from the title.
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


#: Names that are not a person. `Not Documented` holds credits across 15 of
#: these artists and `Unknown` across 11 -- what Qobuz ships when a label
#: leaves the slot blank, so either would report a release whenever that
#: happens. Exact names after `normalise`: a first regex matched `Navarro` and
#: `Molina`.
PLACEHOLDER_NAMES = frozenset({
    "not documented", "unknown", "unknown artist", "various", "various artists",
    "traditional", "n/a", "na", "not applicable", "no artist", "anonymous",
    "public domain", "composer", "producer",
})

#: Below this a name is a fragment: the file holds `Jr`, `KJ` and `JD`.
MIN_NAME_LENGTH = 3

#: Credits somebody needs before this looks for their new work. 723 of 1,538
#: people held exactly one.
#:
#: COUNTED ACROSS EVERY FAMILY. Counting production alone cut the list to 409
#: and dropped Marta Salogni (9 credits, 0 as `Producer` -- she mixes for these
#: artists) and Neal Pogue (10, 0), and with them the two best rows. The list
#: asks whether somebody is crew, where a mixing credit is evidence; `verdict`
#: asks whether they produced THIS record, per release.
MIN_PERSON_RECORDS = 2

PERSON_REASONS = ("watched", "muted", "junk", "yourself", "thin")


def person_verdict(entry: dict, yours: frozenset[str] = frozenset()) -> str:
    """Why one person is or is not looked for.

        muted      `"watch": false`. Yours, and first, so lifting it shows
        junk       a placeholder or a fragment
        yourself   an artist you watch, producing their own record. `verdict`'s
                   `yours` cannot catch them: it only sees the billing
        thin       fewer than MIN_PERSON_RECORDS credits
        watched    looked for
    """
    if entry.get("watch") is False:
        return "muted"
    name = (entry.get("name") or "").strip()
    if normalise(name) in PLACEHOLDER_NAMES or len(name) < MIN_NAME_LENGTH:
        return "junk"
    if yours and {normalise(n) for n in [name, *(entry.get("names") or [])]} & yours:
        return "yourself"
    # `albums`, every family. MIN_PERSON_RECORDS has the backfill.
    if (entry.get("albums") or 0) < MIN_PERSON_RECORDS:
        return "thin"
    return "watched"


@dataclass
class People:
    """Who to look for, and who the file lost and why."""

    names: dict[str, str]
    excluded: dict[str, int]
    #: {name: the artists of YOURS they have worked for}, from the `for` field
    #: the discovery files fill in. The reason a row lands: "James Ford -
    #: Producer" is a stranger, "works with Björk" is a recommendation.
    worked_for: dict[str, list[str]] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.kept) + sum(self.excluded.values())

    @property
    def kept(self) -> set[str]:
        """The people kept, as opposed to the spellings they go by."""
        return set(self.names.values())

    def report(self) -> dict:
        return {"kept": len(self.kept), "entries": self.total, **self.excluded}


def _read(path: Path, key: str) -> list[dict]:
    """Entries from one hand-edited file, or [] when it is missing or broken.

    Same stance as `core.favourites.load`: a bad file degrades to an empty
    watchlist and the radar's own message, rather than a traceback mid-run.
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
    """The labels to scan, and what the gate left out."""

    ids: dict[int, str]
    excluded: dict[str, int]

    @property
    def total(self) -> int:
        return len(self.ids) + sum(self.excluded.values())

    def report(self) -> dict:
        """`ids` and `entries`, the keys `radars/report.py` already reads."""
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

    `names` maps every spelling to the one name the report prints, which is how
    `credits_by` folds two spellings on one record. `yours` is passed in rather
    than read here, so this stays a function of its arguments.
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
