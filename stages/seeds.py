#!/usr/bin/env python3
"""Which artist to walk next, and why -- the input to discover.py.

The first four seeds were picked by hand, and two of them intersect with
nothing: Little Simz and Björk share no co-artist with each other or with the
Iberian pair, so "how many of your artists made a record with this person" is 1
for 97 of 99 rows and a cross-seed ranker has nothing to rank. A seed costs ~50
requests and ten minutes of reading its alias report, so this picks them by
rule instead -- `policy.seedable`, with the measurement behind both numbers.

    ./stages/seeds.py                    # the pool, in walk order
    ./stages/seeds.py --next 8           # the next eight, with their commands
    ./stages/seeds.py --all              # include the ones the rule rejects
    ./stages/seeds.py --json

Reads data/profile.json (the bands and the month counts), data/favourites.json
(the Qobuz id and the mbid a walk needs) and data/music.db (who is already a
co-artist, which decides the ORDER). Offline, no requests.

WHY THE ORDER IS NOT THE RULE. The rule says who is worth 50 requests; the
order says which 50 to spend first. An artist already seen as a co-artist of a
walked seed is a guaranteed intersection, so walking those first puts range
into the ranker's main column after two or three walks instead of after eight.
It is deliberately not part of `seedable` -- that would make the corpus grow
only along links it already knows, which is the opposite of discovery.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys

from core.names import normalise
from core.paths import DATA
from policy import SEED_PLAYS_FLOOR, SEED_RECENT_FLOOR, seedable

# Everyone already in the store as a co-appearance somebody holds. A seed drawn
# from here will intersect the existing graph by construction.
CO_ARTISTS = """
SELECT DISTINCT person_key FROM co_artists
WHERE seed_records + their_records > 0
"""


def walkable(path=None) -> dict[str, dict]:
    """Artist key -> the ids a walk needs, from favourites.json.

    Both ids, not either: `discover.py` needs the Qobuz id to read the
    discography and the mbid to know which names the seed is credited under
    (D23). Without the second the walk still runs and reports the seed as its
    own biggest collaborator, so an artist missing one is not a candidate.
    """
    blob = json.loads((path or DATA / "favourites.json").read_text())
    entries = blob.get("artists") if isinstance(blob, dict) else blob
    return {normalise(e["name"]): e for e in entries or []
            if e.get("name") and e.get("qobuz_id") and e.get("mbid")}


def reason(artist: dict, ids: dict | None) -> str:
    """Why this artist is not a candidate, in the words of the test it failed.

    Three branches for `seedable`'s two tests, and no branch for the band:
    "lapsed" means a long history with a recent count under `policy`'s m24
    floor of 10, which is below SEED_RECENT_FLOOR, so the month test has
    already answered and a band branch here would be unreachable.
    """
    if ids is None:
        return "no qobuz id or no mbid in favourites.json"
    if artist["recent"] < SEED_RECENT_FLOOR:
        return f"{artist['recent']} recent months, floor is {SEED_RECENT_FLOOR}"
    return f"{artist['plays']} plays on a short history, floor is {SEED_PLAYS_FLOOR}"


def candidates(profile: dict, ids: dict[str, dict], walked: set[int],
               co_artists: set[str]) -> tuple[list[dict], list[dict]]:
    """(candidates in walk order, the rejected with their reason).

    Walk order is intersections first, then recent months, then plays -- see
    the module docstring for why that is separate from the rule.
    """
    kept, dropped = [], []
    for artist in profile.get("artists") or []:
        key = normalise(artist["name"])
        entry = ids.get(key)
        if entry is None or not seedable(artist["band"], artist["recent"],
                                         artist["plays"]):
            dropped.append({**artist, "key": key, "why": reason(artist, entry)})
            continue
        row = {**artist, "key": key, "qobuz_id": entry["qobuz_id"],
               "mbid": entry.get("mbid"),
               "walked": entry["qobuz_id"] in walked,
               "intersects": key in co_artists}
        kept.append(row)
    kept.sort(key=lambda r: (r["walked"], not r["intersects"],
                             -r["recent"], -r["plays"]))
    return kept, dropped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(DATA / "music.db"))
    parser.add_argument("--next", type=int, metavar="N",
                        help="print the commands for the next N unwalked seeds")
    parser.add_argument("--all", action="store_true",
                        help="also list the artists the rule rejects, with why")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        profile = json.loads((DATA / "profile.json").read_text())
        ids = walkable()
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{exc} - run ./stages/profile.py first") from exc

    walked: set[int] = set()
    co_artists: set[str] = set()
    try:
        con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        walked = {r[0] for r in con.execute("SELECT seed_qobuz_id FROM seeds")}
        co_artists = {r[0] for r in con.execute(CO_ARTISTS)}
    except sqlite3.OperationalError:
        # No store yet is not an error here: the rule does not need it, and
        # only the ORDER degrades -- to recent months, which is the fallback
        # the hand-picking used.
        print(f"warning: no readable store at {args.db}, so no seed is known "
              "to intersect and the order falls back to recent months",
              file=sys.stderr)

    kept, dropped = candidates(profile, ids, walked, co_artists)
    fresh = [r for r in kept if not r["walked"]]

    if args.json:
        print(json.dumps({"candidates": kept, "rejected": dropped},
                         indent=2, ensure_ascii=False))
        return 0

    if args.next:
        count = min(args.next, len(fresh))
        print(f"# the next {count} seeds, ~50 requests each, "
              f"~{count * 50} in total\n")
        for row in fresh[:args.next]:
            note = "intersects the graph already" if row["intersects"] else "new cluster"
            print(f"./stages/discover.py --artist {row['qobuz_id']:<8} "
                  f"# {row['name']} - {note}")
        print("\n# then read each one's alias report and add to "
              "data/aliases.json before ranking (D25)")
        return 0

    print(f"{len(kept)} artists pass the rule, {len(kept) - len(fresh)} already walked")
    print(f"{len(fresh)} to go, {sum(1 for r in fresh if r['intersects'])} of them "
          "already a co-artist of a walked seed\n")
    for row in kept:
        flag = ("walked" if row["walked"]
                else "INTERSECTS" if row["intersects"] else "")
        print(f"  {row['qobuz_id']:>8}  {row['name'][:28]:<28} {row['band']:<9} "
              f"{row['recent']:>2}/24 months  {row['plays']:>5} plays  {flag}")

    if args.all:
        print(f"\n{len(dropped)} rejected:")
        for row in sorted(dropped, key=lambda r: (-r["recent"], -r["plays"])):
            print(f"            {row['name'][:28]:<28} {row['band']:<9} "
                  f"{row['recent']:>2}/24 months  {row['why']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
