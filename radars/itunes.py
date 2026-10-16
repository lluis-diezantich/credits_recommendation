#!/usr/bin/env python3
"""A personal new-release radar, backed by the iTunes Search API.

Companion to fresh_releases.py, which reads the ListenBrainz feed. That one is
a single global request filtered locally, and inherits MusicBrainz's coverage
gaps: it does not know about releases MusicBrainz has not registered yet, which
in practice means a lot of singles and a lot of non-Anglophone artists.

This one asks Apple about each watched artist directly. More requests, far
better coverage of what actually came out, but it can only ever tell you about
artists you have listed.

No API key, no auth, standard library only.

    ./itunes_releases.py              # new releases from the last 90 days
    ./itunes_releases.py --days 365   # widen the reporting window
    ./itunes_releases.py --days 0     # no date cutoff (first run: whole discography)
    ./itunes_releases.py --all        # ignore the state file
    ./itunes_releases.py --dry-run    # report without recording anything
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Run directly (./radars/qobuz.py) or as a module (python -m radars.qobuz).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import favourites
from core.paths import DATA
from core.state import load_seen as _load_seen
from core.state import save_seen as _save_seen

STATE_FILE = DATA / "itunes_seen.json"


def load_seen() -> set[str]:
    return _load_seen(STATE_FILE)


def save_seen(seen: set[str]) -> None:
    _save_seen(STATE_FILE, seen)

# --- what you watch -------------------------------------------------------
# Apple artist IDs, which are NOT MusicBrainz MBIDs. This is deliberately a
# separate namespace (and a separate state file) from fresh_releases.py, so the
# two scripts never have to agree about artist identity.
#
# To find an ID:
#   curl -s "https://itunes.apple.com/search?term=Jorge+Drexler&entity=musicArtist&limit=3" \
#     | python3 -m json.tool
# and take `artistId`.
# This literal is now only the FALLBACK, used when data/favourites.json
# carries no itunes_id. Generate that file with ./stages/favourites.py.
WATCHED_ARTISTS: dict[int, str] = favourites.ids_for("itunes_id", {
    16421943: "Jorge Drexler",
})

# Apple's catalogue is territory-specific: the same artist returned 69 releases
# in the US store, 66 in ES, 69 in UY. If a release you expect is missing, try
# the artist's home storefront before assuming the API is at fault.
STOREFRONT = "US"

# Release types to report. Apple has no usable type field (`collectionType` is
# literally "Album" even for a one-track single), so this is inferred from the
# title suffix -- see classify().
KEEP_TYPES = {"Album", "EP", "Single"}

# Only report releases at most this many days old. This is what stops the first
# run from dumping a 40-year back catalogue at you: everything gets recorded to
# the state file, but only recent releases are reported. Use --days 0 to
# disable.
#
# The trade-off: a genuinely new *addition* of an old record (a reissue Apple
# only just listed) is recorded silently and never reported.
RECENT_DAYS = 90

LOOKUP_URL = "https://itunes.apple.com/lookup"
USER_AGENT = "fresh-releases-radar/1.0 (personal use)"

# Apple does not document a rate limit, so be unhurried between artists.
REQUEST_PAUSE_SECONDS = 0.5


def fetch_artist_releases(artist_id: int) -> list[dict]:
    """Every release Apple lists for one artist, as raw result rows."""
    query = urllib.parse.urlencode({
        "id": artist_id,
        "entity": "album",
        "limit": 200,
        "country": STOREFRONT,
    })
    request = urllib.request.Request(f"{LOOKUP_URL}?{query}",
                                     headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)

    # results[0] is the artist itself (wrapperType "artist"); the rest are
    # releases. An unknown ID yields an empty list rather than an error.
    return [row for row in payload.get("results", [])
            if row.get("wrapperType") == "collection"]


def classify(row: dict) -> str:
    """Album / EP / Single, inferred from the title.

    Apple encodes the type in the name ("Foo - Single", "Foo - EP") and gives
    every release collectionType "Album", so the suffix is the only real
    signal. trackCount is the tie-breaker for anything untagged.
    """
    name = row.get("collectionName") or ""
    if name.endswith(" - Single"):
        return "Single"
    if name.endswith(" - EP"):
        return "EP"
    if (row.get("trackCount") or 0) == 1:
        return "Single"
    return "Album"


def clean_title(row: dict) -> str:
    """The title without Apple's type suffix, which we show in its own column."""
    name = row.get("collectionName") or "(untitled)"
    for suffix in (" - Single", " - EP"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def normalize(row: dict, label: str) -> dict:
    """One release, in the same shape fresh_releases.py reports.

    Keeping the two scripts' records structurally similar is deliberate: if
    they are ever merged, the shared part is the reporting stage, and this is
    the seam it would work against.
    """
    return {
        "date": (row.get("releaseDate") or "")[:10] or "????-??-??",
        "type": classify(row),
        "artist": row.get("artistName") or label,
        "title": clean_title(row),
        "id": str(row.get("collectionId") or ""),
        "source": "itunes",
        "tracks": row.get("trackCount") or 0,
    }


def describe(release: dict, today: dt.date) -> str:
    # Apple lists pre-orders with a future date, so flag those rather than
    # letting them look like something you had missed.
    upcoming = " [upcoming]" if release["date"] > today.isoformat() else ""
    tracks = f"({release['tracks']} tr)" if release["tracks"] else ""
    return (f"{release['date']}  {release['type']:<7}{upcoming:<11} "
            f"{release['artist']} - {release['title']} {tracks}".rstrip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Report new releases from watched artists via iTunes.")
    parser.add_argument("--days", type=int, default=RECENT_DAYS,
                        help=f"only report releases this recent; 0 disables (default: {RECENT_DAYS})")
    parser.add_argument("--all", action="store_true",
                        help="report everything, including already-seen releases")
    parser.add_argument("--dry-run", action="store_true",
                        help="report without recording anything to the state file")
    args = parser.parse_args()

    if not WATCHED_ARTISTS:
        sys.exit("WATCHED_ARTISTS is empty - add at least one Apple artist ID.")

    today = dt.date.today()
    cutoff = (today - dt.timedelta(days=args.days)).isoformat() if args.days > 0 else ""
    seen = set() if args.all else load_seen()

    found: list[dict] = []
    everything: set[str] = set()
    scanned = 0

    for index, (artist_id, label) in enumerate(WATCHED_ARTISTS.items()):
        if index:
            time.sleep(REQUEST_PAUSE_SECONDS)
        try:
            rows = fetch_artist_releases(artist_id)
        except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as error:
            # One artist failing should not lose the whole run.
            print(f"warning: {label} ({artist_id}) lookup failed: {error}", file=sys.stderr)
            continue

        if not rows:
            print(f"warning: {label} ({artist_id}) returned no releases "
                  f"- wrong ID, or nothing in the {STOREFRONT} store?", file=sys.stderr)
            continue

        scanned += len(rows)
        for row in rows:
            release = normalize(row, label)
            if not release["id"]:
                continue
            everything.add(release["id"])
            if release["id"] in seen:
                continue
            if release["type"] not in KEEP_TYPES:
                continue
            if cutoff and release["date"] < cutoff:
                continue
            found.append(release)

    watching = len(WATCHED_ARTISTS)
    window = f"last {args.days} days" if args.days > 0 else "all dates"
    print(f"Scanned {scanned} releases from {watching} "
          f"artist{'s' if watching != 1 else ''} in the {STOREFRONT} store ({window}).")

    if not found:
        print("Nothing new.")
    else:
        print()
        for release in sorted(found, key=lambda r: r["date"]):
            print(f"  {describe(release, today)}")
        print()
        print(f"{len(found)} new release{'s' if len(found) != 1 else ''}.")

    # Record everything seen this run, not just what was reported, so the date
    # cutoff does not cause old releases to be re-reported later.
    if not args.dry_run and not args.all and everything:
        save_seen(seen | everything)

    return 0


if __name__ == "__main__":
    sys.exit(main())
