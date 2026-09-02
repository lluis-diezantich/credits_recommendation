#!/usr/bin/env python3
"""A personal new-release radar, backed by the Qobuz API. No login required.

Third of three, alongside fresh_releases.py (ListenBrainz) and
itunes_releases.py (Apple). Same job, same output shape -- and this one is the
authoritative answer about what you can actually play, because it is the
catalogue you subscribe to.

Approach borrowed from pawllo01/qobuz-artist-discography (MIT): the store-front
API accepts a public app id plus the cookies any /discover page hands out, with
NO account, NO token and NO request signature. An earlier version of this script
tried to log in with email+password and burned a lot of time on it; that turned
out to be unnecessary.

    ./qobuz_releases.py --find "Jorge Drexler"   # look up an artist id
    ./qobuz_releases.py                          # new releases, last 90 days
    ./qobuz_releases.py --days 0                 # no date cutoff
    ./qobuz_releases.py --all                    # ignore the state file
    ./qobuz_releases.py --dry-run                # report, record nothing
    ./qobuz_releases.py --store es-es            # a different storefront
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Run directly (./radars/qobuz.py) or as a module (python -m radars.qobuz).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.paths import DATA
from core.qobuz import API, APP_ID, PAGE_LIMIT, SITE, STORE, UA
from core.qobuz import get as _get
from core.qobuz import message as _message
from core.qobuz import store_cookies
from core.state import load_seen as _load_seen
from core.state import save_seen as _save_seen

STATE_FILE = DATA / "qobuz_seen.json"


def load_seen() -> set[str]:
    return _load_seen(STATE_FILE)

# --- what you watch -------------------------------------------------------
# Qobuz artist IDs -- a third namespace, unrelated to MusicBrainz MBIDs and
# Apple artist IDs. Find one with:  ./qobuz_releases.py --find "Name"
WATCHED_ARTISTS: dict[int, str] = {
    41620: "Jorge Drexler",
}


# Qobuz does NOT return release_type on this endpoint, so the type is inferred
# from track count -- see classify(). These are the inferred labels to report.
KEEP_TYPES = {"Album", "EP", "Single"}

# Only report releases this recent, so a first run records the back catalogue
# silently instead of printing decades of it. 0 disables.
RECENT_DAYS = 90


def find_artists(name: str, store: str) -> list[dict]:
    """Autosuggest search. Needs no app id and no cookies at all."""
    url = f"{SITE}/v4/{store}/catalog/search/autosuggest?q={urllib.parse.quote(name)}"
    status, body, _ = _get(url, {"x-requested-with": "XMLHttpRequest"})
    if status != 200:
        raise SystemExit(f"Qobuz search failed (HTTP {status}): {_message(body)}")
    try:
        return json.loads(body).get("artists") or []
    except json.JSONDecodeError:
        raise SystemExit("Qobuz search returned a non-JSON body")


def artist_releases(artist_id: int, store: str, cookies: str) -> tuple[str, list[dict]]:
    """(artist name, every release where they are a primary artist).

    `extra=albums_with_last_release` puts the discography under
    `albums_without_last_release`. Paginated because prolific artists exceed
    one page.
    """
    zone = store.split("-")[0].upper()
    headers = {"x-app-id": APP_ID, "cookie": cookies}
    name = "?"
    collected: list[dict] = []
    offset = 0

    while True:
        query = urllib.parse.urlencode({
            "artist_id": artist_id,
            "extra": "albums_with_last_release",
            "limit": PAGE_LIMIT,
            "offset": offset,
            "zone": zone,
            "store": store,
        })
        status, body, _ = _get(f"{API}/artist/get?{query}", headers)
        if status != 200:
            raise SystemExit(f"Qobuz artist/get failed (HTTP {status}): {_message(body)}")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            raise SystemExit("Qobuz artist/get returned a non-JSON body")

        name = data.get("name") or name
        page = (data.get("albums_without_last_release") or {}).get("items") or []
        # Skip releases where this artist is only a composer or a guest: the
        # discography otherwise fills up with other people's records.
        collected += [album for album in page
                      if any(str(a.get("id")) == str(artist_id)
                             for a in (album.get("artists") or []))]
        if len(page) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT

    return name, collected


def classify(album: dict) -> str:
    """Album / EP / Single, inferred from track count.

    This endpoint returns no release_type, so there is nothing authoritative to
    read. The thresholds are a heuristic: a 6-track album will be labelled EP.
    """
    tracks = album.get("tracks_count") or 0
    if tracks == 1:
        return "Single"
    if 2 <= tracks <= 6:
        return "EP"
    return "Album"


def normalize(album: dict, label: str) -> dict:
    """One release, in the shape the other two scripts report."""
    date = (album.get("release_date_original")
            or album.get("release_date_stream")
            or "")[:10] or "????-??-??"
    artists = [a.get("name") for a in (album.get("artists") or []) if a.get("name")]
    version = (album.get("version") or "").strip()
    return {
        "date": date,
        "type": classify(album),
        "artist": ", ".join(artists) or label,
        "title": f"{album.get('title') or '(untitled)'}" + (f" ({version})" if version else ""),
        "id": str(album.get("id") or ""),
        "source": "qobuz",
        "tracks": album.get("tracks_count") or 0,
        "hires": bool(album.get("hires")),
        "streamable": bool(album.get("streamable")),
    }


def describe(release: dict, today: dt.date) -> str:
    upcoming = " [upcoming]" if release["date"] > today.isoformat() else ""
    bits = []
    if release["tracks"]:
        bits.append(f"{release['tracks']} tr")
    if release["hires"]:
        bits.append("hi-res")
    if not release["streamable"]:
        bits.append("not streamable")
    suffix = f" ({', '.join(bits)})" if bits else ""
    return (f"{release['date']}  {release['type']:<7}{upcoming:<11} "
            f"{release['artist']} - {release['title']}{suffix}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Report new releases from watched artists via Qobuz.")
    parser.add_argument("--find", metavar="NAME", help="look up Qobuz artist ids by name and exit")
    parser.add_argument("--store", default=STORE, help=f"storefront code (default: {STORE})")
    parser.add_argument("--days", type=int, default=RECENT_DAYS,
                        help=f"only report releases this recent; 0 disables (default: {RECENT_DAYS})")
    parser.add_argument("--all", action="store_true", help="report everything, ignoring the state file")
    parser.add_argument("--dry-run", action="store_true", help="report without recording anything")
    args = parser.parse_args()

    if args.find:
        found = find_artists(args.find, args.store)
        if not found:
            print(f"No Qobuz artist matched {args.find!r}.")
            return 0
        print(f"Qobuz artists matching {args.find!r} - add one to WATCHED_ARTISTS:\n")
        for artist in found[:15]:
            print(f"  {str(artist.get('id')):>10}  {artist.get('name')}"
                  f"   ({artist.get('albumsCount') or 0} albums)")
        return 0

    if not WATCHED_ARTISTS:
        sys.exit("WATCHED_ARTISTS is empty - run with --find \"Artist Name\" to get an id.")

    today = dt.date.today()
    cutoff = (today - dt.timedelta(days=args.days)).isoformat() if args.days > 0 else ""
    seen = set() if args.all else load_seen()
    cookies = store_cookies(args.store)

    found: list[dict] = []
    everything: set[str] = set()
    scanned = 0

    for artist_id, label in WATCHED_ARTISTS.items():
        name, albums = artist_releases(artist_id, args.store, cookies)
        scanned += len(albums)
        if not albums:
            print(f"warning: {label} ({artist_id}) returned no releases in the "
                  f"{args.store} store", file=sys.stderr)
        for album in albums:
            release = normalize(album, name or label)
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
          f"artist{'s' if watching != 1 else ''} in the {args.store} store ({window}).")

    if not found:
        print("Nothing new.")
    else:
        print()
        for release in sorted(found, key=lambda r: r["date"]):
            print(f"  {describe(release, today)}")
        print()
        print(f"{len(found)} new release{'s' if len(found) != 1 else ''}.")

    # Record everything seen, not just what was reported, so the date cutoff
    # does not cause old releases to resurface later.
    if not args.dry_run and not args.all and everything:
        _save_seen(STATE_FILE, seen | everything)

    return 0


if __name__ == "__main__":
    sys.exit(main())
