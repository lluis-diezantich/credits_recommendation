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

`"ended"` is a FACT from MusicBrainz, not a decision, and that is why it is a
separate field from `watch`. A mute is yours and you can lift it; an artist who
died or a band that split will not release again whatever you think about it.
Both skip the artist, and keeping them apart is what lets `--check-active`
refresh one without touching the other.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
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


# Written into the file itself, because this one is meant to be read and
# hand-edited: the mute knob is invisible until something flips it.
NOTE = ('hand-edits are kept: set "watch": false to stop watching an artist '
        '(or run stages/favourites.py --mute "Name"), and a qobuz_id you fix '
        'by hand is never re-resolved.')


def save(artists: list[dict], generated: str, path: Path = FILE) -> None:
    path.write_text(
        json.dumps({"generated": generated, "note": NOTE, "artists": artists},
                   indent=2, ensure_ascii=False)
        + "\n"
    )


#: Every verdict watch_verdict can return. "watched" first, because the rest
#: are the exclusions and report.py lists them in this order.
WATCH_REASONS = ("watched", "muted", "ended", "unresolved")


def watch_verdict(entry: dict, key: str) -> str:
    """Why one artist is or is not watched: watched, muted, ended or unresolved.

    Pure, and lifted out of the comprehension it used to live inside, because
    this is the actual judgement about who a radar looks at -- the same reason
    core/radar.py's verdict() is its own function rather than an `if` in the
    loop. It also makes the exclusions countable, which is what lets an issue
    say 15 artists were muted instead of silently watching 26 fewer.

    The order is load-bearing, and it is "whose decision was this" rather than
    cheapest-test-first:

    - A mute wins, because it is yours. An artist you muted must not also turn
      up in the unresolved count and send you to --review for an id you are
      never going to use.
    - `ended` comes next for the same reason one step weaker: it is a FACT
      from MusicBrainz, and a dead artist needs no id either.
    - So `unresolved` counts only artists you still want and could still
      watch. That is the number worth acting on, and the point of separating
      these at all.
    """
    if not entry.get("watch", True):
        return "muted"
    if entry.get("ended"):
        return "ended"
    if not entry.get(key):
        return "unresolved"
    return "watched"


@dataclass(frozen=True)
class Watchlist:
    """Who a radar will look at, who it will not, and why not.

    `ids` is the only part a radar needs to run; the rest exists so the report
    can account for the difference between the file and the run. Without it the
    issue says "146 of 146 artists" and the 26 it dropped are invisible -- the
    only way to find a mute was to read the JSON.
    """

    #: {id: name}, deduplicated, which is what the radar watches.
    ids: dict
    #: {reason: entries}, over WATCH_REASONS. Entries, not ids.
    counts: dict
    #: Watched entries that share an id with another, so collapse into one.
    #: Two spellings of one artist, usually.
    collapsed: int = 0
    #: True when the file carried no id for this source and `ids` is the
    #: radar's built-in fallback, so the counts describe a list nobody used.
    fallback: bool = False

    @property
    def excluded(self) -> int:
        return sum(n for reason, n in self.counts.items() if reason != "watched")

    def report(self) -> dict:
        """The JSON shape radars/report.py renders, flat and all-zeros-included.

        `entries` and `ids` are both here because they differ and the
        difference is not obvious: 148 watched entries can be 146 artists.
        """
        return {"entries": sum(self.counts.values()), "ids": len(self.ids),
                "collapsed": self.collapsed, **self.counts}


def watchlist(key: str, fallback: dict, path: Path = FILE) -> Watchlist:
    """Read the file once and decide every entry, keeping the reasons.

    ids_for() is this with the reasons thrown away, and is still what the
    radars call to get something to iterate.
    """
    entries = load(path)
    counts = dict.fromkeys(WATCH_REASONS, 0)
    found: dict = {}
    for entry in entries:
        reason = watch_verdict(entry, key)
        counts[reason] += 1
        if reason == "watched":
            # Last spelling wins, as the comprehension this replaced did.
            found[entry[key]] = entry["name"]
    if not found:
        # Silent when there is no file at all -- that is just today's behaviour.
        # Loud when a file exists but carries no id for this source, because
        # then "watching 1 artist" is a surprise worth explaining.
        if entries:
            print(f"note: {path.name} has no {key} for any artist; "
                  f"using this radar's built-in list instead", file=sys.stderr)
        return Watchlist(ids=fallback, counts=counts, fallback=True)
    return Watchlist(ids=found, counts=counts,
                     collapsed=counts["watched"] - len(found))


def ids_for(key: str, fallback: dict, path: Path = FILE) -> dict:
    """{id: name} for one source's id field, or `fallback` if it has none.

    The fallback is each radar's original hardcoded dict. It matters because
    resolving only Qobuz ids must not quietly empty the other two radars: a
    file full of `"itunes_id": null` means "nobody resolved these", so the
    iTunes radar keeps watching what it was watching before.
    """
    return watchlist(key, fallback, path).ids


def mbid_for(qobuz_id: int, path: Path = FILE) -> str | None:
    """The MusicBrainz id of a watched artist, by Qobuz id. None if unknown.

    This file already carries an mbid per artist from the ListenBrainz ranking
    that produced it, which is what lets a stage ask MusicBrainz about a seed
    without resolving a name first. None rather than raising: a seed that is
    not on the watchlist is a normal case.
    """
    for entry in load(path):
        if entry.get("qobuz_id") == qobuz_id and entry.get("mbid"):
            return str(entry["mbid"])
    return None
