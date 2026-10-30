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

import collections
import datetime as dt
import sys
import time
from collections.abc import Iterator

from core import favourites
from core.appearances import appearance_key, credits_for
from core.appearances import verdict as appearance_verdict
from core.qobuz import (
    PAUSE,
    STORE,
    album_detail,
    album_tracks,
    artist_releases,
    search_artists,
    search_tracks,
    store_cookies,
)
from core.radar import Batch, Radar, Release, execute, parser

# --- what you watch -------------------------------------------------------
# Qobuz artist IDs -- a third namespace, unrelated to MusicBrainz MBIDs and
# Apple artist IDs. Find one with:  ./radars/qobuz.py --find "Name"
# This literal is now only the FALLBACK, used when data/favourites.json
# carries no qobuz_id. That file is hand-edited on main; the stage that
# generated it is on the `ranking` branch (D41).
# watchlist() rather than ids_for(), because the run reports what it dropped:
# the counts travel into the JSON via report_extra() below.
WATCHLIST = favourites.watchlist("qobuz_id", {
    41620: "Jorge Drexler",
})
WATCHED_ARTISTS: dict[int, str] = WATCHLIST.ids

# Only report releases this recent, so a first run records the back catalogue
# silently instead of printing decades of it. 0 disables.
RECENT_DAYS = 90

# The credit pass's outcomes, in the order a candidate meets them. This is the
# funnel D42 measured, and the names are core/appearances.py's verdicts plus
# the two the radar itself decides: `unreadable` is an album/get that failed,
# `duplicate` is the same record under a second Qobuz id.
FUNNEL = ("appearance", "writer", "compilation", "retrospective", "absent",
          "redelivery", "duplicate", "unreadable")


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


