"""One person, one key -- when the only evidence is two spellings of a name.

`normalise` folds case, accents and whitespace, which merges a label's
typography and nothing else. It cannot merge a person filed under two different
names, and the credits are full of them:

    Sjon / Sigurjon Sigurdsson / Sigurjon Birgir Sigurdsson    a pen name
    Arca / Alejandro Ghersi                                    a stage name
    Inflo / Dean Josiah Cover                                  a production name
    Carles Campi Campon / Carles Campon / Campi                a shortening

The first three are the expensive ones: they split the people who matter most,
because a producer who is also a writer is credited one way for the production
and another way for the publishing. Bjork's graph had Sjon as four people at
ranks 4, 6, 8 and 68.

WHY A FILE AND NOT A LOOKUP. Resolving these needs a source that knows a
person's other names. MusicBrainz is that source and `core.musicbrainz.names`
already reads it -- but it needs an MBID, and of the top 12 people across the
four walked seeds, ONE has an MBID anywhere on disk. `listens.artist_mbid`
covers the artists you play, not the producers and composers who made their
records. So MusicBrainz here would mean a SEARCH by name, which is the fuzzy
match `core.qobuz.find_artist` refuses on principle, at a request per name.
docs/adr/D25 has the full comparison.

So this is a hand-edited file, the same stance `data/favourites.json` takes
where nothing can be derived, and `stages/discover.py` prints the pairs it did
NOT merge so the file is fed by evidence rather than by guessing.

The canonical name is always the PERFORMING name -- Sjon, not Sigurjon Birgir
Sigurdsson -- for two reasons: it is the key `listens.artist_key` carries, so
the 59% hit-rate measurement still joins, and it is the name a reader
recognises.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.names import normalise
from core.paths import DATA

FILE = "aliases.json"


def path(directory: Path | None = None) -> Path:
    return (directory or DATA) / FILE


def load(directory: Path | None = None) -> dict[str, str]:
    """alias key -> canonical key, for every name in the file.

    An absent or unreadable file is an empty map rather than an error: every
    count this project produces was computed without one until now, so the
    answer to a missing file is the old behaviour and not a stop.

    The canonical name maps to itself, so a caller can look up any spelling
    including the one it is keyed under.
    """
    file = path(directory)
    try:
        blob = json.loads(file.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    out: dict[str, str] = {}
    for person in blob.get("people") or []:
        canonical = normalise(person.get("name") or "")
        if not canonical:
            continue
        out[canonical] = canonical
        for other in person.get("also") or []:
            if normalise(other):
                out[normalise(other)] = canonical
    return out


def display_names(directory: Path | None = None) -> dict[str, str]:
    """canonical key -> the name as the file writes it.

    Without this a merged person is displayed under whichever spelling sorts
    first, so Sjon's 30 albums were printed under "Sigurjon Birgir
    Sigurdsson" and Arca's under "Alejandra Ghersi" -- the legal names, which
    is the opposite of the point. The file's `name` is the performing name by
    construction, so it is the one to show.
    """
    try:
        blob = json.loads(path(directory).read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return {normalise(person["name"]): person["name"]
            for person in blob.get("people") or [] if person.get("name")}


def canonical(key: str, aliases: dict[str, str] | None) -> str:
    """The one key this person's credits should accumulate under."""
    return (aliases or {}).get(key, key)


def person_key(name: str, aliases: dict[str, str] | None) -> str:
    """`normalise`, then the alias map. The only way to mint a person key.

    Takes the map rather than loading it, so this stays pure and a stage reads
    the file once per run instead of once per credit.
    """
    return canonical(normalise(name), aliases)
