"""MusicBrainz, for the one fact no listening history can contain: has an
artist stopped?

A play count says how much you liked someone. It cannot say whether they are
dead, or whether the band split -- and the release dates cannot either, because
a dead artist keeps putting out compilations and remasters. MusicBrainz states
it outright in `life-span.ended`, and says which it was:

    Celia Cruz      Person  ended  2003-07-16   died
    Extremoduro     Group   ended  2019-12-17   split
    Jorge Drexler   Person  active

The project's first DIRECT MusicBrainz call. MBIDs already arrive through
ListenBrainz's mbid_mapping; this asks MusicBrainz itself.

Two things it needs that other clients here do not:

    1 request per second, strictly. The published limit, and a burst earns a
      503 rather than a 429.
    A User-Agent naming the application AND a contact. The generic one this
      project uses elsewhere gets 503 on the first call.

Cached per artist and effectively forever: a death date does not change, and a
band that split stays split. --refresh re-asks.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from core.http import get
from core.paths import CACHE

CACHE_DIR = CACHE / "musicbrainz"
# `inc=aliases` rather than a second endpoint: the aliases arrive on the
# request this module already makes, so the names an artist is credited under
# cost nothing beyond what --check-active already spends. Cached entries
# written before this are refetched on demand -- `ended()` reads life-span,
# which is in both shapes.
ARTIST_URL = ("https://musicbrainz.org/ws/2/artist/{mbid}"
              "?inc=aliases+artist-rels&fmt=json")

# Named application plus a contact URL, as MusicBrainz asks. Not decoration:
# "dormancy-check/1.0 (personal use)" was refused with a 503.
USER_AGENT = ("credits-recommendation/0.1 "
              "( https://github.com/lluis-diezantich/credits_recommendation )")

# The published limit is one request a second. A little over, because the clock
# that matters is theirs, not ours.
PAUSE = 1.2


def cache_path(mbid: str, directory: Path | None = None) -> Path:
    return (directory or CACHE_DIR) / f"{mbid}.json"


def artist(mbid: str, refresh: bool = False,
           directory: Path | None = None) -> dict | None:
    """One artist from MusicBrainz, cached. None when it cannot be read.

    None rather than an exception, and never an empty dict: "MusicBrainz does
    not know" and "MusicBrainz says active" must stay distinguishable, or a
    failed lookup silently reads as a living artist.
    """
    path = cache_path(mbid, directory)
    if path.exists() and not refresh:
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass            # a corrupt cache entry is refetched, not fatal
    status, body, _ = get(ARTIST_URL.format(mbid=mbid), user_agent=USER_AGENT,
                          service="MusicBrainz", fatal=False)
    time.sleep(PAUSE)
    if status != 200:
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n")
    return data


def ended(entity: dict | None) -> tuple[bool, str | None]:
    """(has it ended, when) from an artist document.

    `ended` is the authority, not the presence of an end date: MusicBrainz sets
    the flag for a group that split on an unknown date, so a date-only test
    would read it as active.
    """
    if not entity:
        return False, None
    span = entity.get("life-span") or {}
    return bool(span.get("ended")), span.get("end")


def why(entity: dict | None) -> str:
    """"died", "split" or "" -- the distinction is worth keeping in a report."""
    stopped, _ = ended(entity)
    if not stopped:
        return ""
    return "died" if entity and entity.get("type") == "Person" else "split"


def names(entity: dict | None) -> list[str]:
    """Every name MusicBrainz knows this artist by, primary name first.

    The answer to "is this credit the artist themselves or a collaborator",
    which nothing else on disk can give. Qobuz credits a record to whichever
    name the label filed -- "Bjork Gudmundsdottir" on 120 of Bjork's own
    albums, "Simbiatu Ajikawo" on 20 of Little Simz's -- and both read as the
    seed's biggest collaborator until something knows they are the seed.

    Measured first and rejected: the share of the seed's catalogue (Bjork's
    legal name holds 81%, but Little Simz's holds 45% against a real
    producer's 42%, which is no gap at all) and whether the credit holds
    MainArtist (neither legal name does -- both are filed as Composer).
    So this is asked rather than inferred, the same stance as `ended()`.

    Three sources, all on the one request: the aliases, and the artists on the
    other end of an `is person` relationship, which is where MusicBrainz files
    a legal name that is not an alias -- Little Simz has no alias for
    "Simbiatu Ajikawo" and is related to it as a person.

    What this does NOT return is a name nobody recorded. Two further spellings
    of that one ("Simbiatu Abisola Abiola Ajikawo", "Simbi Ajikawo") are in no
    MusicBrainz field, so 9 of her 29 self-credited albums survive it. The
    caller reports the residue rather than fuzzy-matching it -- `find_artist`
    refuses fuzzy matches for the same reason.
    """
    if not entity:
        return []
    found = [entity.get("name"), entity.get("sort-name")]
    found += [alias.get("name") for alias in entity.get("aliases") or []]
    for relation in entity.get("relations") or []:
        if relation.get("type") == "is person":
            other = relation.get("artist") or {}
            found += [other.get("name"), other.get("sort-name")]
    seen: dict[str, None] = {}
    for name in found:
        if name:
            seen.setdefault(name, None)
    return list(seen)