def normalize(album: dict, label: str, because: str | None = None) -> Release:
    """One Qobuz album row as a Release.

    `because` is set only by the credit pass, where the row is somebody else's
    record and the report has to say whose credit put it there.
    """
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
        because=because,
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

    def __init__(self) -> None:
        # Why each credit-pass candidate stopped. Counted rather than summed to
        # one number, because the funnel IS the measurement D42 rests on: the
        # week "writer" stops being the biggest category is the week the role
        # denylist needs re-reading.
        self.funnel: collections.Counter[str] = collections.Counter()

    def add_arguments(self, parser) -> None:
        parser.add_argument("--find", metavar="NAME",
                            help="look up Qobuz artist ids by name and exit")
        parser.add_argument("--store", default=STORE,
                            help=f"storefront code (default: {STORE})")
        parser.add_argument("--no-credits", action="store_true",
                            help="skip the credit pass: report only releases the "
                                 "watched artists are billed on, which is what this "
                                 "radar did before D42. Measured at 1.3 minutes "
                                 "against 8 for 128 artists -- track/search is slow "
                                 "and runs twice per artist")

    def watching(self) -> dict:
        return WATCHED_ARTISTS

    def empty_message(self) -> str:
        return "WATCHED_ARTISTS is empty - run with --find \"Artist Name\" to get an id."

    def batches(self, args, watching: dict) -> Iterator[Batch]:
        """One Batch per watched ARTIST, from up to two passes over the store.

        Deliberately not one batch per call. The runner counts a Batch as a
        call and reports `fetched` of `watching` as artists, so yielding the
        credit pass separately made a 128-artist run say "256 of 128". The
        unit the run is about is the artist; `Batch.scanned` already exists for
        a batch that reads more rows than it returns, and the pacing the second
        pass needs is finer than one sleep per artist anyway, so it does its
        own.
        """
        cookies = store_cookies(args.store)
        # Dedup of appearances runs across the whole run, not per artist: the
        # same record reaches two watched artists as two separate credits.
        folded: set[str] = set()
        watched_ids = {str(i) for i in watching}
        cutoff = self.cutoff(args, dt.date.today())
        credits_wanted = not getattr(args, "no_credits", False)

        for artist_id, label in watching.items():
            name, albums, ok = artist_releases(artist_id, args.store, cookies)
            warnings = []
            if not ok:
                warnings.append(f"{label} ({artist_id}) lookup failed, skipped - "
                                "anything missed is reported next run")
            elif not albums:
                warnings.append(f"{label} ({artist_id}) returned no releases in the "
                                f"{args.store} store")
            releases = [normalize(a, name or label) for a in albums]
            scanned = None

            if credits_wanted:
                found, read, searched = self.appearances(
                    args, label, cookies, watched_ids, folded, cutoff)
                releases += found
                # Pass one examines exactly what it returns; pass two reads an
                # index of hundreds to keep none most weeks. Counting only the
                # kept rows would report a working run as a dead one.
                scanned = len(albums) + read
                if not searched:
                    warnings.append(f"{label} ({artist_id}) credit search failed, "
                                    "skipped - anything missed is reported next run")

            yield Batch(releases=releases, ok=ok, label=label, scanned=scanned,
                        warning="; ".join(warnings))

    def appearances(self, args, label: str, cookies: str, watched_ids: set[str],
                    folded: set[str], cutoff: str) -> tuple[list[Release], int, bool]:
        """(appearances, index rows read, the search worked) for one artist. D42.

        The reverse lookup `artist/get` cannot do: Qobuz files a release under
        an artist only when they are billed on the ALBUM, so a track-level
        feature never appears there. This searches their NAME in the track
        index instead, which is why most of the work is throwing things out.

        Two candidates are dropped before a request is spent on them, and both
        save money rather than judgement:

          * billed to somebody in `watching` -- the first pass already has it.
            This is D42's Tame Impala / Justice overlap, dropped here because
            it is cheaper than deduping a printed row later.
          * dated outside the window by the SEARCH payload. That date is a
            delivery date, and it errs in one direction only: never older than
            the real one. So this cannot drop a release that belongs in the
            window, though it lets re-deliveries through.

        Everything surviving costs one `album_detail`, which answers the two
        questions the search row cannot: the real date, and the credits. Every
        later outcome -- `redelivery`, the four verdicts, and the fold onto a
        record already reported under another Qobuz id -- is decided from that
        payload, so it is reached only after the request is spent.
        """
        rows, searched = search_tracks(label, args.store, cookies)

        candidates: dict[str, dict] = {}
        for track in rows:
            album = track.get("album") or {}
            album_id = str(album.get("id") or "")
            if not album_id or album_id in candidates:
                continue
            billed = {str((album.get("artist") or {}).get("id") or "")}
            billed |= {str(a.get("id") or "") for a in (album.get("artists") or [])}
            if billed & watched_ids:
                continue
            if cutoff and (album.get("release_date_original") or "")[:10] < cutoff:
                continue
            candidates[album_id] = track

        found: list[Release] = []
        for album_id in candidates:
            if self.pause:
                time.sleep(self.pause)
            detail, _ = album_detail(album_id, args.store, cookies)
            if detail is None:
                self.funnel["unreadable"] += 1
                continue
            # The real date, which is the whole reason this request was made.
            # Counted here rather than left to the runner's `old` verdict: the
            # search payload let it through on a DELIVERY date, so this is the
            # credit pass correcting its own candidate, and a funnel reading
            # "3 appearance" beside one printed row would be a lie. 866 of
            # 1163 candidates stopped here in D42.
            real_date = (detail.get("release_date_original")
                         or detail.get("release_date_stream") or "")[:10]
            if cutoff and real_date and real_date < cutoff:
                self.funnel["redelivery"] += 1
                continue
            title = detail.get("title") or ""
            # `artists` is empty on a compilation and the name is only in the
            # singular `artist`, so both are read -- see COMPILATION_ARTIST.
            artists = ", ".join(a.get("name") for a in (detail.get("artists") or [])
                                if a.get("name"))
            artists = artists or (detail.get("artist") or {}).get("name") or ""
            credited = credits_for(album_tracks(detail), label)
            why = appearance_verdict(title, credited, artists)
            # One candidate, one count. The dedup verdict is taken BEFORE
            # anything is counted, because incrementing `appearance` first and
            # `duplicate` after made the same record show up in two buckets
            # and the funnel stopped summing to the candidates read.
            if why == "appearance" and appearance_key(artists, title) in folded:
                why = "duplicate"
            self.funnel[why] += 1
            if why != "appearance":
                continue
            folded.add(appearance_key(artists, title))
            # The billed credit if there is one, so the report says
            # "FeaturedArtist" rather than whichever track came back first.
            best = next((c for c in credited if c.billed), credited[0])
            # `artists` as the label, not the watched name: normalize() uses
            # it only as the artist fallback, and on a record somebody else
            # made the artist column has to say who made it.
            found.append(normalize(detail, artists or label,
                                   because=f"{label} - {best.describe()}"))

        return found, len(rows), searched

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
        if self.funnel:
            line += f"\nCredit pass: {self.funnel_line()}."
        return line

    def funnel_line(self) -> str:
        """Where the credit pass's candidates went, in the funnel's own order.

        Fixed order rather than Counter.most_common, so two runs read the same
        way and a change in the shape is visible rather than re-sorted away.
        """
        return ", ".join(f"{self.funnel[name]} {name}" for name in FUNNEL if
                         self.funnel.get(name))

    def report_extra(self, args) -> dict:
        extra: dict = {"store": args.store}
        # Only when the run is actually watching the list this breakdown
        # describes. tests/conftest.py patches WATCHED_ARTISTS to a handful of
        # fixture ids, and "15 muted" printed beside three of them would be a
        # claim about a file the run never read. Same for the fallback list.
        if WATCHED_ARTISTS is WATCHLIST.ids and not WATCHLIST.fallback:
            extra["watchlist"] = WATCHLIST.report()
        if self.funnel:
            extra["credits"] = {name: self.funnel[name] for name in FUNNEL
                                if self.funnel.get(name)}
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
          f"data/favourites.json as qobuz_id:\n")
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
