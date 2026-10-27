#!/usr/bin/env python3
"""How many releases Discogs holds for each candidate -- the ubiquity input.

`policy.selectivity()` has existed since the pool was built and has never had
an input: 0 of 592 co-artists carry `discogs_total_releases`, because the only
stage that ever filled it (`resolve_discogs.py`) runs on the people Qobuz
CANNOT see, and a co-artist is by definition someone Qobuz can.

The defect that costs: `breadth` ranks on how many of your artists a person
turns up with, and a singer who guests on everybody's record turns up with
three of them for the same reason they turn up with everybody. Six reggaeton
features led the list on 2026-10-24 for exactly that reason, above Yomo Toro
at 23 records with Willie Colon and Hector Lavoe.

    ./stages/ubiquity.py --limit 40      # a sample, to measure the match rate
    ./stages/ubiquity.py                 # all of them
    ./stages/ubiquity.py --refresh       # ignore the cache

Two requests per person -- a search for the id, then page 1 of their releases
for `pagination.items` -- so the full run is ~1,200 requests at 25/min
anonymous, 60/min with DISCOGS_TOKEN. Both are cached in cache/discogs/, so
the second run of anything costs nothing.

WHY THE SAMPLE COMES FIRST. `find_discogs_artist` is exact-match-only by
design, and a person it cannot find has no ubiquity number. If a third of them
come back unmatched then a penalty applied to the other two thirds REWARDS the
ones it could not find, which is worse than having no penalty at all. The
match rate decides whether a penalty is written, so it is measured before the
requests are spent -- and what to do about the misses is a `policy.py`
decision that cannot be made without the number.

Writes data/ubiquity.json. Does not touch the store: `load.py` reads this file
in, so the number arrives the same way every other derived fact does.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import sqlite3
import sys
from contextlib import closing

from core.discogs import Throttle, find_discogs_artist, total_releases
from core.names import strip_discogs_suffix
from core.paths import DATA
from stages.rank import candidates

FILE = "ubiquity.json"

# Every spelling the credits used for one person, so the exact match has more
# than one chance. D25's person key already folded the aliases; this undoes
# the fold for the SEARCH only, because Discogs files under its own spelling.
SPELLINGS = """
SELECT person_key, name FROM co_artists
WHERE seed_records + their_records > 0
GROUP BY person_key, name
"""

# The sample must be the same 40 people on a rerun, or the match rate it
# reports cannot be compared with the one before it.
SAMPLE_SEED = 0


def spellings(con: sqlite3.Connection) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in con.execute(SPELLINGS):
        out.setdefault(row["person_key"], []).append(row["name"])
    return out


def targets(con: sqlite3.Connection, limit: int | None) -> list[dict]:
    """The people to ask about: the same population `rank.py` ranks.

    Reused rather than requeried, so a person the filters drop is a person we
    do not pay Discogs for -- a remixer, a channel and an illustrator are not
    candidates (D24, D27, D30, D35) and their ubiquity is nobody's question.

    Not filtered to unheard, unlike the default ranked view: how prolific
    somebody is does not depend on whether you have played them, and the
    number is wanted for `--all` too.
    """
    rows = candidates(con, dt.date.today())
    rows.sort(key=lambda r: r["person_key"])
    if limit is not None and limit < len(rows):
        rows = random.Random(SAMPLE_SEED).sample(rows, limit)
        rows.sort(key=lambda r: r["person_key"])
    return rows


def ask(row: dict, names: list[str], throttle: Throttle, token: str | None,
        refresh: bool) -> dict:
    """One person: their Discogs id, and how many releases it holds."""
    artist, how = find_discogs_artist(names, throttle, token, refresh=refresh)
    if not artist:
        return {"person_key": row["person_key"], "name": row["name"],
                "match": how, "discogs_id": None, "total_releases": None}
    did = artist.get("id")
    total = total_releases(did, throttle, token, refresh=refresh) if did else None
    return {"person_key": row["person_key"], "name": row["name"],
            "match": how, "discogs_id": did,
            "discogs_name": strip_discogs_suffix(artist.get("title") or ""),
            "total_releases": total}


def summarise(people: list[dict]) -> dict:
    """The match rate and the spread, which is what the sample is for."""
    matched = [p for p in people if p["total_releases"] is not None]
    totals = sorted(p["total_releases"] for p in matched)
    reasons: dict[str, int] = {}
    for p in people:
        if p["total_releases"] is None:
            reasons[p["match"]] = reasons.get(p["match"], 0) + 1

    def at(fraction: float) -> int | None:
        """Nearest-rank, which needs no interpolation and cannot leave the list."""
        if not totals:
            return None
        return totals[min(int(fraction * (len(totals) - 1) + 0.5), len(totals) - 1)]

    by_match: dict[str, int] = {}
    for p in matched:
        by_match[p["match"]] = by_match.get(p["match"], 0) + 1

    return {
        "asked": len(people),
        "matched": len(matched),
        "match_rate": round(100 * len(matched) / max(len(people), 1), 1),
        "matched_by_kind": by_match,
        "unmatched_by_reason": reasons,
        "min": at(0.0),
        "median": at(0.5),
        "p90": at(0.9),
        "max": at(1.0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DATA / "music.db"))
    parser.add_argument("--limit", type=int, metavar="N",
                        help=f"a reproducible random sample of N (seed {SAMPLE_SEED})")
    parser.add_argument("--refresh", action="store_true",
                        help="ignore cache/discogs/ and refetch")
    parser.add_argument("--out", help=f"output path (default: data/{FILE})")
    parser.add_argument("--json", action="store_true",
                        help="the summary as JSON, for a measurement log")
    args = parser.parse_args()

    token = os.environ.get("DISCOGS_TOKEN") or None
    throttle = Throttle(60 if token else 25)
    print(f"discogs: {'token' if token else 'anonymous'} "
          f"({'60' if token else '25'} req/min)", file=sys.stderr)

    with closing(sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        try:
            rows = targets(con, args.limit)
        except sqlite3.OperationalError as exc:
            raise SystemExit(f"{args.db}: {exc} - run ./stages/load.py first") from exc
        names = spellings(con)

    print(f"{len(rows)} people, up to {2 * len(rows)} requests", file=sys.stderr)
    people = []
    for index, row in enumerate(rows, 1):
        key = row["person_key"]
        entry = ask(row, names.get(key) or [row["name"]], throttle, token,
                    args.refresh)
        people.append(entry)
        total = entry["total_releases"]
        print(f"  [{index}/{len(rows)}] {row['name'][:30]:<30} "
              f"{'-' if total is None else total:>6}  {entry['match']}",
              file=sys.stderr)

    stats = summarise(people)
    out = {"generated": dt.date.today().isoformat(),
           "sample": args.limit, "summary": stats, "people": people}
    path = DATA / FILE if not args.out else DATA.joinpath(args.out)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")

    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(f"\n{stats['matched']} of {stats['asked']} matched "
              f"({stats['match_rate']}%)")
        for reason, count in sorted(stats["unmatched_by_reason"].items()):
            print(f"  {count:>3} {reason}")
        print(f"releases: min {stats['min']}, median {stats['median']}, "
              f"p90 {stats['p90']}, max {stats['max']}")
    print(f"wrote {path.name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
