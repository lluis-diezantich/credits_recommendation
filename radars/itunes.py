#!/usr/bin/env python3
"""A personal new-release radar, backed by the iTunes Search API.

Companion to listenbrainz.py, which reads the ListenBrainz feed. That one is a
single global request filtered locally, and inherits MusicBrainz's coverage
gaps: it does not know about releases MusicBrainz has not registered yet, which
in practice means a lot of singles and a lot of non-Anglophone artists.

This one asks Apple about each watched artist directly. More requests, far
better coverage of what actually came out, but it can only ever tell you about
artists you have listed.

No API key and no auth. `requests` via core/http.py for the pooling and the
retry policy. The run itself is core/radar.py, shared with the other two --
which is how this radar acquired --json and the broken-run guard it had been
missing: an Apple outage used to report "Nothing new." and look correct.

    ./radars/itunes.py              # new releases from the last 90 days
    ./radars/itunes.py --days 365   # widen the reporting window
    ./radars/itunes.py --days 0     # no date cutoff (first run: whole discography)
    ./radars/itunes.py --all        # ignore the state file
    ./radars/itunes.py --dry-run    # report without recording anything
"""

from __future__ import annotations

import json
import sys
import urllib.parse
from collections.abc import Iterator

from core import favourites
from core.http import get as http_get
from core.radar import Batch, Radar, Release, execute, parser

# --- what you watch -------------------------------------------------------
# Apple artist IDs, which are NOT MusicBrainz MBIDs. This is deliberately a
# separate namespace (and a separate state file) from listenbrainz.py, so the
# two radars never have to agree about artist identity.
#
# To find an ID:
#   curl -s "https://itunes.apple.com/search?term=Jorge+Drexler&entity=musicArtist&limit=3" \
#     | python3 -m json.tool
# and take `artistId`.
# This literal is now only the FALLBACK, used when data/favourites.json
# carries no itunes_id. That file is hand-edited on main (D41).
WATCHED_ARTISTS: dict[int, str] = favourites.ids_for("itunes_id", {
    16421943: "Jorge Drexler",
})

# Apple's catalogue is territory-specific: the same artist returned 69 releases
# in the US store, 66 in ES, 69 in UY. If a release you expect is missing, try
# the artist's home storefront before assuming the API is at fault.
STOREFRONT = "US"

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
    status, body, _ = http_get(f"{LOOKUP_URL}?{query}", timeout=30,
                               user_agent=USER_AGENT, service="iTunes")
    if status != 200:
        raise RuntimeError(f"iTunes returned HTTP {status}")
    payload = json.loads(body)

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


def normalize(row: dict, label: str) -> Release:
    """One Apple result row as a Release.

    `hires` and `streamable` are left unset rather than False: Apple does not
    say, and core.radar.Release distinguishes "no" from "no idea".
    """
    return Release(
        id=str(row.get("collectionId") or ""),
        date=(row.get("releaseDate") or "")[:10] or "????-??-??",
        kind=classify(row),
        artist=row.get("artistName") or label,
        title=clean_title(row),
        source="itunes",
        tracks=row.get("trackCount") or 0,
    )


class ItunesRadar(Radar):
    name = "itunes"
    # Apple has no usable type field (`collectionType` is literally "Album"
    # even for a one-track single), so this is inferred -- see classify().
    keep_types = {"Album", "EP", "Single"}
    pause = REQUEST_PAUSE_SECONDS
    default_days = RECENT_DAYS

    def watching(self) -> dict:
        return WATCHED_ARTISTS

    def empty_message(self) -> str:
        return "WATCHED_ARTISTS is empty - add at least one Apple artist ID."

    def batches(self, args, watching: dict) -> Iterator[Batch]:
        for artist_id, label in watching.items():
            try:
                rows = fetch_artist_releases(artist_id)
            except (RuntimeError, json.JSONDecodeError) as error:
                # One artist failing should not lose the whole run.
                yield Batch(ok=False, label=label,
                            warning=f"{label} ({artist_id}) lookup failed: {error}")
                continue
            warning = "" if rows else (
                f"{label} ({artist_id}) returned no releases "
                f"- wrong ID, or nothing in the {STOREFRONT} store?")
            yield Batch(releases=[normalize(row, label) for row in rows],
                        label=label, warning=warning)

    def summary(self, args, run) -> str:
        plural = "s" if run.watching != 1 else ""
        return (f"Scanned {run.scanned} releases from {run.fetched} of "
                f"{run.watching} artist{plural} in the {STOREFRONT} store "
                f"({self.window(args)}).")

    def report_extra(self, args) -> dict:
        return {"store": STOREFRONT}

    def broken_run_message(self, run) -> str:
        plural = "s" if run.calls != 1 else ""
        return (f"nothing came back from any of {run.calls} artist{plural} "
                f"({run.failed} failed, {run.empty} returned no releases)")


def main() -> int:
    radar = ItunesRadar()
    args = parser(radar, "Report new releases from watched artists via iTunes.").parse_args()
    return execute(radar, args)


if __name__ == "__main__":
    sys.exit(main())
