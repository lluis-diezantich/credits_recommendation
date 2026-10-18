"""Per-artist listening history, month by month.

Two sources, one shape: a month, an artist, a play count. The export seeds
every month up to the day it was downloaded; the stats API adds the ones after.

No judgement here -- `window` is passed in, and policy.py decides the bands.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from core.names import normalise
from core.paths import CACHE, ROOT

MONTHS = CACHE / "listens_months"

# The export lives OUTSIDE the repo, and is found rather than required.
EXPORT_GLOB = str(ROOT.parent / "listenbrainz_*.zip")


def newest_export(pattern: str = EXPORT_GLOB) -> Path | None:
    """The export to read, chosen by SIZE rather than by name.

    sorted(glob)[-1] takes the last name alphabetically, and
    "listenbrainz_sample.zip" sorts after "listenbrainz_<user>_<stamp>.zip" --
    so a 2,000-listen sample silently shadowed 190,131 listens, and every
    number measured off it was wrong by two orders of magnitude.
    """
    found = sorted(glob.glob(pattern), key=lambda path: Path(path).stat().st_size)
    return Path(found[-1]) if found else None


@dataclass(frozen=True)
class Artist:
    """One row of the profile. `key` is an mbid, or "name:<folded>" without one."""

    key: str
    name: str
    mbid: str | None
    months: int          # lifetime active months
    recent: int          # active months inside the window
    plays: int
    recent_plays: int
    first: str
    last: str


def index(month: str) -> int:
    """"2026-05" -> a comparable integer, so month arithmetic needs no dates."""
    return int(month[:4]) * 12 + int(month[5:7])


def read_export(path: Path) -> dict[str, list[dict]]:
    """{"2013-03": [{"mbid", "name", "plays"}, ...]} from a ListenBrainz export.

    A collaboration counts for every credited artist, which is what the stats
    API does too, so the two sources join without a step at the seam.
    `mbid_mapping.artists` carries one name per mbid; `artist_name` is the whole
    credit line ("Milo j & Trueno") and is used only where the mapping is absent
    (7.4% of listens).
    """
    tally: dict[str, Counter] = defaultdict(Counter)
    labels: dict[str, Counter] = defaultdict(Counter)
    with zipfile.ZipFile(path) as zf:
        for entry in zf.namelist():
            if not entry.startswith("listens/") or not entry.endswith(".jsonl"):
                continue
            with zf.open(entry) as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        listen = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    stamp = listen.get("listened_at")
                    if not isinstance(stamp, (int, float)):
                        continue
                    month = dt.datetime.fromtimestamp(stamp, dt.UTC).date().isoformat()[:7]
                    meta = listen.get("track_metadata") or {}
                    mapped = (meta.get("mbid_mapping") or {}).get("artists") or []
                    if mapped:
                        credits = [(a.get("artist_mbid"), a.get("artist_credit_name") or "")
                                   for a in mapped]
                    else:
                        credits = [(None, meta.get("artist_name") or "")]
                    for mbid, name in credits:
                        if not (mbid or name):
                            continue
                        key = mbid or "name:" + normalise(name)
                        tally[month][key] += 1
                        labels[key][name] += 1
    return {
        month: [{"mbid": None if key.startswith("name:") else key,
                 "name": labels[key].most_common(1)[0][0],
                 "plays": plays}
                for key, plays in counts.items()]
        for month, counts in sorted(tally.items())
    }


def from_stats(payload: dict) -> tuple[str, list[dict]]:
    """(month, rows) from one /1/stats/user/X/artists response.

    Labelled from `from_ts`, not today and not `to_ts`: `range=month` returns a
    complete calendar month, and its `to_ts` is the exclusive end, so Sep 2026
    arrives as 2026-09-01 -> 2026-10-01 and `to_ts` would name October.
    """
    body = payload.get("payload") or payload
    start = dt.datetime.fromtimestamp(body["from_ts"], dt.UTC).date()
    rows = [{"mbid": artist.get("artist_mbid"),
             "name": artist.get("artist_name") or "",
             "plays": artist.get("listen_count") or 0}
            for artist in body.get("artists") or []]
    return start.isoformat()[:7], rows


def write_month(month: str, rows: list[dict], source: str,
                directory: Path | None = None) -> Path:
    """One file per month, so a month that was never fetched is a missing file."""
    directory = directory or MONTHS       # resolved per call, so tests can redirect it
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{month}.json"
    path.write_text(json.dumps({"month": month, "source": source, "artists": rows},
                               ensure_ascii=False) + "\n")
    return path


def read_months(directory: Path | None = None) -> dict[str, list[dict]]:
    months = {}
    directory = directory or MONTHS
    for path in sorted(directory.glob("[0-9]*.json")):
        data = json.loads(path.read_text())
        months[data["month"]] = data["artists"]
    return months


def fold(months: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Give name-only rows the mbid that spelling carries in any other month.

    The stats API splits one artist whenever a listen went unmapped or the
    accents differ, so "Jorge Drexler" arrives twice in the same month, once
    with an mbid and once without. Folding recovered 59 of 130 such rows.
    """
    known: dict[str, str] = {}
    for rows in months.values():
        for row in rows:
            if row.get("mbid"):
                known.setdefault(normalise(row["name"]), row["mbid"])
    folded = {}
    for month, rows in months.items():
        merged: dict[str, dict] = {}
        for row in rows:
            mbid = row.get("mbid") or known.get(normalise(row["name"]))
            key = mbid or "name:" + normalise(row["name"])
            if key in merged:
                merged[key]["plays"] += row["plays"]
            else:
                merged[key] = {"mbid": mbid, "name": row["name"], "plays": row["plays"]}
        folded[month] = list(merged.values())
    return folded


def profile(months: dict[str, list[dict]], now: str, window: int) -> list[Artist]:
    """One row per artist. `now` is the month the window counts back from."""
    active: dict[str, set[str]] = defaultdict(set)
    recent: dict[str, set[str]] = defaultdict(set)
    plays: Counter = Counter()
    recent_plays: Counter = Counter()
    labels: dict[str, Counter] = defaultdict(Counter)
    mbids: dict[str, str] = {}
    end = index(now)
    for month, rows in months.items():
        inside = 0 <= end - index(month) < window
        for row in rows:
            mbid = row.get("mbid")
            key = mbid or "name:" + normalise(row["name"])
            active[key].add(month)
            plays[key] += row["plays"]
            labels[key][row["name"]] += row["plays"]
            if mbid:
                mbids[key] = mbid
            if inside:
                recent[key].add(month)
                recent_plays[key] += row["plays"]
    return [Artist(key=key,
                   name=labels[key].most_common(1)[0][0],
                   mbid=mbids.get(key),
                   months=len(seen),
                   recent=len(recent[key]),
                   plays=plays[key],
                   recent_plays=recent_plays[key],
                   first=min(seen),
                   last=max(seen))
            for key, seen in active.items()]
