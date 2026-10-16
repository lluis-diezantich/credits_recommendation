#!/usr/bin/env python3
"""A personal new-release radar.

One GET to the ListenBrainz fresh-releases feed returns every release
MusicBrainz knows about in a window around today. We intersect that against
WATCHED_ARTISTS locally, then subtract whatever we already reported on a
previous run, so each run shows only what is new to you.

No API key and no auth. `requests` via core/http.py for the pooling and the
retry policy.

    ./fresh_releases.py              # what is new since last run
    ./fresh_releases.py --all        # everything in the window, ignore state
    ./fresh_releases.py --days 60    # widen the window
    ./fresh_releases.py --dry-run    # report without recording anything
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

# Run directly (./radars/qobuz.py) or as a module (python -m radars.qobuz).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import favourites
from core.http import get as http_get
from core.paths import DATA
from core.state import load_seen as _load_seen
from core.state import save_seen as _save_seen

STATE_FILE = DATA / "seen.json"


def load_seen() -> set[str]:
    return _load_seen(STATE_FILE)


def save_seen(seen: set[str]) -> None:
    _save_seen(STATE_FILE, seen)

# --- what you watch -------------------------------------------------------
# MusicBrainz artist MBIDs. The name is only a label for the output; matching
# is done on the MBID, which is why collaborations are caught too (a release
# credited "X & Y" carries both MBIDs in artist_mbids).
#
# To find an MBID: search the artist on musicbrainz.org and take the UUID out
# of the /artist/<uuid> URL.
# This literal is now only the FALLBACK, used when data/favourites.json
# carries no mbid. Generate that file with ./stages/favourites.py.
WATCHED_ARTISTS: dict[str, str] = favourites.ids_for("mbid", {
    "abb91078-f7db-41f2-8f07-7f37bb739143": "Jorge Drexler",
})

# Release types to report. The feed also carries "Broadcast", "Other", and
# None (untyped); those are noise for this purpose.
KEEP_TYPES = {"Album", "EP", "Single"}

# The feed window is +/- this many days around today, so this is both how far
# back we look and how far ahead we see announced releases.
#
# Keep this comfortably LARGER than how often you run the script. MusicBrainz
# entries are often registered days after the release date, so a 1-day window
# run daily would permanently miss anything registered late. The state file
# absorbs the resulting overlap, and re-fetching the same rows costs nothing.
LOOKBACK_DAYS = 14

FEED_URL = "https://api.listenbrainz.org/1/explore/fresh-releases/"
USER_AGENT = "fresh-releases-radar/1.0 (personal use)"


def fetch_feed(anchor: dt.date, days: int) -> list[dict]:
    """Return every release in the feed window around `anchor`."""
    url = f"{FEED_URL}?release_date={anchor.isoformat()}&days={days}"
    status, body, _ = http_get(url, timeout=60, user_agent=USER_AGENT,
                               service="ListenBrainz")
    if status != 200:
        sys.exit(f"ListenBrainz returned HTTP {status} for {url}")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        sys.exit("ListenBrainz returned a response that was not JSON")

    return payload.get("payload", {}).get("releases", [])


def matches_watchlist(release: dict) -> list[str]:
    """Names of watched artists credited on this release."""
    mbids = release.get("artist_mbids") or []
    return [WATCHED_ARTISTS[mbid] for mbid in mbids if mbid in WATCHED_ARTISTS]


def describe(release: dict, names: list[str], today: dt.date) -> str:
    date = release.get("release_date", "????-??-??")
    kind = release.get("release_group_primary_type") or "Release"
    title = release.get("release_name", "(untitled)")
    credit = release.get("artist_credit_name", "")

    # The feed reaches into the future, so an unreleased album would otherwise
    # look like something you had somehow missed.
    upcoming = " [upcoming]" if date > today.isoformat() else ""

    # Show the full credit when it differs from the watched artist, so a
    # collaboration or a compilation appearance is obvious.
    watched = ", ".join(names)
    attribution = credit if credit and credit != watched else watched

    return f"{date}  {kind:<7}{upcoming:<11} {attribution} - {title}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Report new releases from watched artists.")
    parser.add_argument("--days", type=int, default=LOOKBACK_DAYS,
                        help="half-width of the feed window in days "
                             f"(default: {LOOKBACK_DAYS})")
    parser.add_argument("--all", action="store_true",
                        help="report everything in the window, including already-seen releases")
    parser.add_argument("--dry-run", action="store_true",
                        help="report without recording anything to the state file")
    args = parser.parse_args()

    if not WATCHED_ARTISTS:
        sys.exit("WATCHED_ARTISTS is empty - add at least one MusicBrainz artist MBID.")

    today = dt.date.today()
    releases = fetch_feed(today, args.days)
    seen = set() if args.all else load_seen()

    hits = []
    for release in releases:
        names = matches_watchlist(release)
        if not names:
            continue
        if release.get("release_group_primary_type") not in KEEP_TYPES:
            continue
        # release_mbid is the stable dedup key; fall back to the release-group
        # or a synthetic key for the rare row that carries neither.
        key = (release.get("release_mbid")
               or release.get("release_group_mbid")
               or "|".join([str(release.get("artist_credit_name")),
                            str(release.get("release_name")),
                            str(release.get("release_date"))]))
        if key in seen:
            continue
        hits.append((key, release, names))

    watching = len(WATCHED_ARTISTS)
    print(f"Scanned {len(releases)} releases in a +/-{args.days} day window "
          f"around {today.isoformat()}, watching {watching} "
          f"artist{'s' if watching != 1 else ''}.")

    if not hits:
        print("Nothing new.")
        return 0

    print()
    for _, release, names in sorted(hits, key=lambda h: h[1].get("release_date", "")):
        print(f"  {describe(release, names, today)}")
    print()
    print(f"{len(hits)} new release{'s' if len(hits) != 1 else ''}.")

    if not args.dry_run and not args.all:
        save_seen(seen | {key for key, _, _ in hits})

    return 0


if __name__ == "__main__":
    sys.exit(main())
