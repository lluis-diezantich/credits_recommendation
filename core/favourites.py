"""Your own top artists, in one list, with one id per source.

Not to be confused with data/watchlist.json, which is the COLLABORATOR list the
credits pipeline builds -- people found by reading who made records. This is the
other direction: the artists you actually play, resolved to whichever id each
radar speaks, because the three radars live in three unrelated namespaces and
used to each hardcode their own dict.

    {"generated": "...", "artists": [
      {"name": "Jorge Drexler",
       "mbid": "abb91078-...",   # radars/listenbrainz.py
       "qobuz_id": 41620,        # radars/qobuz.py
       "itunes_id": null,        # radars/itunes.py -- hand-filled, nothing resolves these
       "plays": 6447,
       "rank": 1,                # best rank in any window, for sorting
       "ranks": {"all_time": 1, "this_week": 4}}]}   # which kind of favourite

A null id means "not resolved", not "no such artist", so a radar skips that row
rather than guessing. Hand-edit an id in and the next resolve run keeps it.
`"watch": false` mutes an artist without deleting the entry -- the same
convention stages/resolve_qobuz.py uses for people.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from core.paths import DATA

FILE = DATA / "favourites.json"


def load(path: Path = FILE) -> list[dict]:
    """Every entry in the favourites file, or [] when there is no file yet."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        # Same stance as core/state.py: a bad file degrades to the radar's own
        # fallback list rather than stopping the run.
        print(f"warning: ignoring unreadable {path.name} ({error})", file=sys.stderr)
        return []
    return data.get("artists") or []


def save(artists: list[dict], generated: str, path: Path = FILE) -> None:
    path.write_text(
        json.dumps({"generated": generated, "artists": artists}, indent=2, ensure_ascii=False)
        + "\n"
    )


def ids_for(key: str, fallback: dict, path: Path = FILE) -> dict:
    """{id: name} for one source's id field, or `fallback` if it has none.

    The fallback is each radar's original hardcoded dict. It matters because
    resolving only Qobuz ids must not quietly empty the other two radars: a
    file full of `"itunes_id": null` means "nobody resolved these", so the
    iTunes radar keeps watching what it was watching before.
    """
    entries = load(path)
    found = {
        entry[key]: entry["name"]
        for entry in entries
        if entry.get(key) and entry.get("watch", True)
    }
    if not found:
        # Silent when there is no file at all -- that is just today's behaviour.
        # Loud when a file exists but carries no id for this source, because
        # then "watching 1 artist" is a surprise worth explaining.
        if entries:
            print(f"note: {path.name} has no {key} for any artist; "
                  f"using this radar's built-in list instead", file=sys.stderr)
        return fallback
    return found
