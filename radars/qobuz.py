#!/usr/bin/env python3
"""A personal new-release radar, backed by the Qobuz API. No login required.

Third of three, alongside listenbrainz.py and itunes.py. Same job, same output
shape -- and this one is the authoritative answer about what you can actually
play, because it is the catalogue you subscribe to.

Approach borrowed from pawllo01/qobuz-artist-discography (MIT): the store-front
API accepts a public app id plus the cookies any /discover page hands out, with
NO account, NO token and NO request signature. An earlier version of this script
tried to log in with email+password and burned a lot of time on it; that turned
out to be unnecessary.

The run itself -- the seen-diff, the date window, --json, the state write, the
broken-run guard -- is core/radar.py, shared with the other two. What is left
here is what is specific to Qobuz: the id namespace, inferring a release type
from track count, and the hi-res/streamable badges only this source knows.

    ./radars/qobuz.py --find "Jorge Drexler"   # look up an artist id
    ./radars/qobuz.py                          # new releases, last 90 days
    ./radars/qobuz.py --days 0                 # no date cutoff
    ./radars/qobuz.py --all                    # ignore the state file
    ./radars/qobuz.py --dry-run                # report, record nothing
    ./radars/qobuz.py --store es-es            # a different storefront
"""

from __future__ import annotations

import sys
from collections.abc import Iterator

from core import favourites
from core.qobuz import PAUSE, STORE, artist_releases, search_artists, store_cookies
from core.radar import Batch, Radar, Release, execute, parser

# --- what you watch -------------------------------------------------------
# Qobuz artist IDs -- a third namespace, unrelated to MusicBrainz MBIDs and
# Apple artist IDs. Find one with:  ./radars/qobuz.py --find "Name"
# This literal is now only the FALLBACK, used when data/favourites.json
# carries no qobuz_id. Generate that file with ./stages/favourites.py.
# watchlist() rather than ids_for(), because the run reports what it dropped:
# the counts travel into the JSON via report_extra() below.
WATCHLIST = favourites.watchlist("qobuz_id", {
    41620: "Jorge Drexler",
})
WATCHED_ARTISTS: dict[int, str] = WATCHLIST.ids

# Only report releases this recent, so a first run records the back catalogue
# silently instead of printing decades of it. 0 disables.
RECENT_DAYS = 90


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


def normalize(album: dict, label: str) -> Release:
    """One Qobuz album row as a Release."""
    date = (album.get("release_date_original")
            or album.get("release_date_stream")
            or "")[:10] or "????-??-??"
    artists = [a.get("name") for a in (album.get("artists") or []) if a.get("name")]
    version = (album.get("version") or "").strip()
    return Release(
        id=str(album.get("id") or ""),
        date=date,
        kind=classify(album),
        artist=", ".join(artists) or label,
        title=f"{album.get('title') or '(untitled)'}" + (f" ({version})" if version else ""),
        source="qobuz",
        tracks=album.get("tracks_count") or 0,
        hires=bool(album.get("hires")),
        streamable=bool(album.get("streamable")),
    )


class QobuzRadar(Radar):
    name = "qobuz"
    # Qobuz does NOT return release_type on this endpoint, so the type is
    # inferred from track count -- see classify(). These are the inferred
    # labels to report.
    keep_types = {"Album", "EP", "Single"}
    # Pre-orders are dropped, not badged. This radar answers "what can I play
    # now", and a dated row you cannot hear is noise in that answer -- it
    # reappears on its own in the week it is released. D33.
    keep_upcoming = False
    pause = PAUSE
    default_days = RECENT_DAYS

    def add_arguments(self, parser) -> None:
        parser.add_argument("--find", metavar="NAME",
                            help="look up Qobuz artist ids by name and exit")
        parser.add_argument("--store", default=STORE,
                            help=f"storefront code (default: {STORE})")

    def watching(self) -> dict:
        return WATCHED_ARTISTS

    def empty_message(self) -> str:
        return "WATCHED_ARTISTS is empty - run with --find \"Artist Name\" to get an id."

    def batches(self, args, watching: dict) -> Iterator[Batch]:
        cookies = store_cookies(args.store)
        for artist_id, label in watching.items():
            name, albums, ok = artist_releases(artist_id, args.store, cookies)
            warning = ""
            if not ok:
                warning = (f"{label} ({artist_id}) lookup failed, skipped - "
                           "anything missed is reported next run")
            elif not albums:
                warning = (f"{label} ({artist_id}) returned no releases in the "
                           f"{args.store} store")
            yield Batch(releases=[normalize(a, name or label) for a in albums],
                        ok=ok, label=label, warning=warning)

    def badges(self, release: Release) -> str:
        bits = []
        if release.tracks:
            bits.append(f"{release.tracks} tr")
        if release.hires:
            bits.append("hi-res")
        if release.streamable is False:
            bits.append("not streamable")
        return ", ".join(bits)

    def summary(self, args, run) -> str:
        plural = "s" if run.watching != 1 else ""
        line = (f"Scanned {run.scanned} releases from {run.fetched} of "
                f"{run.watching} artist{plural} in the {args.store} store "
                f"({self.window(args)}).")
        # The exclusions, for a local run. The issue gets the same numbers
        # through report_extra() and radars/report.py.
        if WATCHED_ARTISTS is WATCHLIST.ids and WATCHLIST.excluded:
            dropped = ", ".join(f"{n} {reason}"
                                for reason, n in WATCHLIST.counts.items()
                                if reason != "watched" and n)
            line += f"\nNot watched: {dropped}."
        return line

    def report_extra(self, args) -> dict:
        extra: dict = {"store": args.store}
        # Only when the run is actually watching the list this breakdown
        # describes. tests/conftest.py patches WATCHED_ARTISTS to a handful of
        # fixture ids, and "15 muted" printed beside three of them would be a
        # claim about a file the run never read. Same for the fallback list.
        if WATCHED_ARTISTS is WATCHLIST.ids and not WATCHLIST.fallback:
            extra["watchlist"] = WATCHLIST.report()
        return extra

    def broken_run_message(self, run) -> str:
        plural = "s" if run.calls != 1 else ""
        return (f"nothing came back from any of {run.calls} artist{plural} "
                f"({run.failed} failed, {run.empty} returned an empty discography)")


def find(name: str, store: str) -> int:
    """Print Qobuz artist ids matching a name. Costs one request, changes nothing.

    core.qobuz.search_artists, not a local copy: this was the project's THIRD
    autosuggest. It warns and returns [] where the local version exited, so a
    failed request now prints its own reason above the "no match" line instead
    of in place of it.
    """
    found = search_artists(name, store)
    if not found:
        print(f"No Qobuz artist matched {name!r}.")
        return 0
    print(f"Qobuz artists matching {name!r} - put one in "
          f"data/favourites.json as qobuz_id, or run:\n"
          f"  ./stages/favourites.py --review\n")
    for artist in found[:15]:
        print(f"  {str(artist.get('id')):>10}  {artist.get('name')}"
              f"   ({artist.get('albumsCount') or 0} albums)")
    return 0


def main() -> int:
    radar = QobuzRadar()
    args = parser(radar, "Report new releases from watched artists via Qobuz.").parse_args()
    if args.find:
        return find(args.find, args.store)
    return execute(radar, args)


if __name__ == "__main__":
    sys.exit(main())
