#!/usr/bin/env python3
"""Who you actually still listen to, measured in months rather than plays.

Three jobs. Two write, one reads:

    ./stages/profile.py --seed              # once: compact the export zip
    ./stages/profile.py --month --user X    # monthly: 1 request, save the month
    ./stages/profile.py                     # anytime: print the table, no network

Plays were the wrong unit -- they scale with how much history you have, so a
threshold tuned today is wrong by two orders of magnitude on a fuller file.
Active months do not: they can only grow toward the months the export spans.

The two writers are slow or perishable, the reader is free, so the floors in
policy.py can be re-tuned as often as you like for nothing.

ONE GOTCHA: `range=month` only ever answers about the last 30 days, so a month
nobody fetched is gone. Re-download the export once a year and --seed again; it
backfills any hole and resolves names that had no mbid.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import sys
from pathlib import Path

import policy
from core import favourites, listens
from core.http import get as http_get
from core.paths import DATA, ROOT

STATS_URL = "https://api.listenbrainz.org/1/stats/user/{user}/artists"
USER_AGENT = "profile-builder/1.0 (personal use)"

# Same place load.py looks, but the LARGEST match rather than the last
# alphabetically -- listenbrainz_sample.zip sorts after the real export and
# would otherwise shadow it.
EXPORT_GLOB = str(ROOT.parent / "listenbrainz_*.zip")

BAND_ORDER = {"core": 0, "emerging": 1, "lapsed": 2, "thin": 3}


def verdict(row) -> str:
    """policy.band for one profile row, since every caller needs all three fields."""
    return policy.band(row.months, row.recent, row.recent_plays)


def shorten(path: Path) -> Path:
    """Repo-relative for reading, absolute when it is somewhere else entirely."""
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return path


def newest_export() -> Path | None:
    found = sorted(glob.glob(EXPORT_GLOB), key=lambda p: Path(p).stat().st_size)
    return Path(found[-1]) if found else None


def seed(path: Path, dry_run: bool) -> int:
    """Compact the export into one file per month. Reads 190k listens, writes ~159."""
    print(f"reading {path.name} ({path.stat().st_size / 1e6:.0f} MB)", file=sys.stderr)
    months = listens.read_export(path)
    if not months:
        print("no listens in that zip", file=sys.stderr)
        return 1
    plays = sum(row["plays"] for rows in months.values() for row in rows)
    print(f"{len(months)} months, {min(months)} -> {max(months)}, {plays} credited plays")
    if dry_run:
        return 0
    for month, rows in months.items():
        listens.write_month(month, rows, "export")
    print(f"wrote {len(months)} files to {shorten(listens.MONTHS)}/")
    return 0


def fetch_month(user: str, dry_run: bool) -> int:
    """One request for the trailing 30 days. Stats lag ~18h, so do not run at midnight."""
    url = f"{STATS_URL.format(user=user)}?range=month&count=1000"
    status, body, _ = http_get(url, user_agent=USER_AGENT, service="ListenBrainz")
    if status == 204:
        print("ListenBrainz has no stats for that window yet", file=sys.stderr)
        return 1
    if status == 404:
        sys.exit(f"ListenBrainz does not know a user called {user!r}")
    if status != 200:
        print(f"HTTP {status}", file=sys.stderr)
        return 1
    payload = json.loads(body)
    month, rows = listens.from_stats(payload)
    total = payload["payload"].get("total_artist_count")
    if total and len(rows) < total:
        print(f"warning: got {len(rows)} of {total} artists -- raise count", file=sys.stderr)
    print(f"{month}: {len(rows)} artists, {sum(r['plays'] for r in rows)} plays")
    if dry_run:
        return 0
    print(f"wrote {shorten(listens.write_month(month, rows, 'stats'))}")
    return 0


VERDICT_FILE = DATA / "profile.json"

# thin is 5,608 of 7,807 rows and nothing consumes it, so the file carries the
# three bands a decision could be made from.
WRITTEN_BANDS = ("core", "lapsed", "emerging")


def write_verdicts(rows, now: str, window: int, path: Path) -> int:
    """The machine-readable half, for stages/favourites.py --from-profile.

    A file rather than an import, so the verdict can be read and edited before
    anything spends a Qobuz request on it.
    """
    judged = [(verdict(row), row) for row in rows]
    judged = [pair for pair in judged if pair[0] in WRITTEN_BANDS]
    # Sorted on the rows, not the dicts, so the keys stay typed.
    judged.sort(key=lambda pair: (WRITTEN_BANDS.index(pair[0]), -pair[1].months))
    artists = [{"name": row.name, "mbid": row.mbid, "band": band,
                "months": row.months, "recent": row.recent,
                "plays": row.plays, "recent_plays": row.recent_plays,
                "first": row.first, "last": row.last}
               for band, row in judged]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"generated": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
         "through": now, "window": window,
         "floors": {"m24": policy.M24_FLOOR, "deep": policy.DEEP_FLOOR,
                    "emerging_plays": policy.EMERGING_PLAYS},
         "artists": artists}, indent=2, ensure_ascii=False) + "\n")
    return len(artists)


def report(window: int, min_months: int, show_all: bool, json_path: Path | None) -> int:
    months = listens.read_months()
    if not months:
        print("nothing to profile yet -- run --seed first", file=sys.stderr)
        return 1
    now = max(months)
    rows = listens.profile(listens.fold(months), now, window)

    watched = {e["mbid"] for e in favourites.load()
               if e.get("mbid") and e.get("watch", True)}
    muted = {e["mbid"] for e in favourites.load()
             if e.get("mbid") and not e.get("watch", True)}

    counts: dict[str, int] = {}
    for row in rows:
        band = verdict(row)
        counts[band] = counts.get(band, 0) + 1

    print(f"{len(rows)} artists over {len(months)} months, through {now} "
          f"(window {window}mo, floors {policy.M24_FLOOR}/{policy.DEEP_FLOOR})")
    print("  " + "  ".join(f"{b} {counts.get(b, 0)}" for b in BAND_ORDER))
    print()

    shown = [r for r in rows if show_all or r.months >= min_months]
    shown.sort(key=lambda r: (BAND_ORDER[verdict(r)], -r.months))
    print(f"{'band':<9}{'artist':<34}{'life':>5}{'m' + str(window):>5}"
          f"{'plays':>8}{'recent':>8}  last     watch")
    for row in shown:
        band = verdict(row)
        if band == "thin" and not show_all:
            continue
        mark = "yes" if row.mbid in watched else "MUTED" if row.mbid in muted else "-"
        print(f"{band:<9}{row.name[:33]:<34}{row.months:>5}{row.recent:>5}"
              f"{row.plays:>8}{row.recent_plays:>8}  {row.last}  {mark}")

    # The three sets that are the point of the exercise.
    add = [r for r in shown if verdict(r) in ("core", "emerging")
           and r.mbid and r.mbid not in watched and r.mbid not in muted]
    drop = [r for r in shown if verdict(r) == "lapsed"
            and r.mbid in watched]
    check = [r for r in shown if verdict(r) == "core"
             and r.mbid in muted]
    print()
    print(f"watch these, not watched yet : {len(add)}")
    print(f"watched but lapsed           : {len(drop)}  "
          f"({', '.join(r.name for r in drop[:6])})")
    print(f"muted but still core         : {len(check)}  "
          f"({', '.join(r.name for r in check[:6])})")

    if json_path:
        written = write_verdicts(rows, now, window, json_path)
        print(f"\nwrote {shorten(json_path)} ({written} artists in "
              f"{', '.join(WRITTEN_BANDS)})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Profile your listening in active months, not play counts.")
    parser.add_argument("--seed", action="store_true",
                        help="compact a ListenBrainz export zip into one file per month")
    parser.add_argument("--export", metavar="PATH",
                        help=f"zip to seed from (default: largest match for {EXPORT_GLOB})")
    parser.add_argument("--month", action="store_true",
                        help="fetch the trailing 30 days and save it (1 request)")
    parser.add_argument("--user", help="ListenBrainz username (needed with --month)")
    parser.add_argument("--window", type=int, default=policy.RECENT_WINDOW,
                        help=f"months that count as recent (default: {policy.RECENT_WINDOW})")
    parser.add_argument("--min-months", type=int, default=3, metavar="N",
                        help="hide artists with fewer lifetime months (default: 3)")
    parser.add_argument("--all", action="store_true",
                        help="show every artist, including thin ones")
    parser.add_argument("--json", nargs="?", const=str(VERDICT_FILE), metavar="PATH",
                        help=f"also write the verdicts for --from-profile to read "
                             f"(default: {VERDICT_FILE.name})")
    parser.add_argument("--dry-run", action="store_true", help="write nothing")
    args = parser.parse_args()

    if args.seed and args.month:
        parser.error("--seed and --month are separate runs")
    if args.seed:
        path = Path(args.export) if args.export else newest_export()
        if not path or not path.exists():
            parser.error(f"no export found; --export PATH (looked for {EXPORT_GLOB})")
        return seed(path, args.dry_run)
    if args.month:
        if not args.user:
            parser.error("--month needs --user")
        return fetch_month(args.user, args.dry_run)
    json_path = Path(args.json) if args.json and not args.dry_run else None
    return report(args.window, args.min_months, args.all, json_path)


if __name__ == "__main__":
    sys.exit(main())
