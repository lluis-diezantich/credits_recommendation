#!/usr/bin/env python3
"""The opponent: ListenBrainz's similar artists, beside the co-appearance list.

`roadmap.md` has asked from the start whether a credit graph carries signal a
listening-similarity model does not, and nothing in this repo answered it
because there was no second list. This builds that list from the free API
`radars/listenbrainz.py` already speaks to -- one request per seed, cached --
drops what you already play, and puts the two side by side.

    ./stages/baseline.py                     # the similar-artist list, unheard
    ./stages/baseline.py --compare           # overlap with the co-artist list
    ./stages/baseline.py --log               # record it, to be scored later
    ./stages/baseline.py --refresh           # ignore the cache

The comparison that settles anything is not in this output. It is
`./stages/rank.py --score`, which reads both sources out of the same
`data/shown.json` and reports a hit rate for each -- so `--log` here is the
point of the stage and the printed list is how you decide what to play.

The guess on record, from todo.md, written before the first number arrives:
similarity wins on hit rate, co-appearance wins on keepers you would never
have found, and the lists barely overlap.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
from contextlib import closing

from core import favourites, shown, similar
from core.names import normalise
from core.paths import DATA
from stages.rank import candidates as co_artist_candidates

SEEDS = "SELECT seed_qobuz_id, name FROM seeds ORDER BY name"


def already_played(con: sqlite3.Connection) -> tuple[set[str], set[str]]:
    """(artist keys you have played, mbids you have played).

    Both, because ListenBrainz answers in MBIDs and `listens` carries one only
    where its own mbid_mapping found one. Matching on the mbid is exact;
    matching on normalise(name) catches the rest and is the same key every
    other join in this project uses.
    """
    keys = {r[0] for r in con.execute(
        "SELECT DISTINCT artist_key FROM listens WHERE artist_key IS NOT NULL")}
    mbids = {r[0] for r in con.execute(
        "SELECT DISTINCT artist_mbid FROM listens "
        "WHERE artist_mbid IS NOT NULL AND artist_mbid != ''")}
    return keys, mbids


def gather(con: sqlite3.Connection, refresh: bool) -> tuple[list[dict], list[str]]:
    """(unheard similar artists across every seed, seeds that could not be read).

    Ordered by AFFINITY, not by the raw score. ListenBrainz returns a
    session co-occurrence COUNT, which scales with how much the seed is
    listened to globally rather than with how close the neighbour is, and the
    scales are not remotely comparable -- measured 2026-10-22 over the ten
    seeds:

        Bjork              top 6682, median 2076
        ROSALIA            top 1645, median  398
        Jorge Drexler      top  364, median   83
        Silvia Perez Cruz  top   24, median   12

    A factor of 278 between the first seed and the last. Merging on the raw
    maximum therefore ranked "artists ListenBrainz has a lot of data about"
    and called it similarity: Perez Cruz's best neighbour scored below Bjork's
    hundredth. So each seed's scores are divided by that seed's own top score,
    which puts every seed's first suggestion at 1.0 and keeps the shape of the
    distribution behind it -- a neighbour three times clear of the next one is
    a stronger claim than a flat run, and a rank would have thrown that away.

    Merged on the maximum affinity, and the seed COUNT is only a tie-break.
    That is deliberate restraint: ListenBrainz has no cross-seed notion, and
    rewarding breadth here would be designing the opponent rather than using
    it. The co-appearance list is the one making the breadth claim.
    """
    played_keys, played_mbids = already_played(con)
    best: dict[str, dict] = {}
    failed: list[str] = []

    for seed_id, seed_name in con.execute(SEEDS):
        mbid = favourites.mbid_for(seed_id)
        if not mbid:
            failed.append(f"{seed_name} (no mbid in favourites.json)")
            continue
        rows = similar.similar(mbid, refresh=refresh)
        if rows is None:
            failed.append(f"{seed_name} (request failed)")
            continue
        ceiling = max((row["score"] for row in rows), default=0) or 1
        for row in rows:
            key = normalise(row["name"])
            if key in played_keys or (row["mbid"] and row["mbid"] in played_mbids):
                continue
            if key == normalise(seed_name):
                continue                 # the seed suggested as its own neighbour
            entry = best.setdefault(key, {
                "person_key": key, "name": row["name"], "mbid": row["mbid"],
                "affinity": 0.0, "score": 0, "seeds": 0, "seed_names": []})
            affinity = row["score"] / ceiling
            if affinity > entry["affinity"]:
                # The raw score is kept beside it, but only as provenance: it
                # is the number ListenBrainz said, and it is not comparable
                # between seeds, which is the whole reason for the division.
                entry["affinity"] = affinity
                entry["score"] = row["score"]
            entry["seeds"] += 1
            entry["seed_names"].append(seed_name)

    out = sorted(best.values(),
                 key=lambda r: (-r["affinity"], -r["seeds"], r["person_key"]))
    for row in out:
        row["sort_key"] = (round(row["affinity"], 4),)
    return out, failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(DATA / "music.db"))
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--compare", action="store_true",
                        help="overlap with the co-appearance list")
    parser.add_argument("--log", action="store_true",
                        help=f"append what this run showed to data/{shown.FILE}")
    parser.add_argument("--refresh", action="store_true",
                        help="ignore the cache, one request per seed")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    with closing(sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        try:
            rows, failed = gather(con, args.refresh)
        except sqlite3.OperationalError as exc:
            raise SystemExit(
                f"{args.db}: {exc} - run ./stages/load.py first") from exc

        for note in failed:
            print(f"warning: no similar artists for {note}", file=sys.stderr)

        if args.compare:
            theirs = {r["person_key"]: r for r in co_artist_candidates(
                con, dt.date.today()) if not r["plays"]}
            mine = {r["person_key"] for r in rows}
            both = mine & set(theirs)
            print(f"similar-artist list: {len(rows)} unheard")
            print(f"co-appearance list:  {len(theirs)} unheard")
            print(f"in both:             {len(both)}"
                  f"  ({len(both) / max(len(mine | set(theirs)), 1):.1%} of the union)")
            if both:
                print("\nthe overlap:")
                for key in sorted(both):
                    print(f"  {theirs[key]['name']}")
            print("\nNeither number says which list is better. "
                  "./stages/rank.py --score does, once both are logged.")
            return 0

        if args.json:
            print(json.dumps(rows[:args.top], indent=2, ensure_ascii=False,
                             default=str))
        else:
            print(f"{len(rows)} unheard artists similar to your "
                  f"{len(set(s for r in rows for s in r['seed_names']))} seeds\n")
            for position, row in enumerate(rows[:args.top], 1):
                via = ", ".join(sorted(set(row["seed_names"])))
                print(f"{position:>3}. {row['name']}   "
                      f"[{row['affinity']:.2f} of {row['score']}]")
                print(f"     similar to {via}")

        if args.log:
            runs = shown.append(DATA, shown.entry(
                "similar", dt.date.today().isoformat(), rows, args.top))
            print(f"\nlogged run {runs} to data/{shown.FILE} - "
                  "./stages/rank.py --score reads it back", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
