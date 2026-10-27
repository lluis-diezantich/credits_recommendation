#!/usr/bin/env python3
"""A personal new-release radar, backed by the ListenBrainz fresh-releases feed.

One GET returns every release MusicBrainz knows about in a window around today.
We intersect that against WATCHED_ARTISTS locally, then subtract whatever we
already reported on a previous run, so each run shows only what is new to you.

The odd one of the three. itunes.py and qobuz.py ask per artist and read a
catalogue; this reads a WINDOW, and two settings in core/radar.py exist to say
so: `record_scanned` is off, because recording a release that matched nobody
would hide it for good if you later started watching that artist, and
`guard_empty_run` is off, because a feed answering with zero rows is a
legitimate quiet window and nothing distinguishes it from an outage.

No API key and no auth. `requests` via core/http.py for the pooling and the
retry policy.

    ./radars/listenbrainz.py              # what is new since last run
    ./radars/listenbrainz.py --all        # everything in the window, ignore state
    ./radars/listenbrainz.py --days 60    # widen the window
    ./radars/listenbrainz.py --dry-run    # report without recording anything
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from collections.abc import Iterator
from pathlib import Path

from core import favourites
from core.http import get as http_get
from core.paths import DATA
from core.radar import Batch, Radar, Release, execute, parser

# --- what you watch -------------------------------------------------------
# MusicBrainz artist MBIDs. The name is only a label for the output; matching
# is done on the MBID, which is why collaborations are caught too (a release
# credited "X & Y" carries both MBIDs in artist_mbids).
#
# To find an MBID: search the artist on musicbrainz.org and take the UUID out
# of the /artist/<uuid> URL.
# This literal is now only the FALLBACK, used when data/favourites.json
# carries no mbid. That file is hand-edited on main (D41).
WATCHED_ARTISTS: dict[str, str] = favourites.ids_for("mbid", {
    "abb91078-f7db-41f2-8f07-7f37bb739143": "Jorge Drexler",
})

# Keep this comfortably LARGER than how often you run the script. MusicBrainz
# entries are often registered days after the release date, so a 1-day window
# run daily would permanently miss anything registered late. The state file
# absorbs the resulting overlap, and re-fetching the same rows costs nothing.
LOOKBACK_DAYS = 14

FEED_URL = "https://api.listenbrainz.org/1/explore/fresh-releases/"
USER_AGENT = "fresh-releases-radar/1.0 (personal use)"


def fetch_feed(anchor: dt.date, days: int) -> list[dict]:
    """Every release in the feed window around `anchor`.

    Exits rather than degrading: there is exactly one call in this radar, so a
    failure leaves nothing to salvage and nothing to report. The per-artist
    radars can lose one lookup of ninety and still be useful; this cannot.
    """
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


def dedup_key(release: dict) -> str:
    """The stable identity of a feed row.

    release_mbid normally; the release-group or a synthetic key for the rare
    row carrying neither, which would otherwise be reported every single run.
    """
    return (release.get("release_mbid")
            or release.get("release_group_mbid")
            or "|".join([str(release.get("artist_credit_name")),
                         str(release.get("release_name")),
                         str(release.get("release_date"))]))


def normalize(release: dict, names: list[str]) -> Release:
    """One feed row as a Release, attributed to whoever is actually credited.

    Show the full credit when it differs from the watched artist, so a
    collaboration or a compilation appearance is obvious rather than looking
    like a record you did not know they made.
    """
    credit = release.get("artist_credit_name", "")
    watched = ", ".join(names)
    return Release(
        id=dedup_key(release),
        date=release.get("release_date") or "????-??-??",
        kind=release.get("release_group_primary_type") or "Release",
        artist=credit if credit and credit != watched else watched,
        title=release.get("release_name") or "(untitled)",
        source="listenbrainz",
    )


class ListenbrainzRadar(Radar):
    name = "listenbrainz"
    # The feed also carries "Broadcast", "Other", and None (untyped); those are
    # noise for this purpose. None arrives here as "Release" -- see normalize.
    keep_types = {"Album", "EP", "Single"}
    default_days = LOOKBACK_DAYS
    days_help = "half-width of the feed window in days"
    record_scanned = False
    guard_empty_run = False

    @property
    def state_file(self) -> Path:
        # Not listenbrainz_seen.json: this radar was the project's first, its
        # state file predates the naming convention, and renaming it would
        # silently re-report everything in the window once.
        return DATA / "seen.json"

    def watching(self) -> dict:
        return WATCHED_ARTISTS

    def empty_message(self) -> str:
        return "WATCHED_ARTISTS is empty - add at least one MusicBrainz artist MBID."

    def window(self, args) -> str:
        return f"+/-{args.days} days around {dt.date.today().isoformat()}"

    def cutoff(self, args, today: dt.date) -> str:
        # The server already applied the window; filtering again here would
        # halve it, because --days is a half-width, not a lookback.
        return ""

    def batches(self, args, watching: dict) -> Iterator[Batch]:
        rows = fetch_feed(dt.date.today(), args.days)
        matched = []
        for row in rows:
            names = [watching[mbid] for mbid in (row.get("artist_mbids") or [])
                     if mbid in watching]
            if names:
                matched.append(normalize(row, names))
        # scanned is the whole feed, not the matches: "scanned 3 releases"
        # would describe the intersection, not the work.
        yield Batch(releases=matched, scanned=len(rows))

    def summary(self, args, run) -> str:
        plural = "s" if run.watching != 1 else ""
        return (f"Scanned {run.scanned} releases in a +/-{args.days} day window "
                f"around {dt.date.today().isoformat()}, watching "
                f"{run.watching} artist{plural}.")


def main() -> int:
    radar = ListenbrainzRadar()
    args = parser(radar, "Report new releases from watched artists.").parse_args()
    return execute(radar, args)


if __name__ == "__main__":
    sys.exit(main())
