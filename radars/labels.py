#!/usr/bin/env python3
"""Report new releases on the LABELS your artists release on, kept only where
somebody you follow is credited on them.

The other three radars ask a source what a PERSON released. This one asks what
a label put out, and then reads the credits to decide what to keep -- because
the person this is really about is a producer, and nothing in Qobuz files a
release under a producer. `core/labels.py` has the measurement and the
judgement; this file is the fetch loop and the printing.

Two requests shape the cost. One `label/get` per label returns the catalogue
newest-first, so the window is a prefix and a page is a date range. Everything
that survives the window and is not already billed to an artist you watch costs
one `album_detail`, which answers the two questions the catalogue row cannot:
the real date, and the credits.

    ./radars/labels.py                          # the Friday scan
    ./radars/labels.py --days 14 --dry-run
    ./radars/labels.py --credit production,engineering
    ./radars/labels.py --discover               # build data/labels.json
    ./radars/labels.py --people-from "data/discovery_*.json"

Both builder modes write a file you then hand-edit, the same arrangement as
data/favourites.json: `"watch": false` mutes a label or a person and nothing
re-resolves it. Neither is part of a run -- see --discover's own help for what
it costs.
"""
from __future__ import annotations

import collections
import datetime as dt
import glob
import json
import sys
import time
from collections.abc import Iterator

from core import favourites
from core.appearances import appearance_key
from core.labels import (
    FAMILIES,
    FEED_KINDS,
    FEED_VERDICTS,
    LABELS_FILE,
    MAJOR_CATALOGUE,
    PEOPLE_FILE,
    VERDICTS,
    credits_by,
    earned,
    family_of,
    fold_editions,
)
from core.labels import labels as load_labels
from core.labels import people as load_people
from core.labels import verdict as credit_verdict
from core.names import normalise
from core.qobuz import (
    LABEL_MAX_PAGES,
    LABEL_PAGE,
    PAUSE,
    STORE,
    album_detail,
    album_tracks,
    artist_releases,
    label_catalogue,
    store_cookies,
)
from core.radar import Batch, Radar, Release, execute, parser

# Imported rather than copied. Both radars normalise the same Qobuz album row,
# and `core/credits.py` exists because the last function that got written twice
# drifted -- discover.py scored collaborator names as instruments for as long
# as both copies lived.
from radars.qobuz import classify, normalize

WATCHLIST = load_labels()
WATCHED_LABELS: dict[int, str] = WATCHLIST.ids
# The artists you watch, so a producer who IS one of them is not looked for:
# they produce their own records and the Friday radar reports those. Read here
# and passed in, rather than inside core/labels.py, so that module stays a
# function of its arguments.
YOURS = frozenset(normalise(entry["name"]) for entry in favourites.load()
                  if entry.get("name"))
PEOPLE_LIST = load_people(yours=YOURS)
PEOPLE: dict[str, str] = PEOPLE_LIST.names
WORKED_FOR: dict[str, list[str]] = PEOPLE_LIST.worked_for

# Shorter than the Qobuz radar's 90. That radar reports a watched artist's own
# releases, where months of back catalogue on a first run is a one-off cost
# worth paying; here the same window is sixty labels' worth of catalogue and
# every row of it costs an album_detail.
RECENT_DAYS = 14

#: Rows one label may contribute to a run. The archived pipeline's roadmap
#: wanted this as "diversification: not ten records by the same producer", and
#: the first full run of this radar is the measurement: of 212 labels scanned,
#: exactly one produced more than two rows, and it produced five -- an act
#: releasing singles on a label named after its own producer. So a cap of 2
#: costs three rows from that label and nothing at all from the other 211,
#: measured 2026-10-31 over one run.
#:
#: A cap rather than another gate, because the problem is not that the label is
#: wrong -- the credits are real -- it is that a weekly report has to be read.
PER_LABEL = 2

#: How many of YOUR artists to name beside a producer before saying "+N more".
#: The names are the reason the row is in the report at all, so three of them
#: earn their width; the fourth onwards is reassurance rather than information.
NAME_AT_MOST = 3

#: The outcomes a candidate can stop at, in the order it meets them.
#: core/labels.py's verdicts plus the three this file decides: `unreadable` is
#: an album/get that failed, `redelivery` is a catalogue date that was newer
#: than the record, and `duplicate` is the same release under a second id.
FUNNEL = (*VERDICTS, "redelivery", "duplicate", "unreadable", "capped")


def label_of(detail: dict) -> str:
    """The label name off an album_detail payload."""
    return (detail.get("label") or {}).get("name") or ""


class LabelRadar(Radar):
    name = "labels"
    keep_types = {"Album", "EP", "Single"}
    # D33, same as the Qobuz radar: this answers "what can I play now", and a
    # dated row you cannot hear is noise in that answer.
    keep_upcoming = False
    pause = PAUSE
    default_days = RECENT_DAYS

    #: FALSE, and this radar is the first catalogue source where that is right.
    #: `record_scanned` exists so a release cannot resurface the week it falls
    #: out of the window, and the Qobuz radar sets it because what it scans is
    #: a watched artist's discography -- a fixed question. What this scans is a
    #: label catalogue, but what it ASKS is "does this credit anybody in
    #: data/producers.json", and that list grows. Recording a release that
    #: matched nobody would hide it for good the day you add the producer it
    #: credits, which is radars/listenbrainz.py's argument arriving at a
    #: catalogue source for a different reason.
    record_scanned = False
    #: True, unlike the other source that sets record_scanned False. A label
    #: catalogue always returns rows, so nothing from any of sixty labels is an
    #: outage rather than a quiet week -- the date filter empties the report,
    #: never the fetch.
    guard_empty_run = True

    def __init__(self) -> None:
        self.funnel: collections.Counter[str] = collections.Counter()
        self.catalogues: dict[str, int] = {}
        #: Feed rows kept, counted after the per-label cap. Apart from the
        #: funnel, whose outcomes sum to the candidates read: a row can be
        #: `absent` AND on the feed.
        self.feed = 0

    def add_arguments(self, parser) -> None:
        parser.add_argument("--store", default=STORE,
                            help=f"storefront code (default: {STORE})")
        parser.add_argument("--credit", default="production", metavar="FAMILIES",
                            help="role families that count as news, comma separated "
                                 f"from {','.join(FAMILIES)} (default: production). "
                                 "Adding engineering roughly triples the rows and "
                                 "most of them are mixing: the archived pipeline "
                                 # Doubled for argparse, which reads % as a
                                 # format spec in a help string and raises.
                                 "measured 73%% of its referrals arriving that way")
        parser.add_argument("--feed", choices=("albums", "all", "off"),
                            default="albums",
                            help="which releases to report that nobody you follow "
                                 "made: albums and EPs (default), everything, or "
                                 "nothing. Measured over a fortnight on these "
                                 "labels: 34 a week, 65, and 0. Credited releases "
                                 "are reported whatever this says")
        parser.add_argument("--max-pages", type=int, default=LABEL_MAX_PAGES,
                            metavar="N",
                            help="catalogue pages to read per label before giving up "
                                 f"on reaching the window (default: {LABEL_MAX_PAGES}, "
                                 f"{LABEL_PAGE} releases each). A 90-day backfill "
                                 "needs more than a 14-day run, and a label whose "
                                 "window does not fit is silently truncated")
        parser.add_argument("--per-label", type=int, default=PER_LABEL, metavar="N",
                            help="report at most N releases per label, newest first; "
                                 f"0 is no cap (default: {PER_LABEL}). One label "
                                 "produced 5 of the first run's 13 rows -- a "
                                 "self-releasing producer credits themselves on "
                                 "everything they put out, and the catalogue gate "
                                 "cannot see it")
        parser.add_argument("--discover", action="store_true",
                            help="rebuild data/labels.json by reading every watched "
                                 "artist's discography and counting the labels they "
                                 "release on, then exit. One request per artist "
                                 f"(~{len(favourites.load()) or 'n'} of them), plus "
                                 "one per label whose album rows carried no catalogue "
                                 "size -- 0 of 254 on the first run, but the fallback "
                                 "is there because the gate cannot read a missing "
                                 "number. Overwrites nothing you hand-edited: a label "
                                 "already in the file keeps its watch flag")
        parser.add_argument("--people-from", metavar="GLOB",
                            help="rebuild data/producers.json from discovery_*.json "
                                 "files written by stages/discover.py on the `ranking` "
                                 "branch, then exit. Offline")

    def watching(self) -> dict:
        return WATCHED_LABELS

    def empty_message(self) -> str:
        return (f"no labels to scan - run with --discover to build {LABELS_FILE.name}, "
                "or check that its entries are not all muted or over "
                f"{MAJOR_CATALOGUE} releases.")

    def families(self, args) -> set[str]:
        """The role families this run counts as news, validated against FAMILIES."""
        asked = {part.strip().lower() for part in args.credit.split(",") if part.strip()}
        unknown = asked - set(FAMILIES)
        if unknown:
            sys.exit(f"unknown credit {'families' if len(unknown) > 1 else 'family'} "
                     f"{', '.join(sorted(unknown))} - pick from {', '.join(FAMILIES)}")
        return asked

    def batches(self, args, watching: dict) -> Iterator[Batch]:
        """One Batch per LABEL, from one catalogue read plus a detail per candidate.

        One batch per label rather than per call, for the reason D42 records:
        the runner counts a batch as a call and reports `fetched` of `watching`,
        so a second batch would make a 60-label run say "from 120 of 60".
        """
        if not PEOPLE:
            print(f"warning: {PEOPLE_FILE.name} is empty, so nothing can be credited - "
                  "run --people-from to build it", file=sys.stderr)

        cookies = store_cookies(args.store)
        families = self.families(args)
        # EVERY entry with a Qobuz id, muted ones included -- not
        # `favourites.ids_for`, which drops them. A mute means you do not want
        # that artist's records, and the Friday radar honours it; reading the
        # watched-only list here let two Carin León releases in through his
        # producer, which is the one place a mute could be undone without
        # anybody choosing to undo it.
        watched_artists = {str(entry["qobuz_id"]) for entry in favourites.load()
                           if entry.get("qobuz_id")}
        # Across the whole run, not per label: a distributor delivers the same
        # record to two of them, and `core.radar` dedups on id and cannot see it.
        folded: set[str] = set()
        cutoff = self.cutoff(args, dt.date.today())

        for label_id, name in watching.items():
            label, catalogue, total, ok = label_catalogue(
                label_id, args.store, cookies, cutoff, args.max_pages)
            warnings = []
            if not ok:
                warnings.append(f"{name} ({label_id}) catalogue read failed, skipped - "
                                "anything missed is reported next run")
            self.catalogues[label or name] = total

            candidates = []
            for album in fold_editions(catalogue):
                date = (album.get("release_date_original") or "")[:10]
                if cutoff and date < cutoff:
                    continue
                billed = {str((album.get("artist") or {}).get("id") or "")}
                billed |= {str(a.get("id")) for a in (album.get("artists") or [])}
                # Cheaper here than deduping a printed row later, and it is the
                # same drop D42 makes: the Friday radar's first pass has it.
                if billed & watched_artists:
                    self.funnel["yours"] += 1
                    continue
                candidates.append(album)

            found = [r for r in (self.examine(args, album, cookies, families,
                                              folded, watched_artists, cutoff)
                                 for album in candidates) if r is not None]
            # Capped per GROUP, so a label with a busy week cannot push its one
            # credited release out of the report with its own feed rows.
            credited = [r for r in found if r.because]
            feed = self.cap(args, [r for r in found if not r.because])
            # Counted AFTER the cap, so the summary cannot claim rows the
            # report does not hold -- the same discipline the funnel keeps.
            # The runner drops pre-orders after this (D33), so this is still
            # an upper bound on what is printed.
            self.feed += len(feed)
            releases = self.cap(args, credited) + feed
            yield Batch(releases=releases, ok=ok, label=label or name,
                        scanned=len(catalogue), warning="; ".join(warnings))

    def cap(self, args, rows: list[Release]) -> list[Release]:
        """The newest `--per-label` of one group, since a report has to be read."""
        rows.sort(key=lambda release: release.date, reverse=True)
        limit = getattr(args, "per_label", 0)
        if limit and len(rows) > limit:
            self.funnel["capped"] += len(rows) - limit
            return rows[:limit]
        return rows

    def examine(self, args, album: dict, cookies: str, families: set[str],
                folded: set[str], watched_artists: set[str],
                cutoff: str) -> Release | None:
        """One candidate, at the cost of one album_detail: a Release or nothing.

        The detail is what decides everything -- the credits are not in a
        catalogue row at all, and the date in one is a DELIVERY date that errs
        new, so a re-delivered 2019 record reaches here looking like news. D42
        measured that at 866 of 1163 candidates, which is why the funnel counts
        `redelivery` separately rather than letting the runner call it `old`.
        """
        if self.pause:
            time.sleep(self.pause)
        album_id = str(album.get("id") or "")
        detail, _ = album_detail(album_id, args.store, cookies)
        if detail is None:
            self.funnel["unreadable"] += 1
            return None

        real_date = (detail.get("release_date_original")
                     or detail.get("release_date_stream") or "")[:10]
        if cutoff and real_date and real_date < cutoff:
            self.funnel["redelivery"] += 1
            return None

        title = detail.get("title") or ""
        # The repackage marker lives in `version`, NOT in the title: Qobuz
        # returns `La Quiniela del Día` with `version: "Remastered 2026"`, and
        # the first run's reissue test read the title alone and printed it.
        # radars/qobuz.py's normalize() is what joins the two for display, so
        # the judgement has to join them itself.
        version = (detail.get("version") or "").strip()
        full_title = f"{title} ({version})" if version else title
        # `artists` comes back EMPTY on a compilation and the name is only in
        # the singular field, so both are read -- core/appearances.py learned
        # this when a 32-track Various Artists record printed as a Drexler album.
        artists = ", ".join(a.get("name") for a in (detail.get("artists") or [])
                            if a.get("name"))
        artists = artists or (detail.get("artist") or {}).get("name") or ""
        billed = {str(a.get("id")) for a in (detail.get("artists") or [])}
        billed |= {str((detail.get("artist") or {}).get("id") or "")}

        credited = credits_by(album_tracks(detail), PEOPLE)
        why = credit_verdict(billed, watched_artists, credited, families, full_title)
        # The dedup verdict is taken BEFORE anything is counted: incrementing
        # `credit` first and `duplicate` after made one record land in two
        # buckets and the funnel stopped summing to the candidates read.
        if why == "credit" and appearance_key(artists, title) in folded:
            why = "duplicate"
        self.funnel[why] += 1
        if why != "credit":
            # A real new release on a label you follow, which nobody you follow
            # made. Reported with no reason attached beyond the label (D45).
            if (args.feed != "off" and why in FEED_VERDICTS
                    and (args.feed == "all" or classify(detail) in FEED_KINDS)):
                return normalize(detail, artists or label_of(detail))
            return None

        folded.add(appearance_key(artists, title))
        # The person who EARNED the verdict, not the one with the most tracks:
        # core/labels.py's `earned` has the three rows that taught this. The
        # verdict guarantees there is one, and the fallback is there so a
        # future verdict that does not cannot crash a run.
        best = earned(credited, families) or credited[0]
        roles = [role for role in best.roles if family_of(role) in families]
        label_name = label_of(detail)
        because = f"{best.name} - {', '.join(roles) or best.describe()}"
        if label_name:
            because += f" (on {label_name})"
        # WHOSE records of yours they have made. Without this the credit column
        # is a stranger's name and the reader has to remember why they care:
        # "James Ford - Producer" against "James Ford - Producer, works with
        # Björk, Little Simz".
        for_you = WORKED_FOR.get(best.name) or []
        if for_you:
            named = ", ".join(for_you[:NAME_AT_MOST])
            more = len(for_you) - NAME_AT_MOST
            because += f", works with {named}" + (f" +{more} more" if more > 0 else "")
        return normalize(detail, artists or label_name, because=because)

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
                f"{run.watching} label{plural} ({self.window(args)}).")
        if WATCHED_LABELS is WATCHLIST.ids and WATCHLIST.excluded:
            left = ", ".join(f"{n} {reason}"
                             for reason, n in sorted(WATCHLIST.excluded.items()))
            line += f" {WATCHLIST.total - len(WATCHED_LABELS)} labels left out ({left})."
        if PEOPLE is PEOPLE_LIST.names and PEOPLE_LIST.excluded:
            left = ", ".join(f"{n} {reason}"
                             for reason, n in sorted(PEOPLE_LIST.excluded.items()))
            line += (f" Looking for {len(PEOPLE_LIST.kept)} of "
                     f"{PEOPLE_LIST.total} people ({left}).")
        if self.funnel:
            line += f" Credits: {self.funnel_line()}."
        if self.feed:
            line += f" {self.feed} on the feed."
        return line

    def funnel_line(self) -> str:
        """The funnel in the order a candidate meets it, zeroes left out."""
        return ", ".join(f"{self.funnel[k]} {k}" for k in FUNNEL if self.funnel[k])

    def report_extra(self, args) -> dict:
        extra: dict = {
            "store": args.store,
            # What the run counted, so report.py says "212 labels" rather than
            # the "artists" every other source counts. Absent from the other
            # radars' reports, which is why the formatter defaults it.
            "unit": "labels",
            "credit": sorted(self.families(args)),
            "feed": args.feed,
            # The people BLOCK, not a count: which entries the file lost and
            # why is the same question the label watchlist answers, and a run
            # that looked for 430 of 1,538 names should say so.
            "people": PEOPLE_LIST.report() if PEOPLE is PEOPLE_LIST.names
                      else {"kept": len(PEOPLE)},
            "catalogues": self.catalogues,
        }
        # Only when the run is watching the file this breakdown describes:
        # tests patch WATCHED_LABELS to a couple of fixture ids, and "27 major"
        # printed beside two of them would be a claim about a file the run
        # never read. Same guard as radars/qobuz.py.
        if WATCHED_LABELS is WATCHLIST.ids:
            extra["watchlist"] = WATCHLIST.report()
        if self.funnel:
            extra["credits"] = {name: self.funnel[name] for name in FUNNEL
                                if self.funnel.get(name)}
        return extra

    def broken_run_message(self, run) -> str:
        return (f"no catalogue came back from any of {run.calls} labels "
                f"({run.failed} failed, {run.empty} returned nothing)")


def discover(store: str) -> int:
    """Rebuild data/labels.json from the labels your artists release on.

    The analogue of `radars/qobuz.py --find`: a mode that exits before any run,
    because what it writes is a file you then read and edit. One request per
    watched artist, and the counts it records -- how many of your releases came
    out on the label, how many of your artists use it, and the catalogue size
    the gate reads -- are what `core.labels.watch_verdict` decides on.

    Hand-edits survive: a `watch` flag already in the file is carried over, for
    the same reason core/favourites.py keeps a manual qobuz_id.
    """
    existing = {int(e["id"]): e for e in json.loads(LABELS_FILE.read_text()).get("labels", [])
                if e.get("id")} if LABELS_FILE.exists() else {}
    watching = favourites.ids_for("qobuz_id", {})
    if not watching:
        sys.exit("nothing in data/favourites.json to read labels from.")

    cookies = store_cookies(store)
    year = (dt.date.today() - dt.timedelta(days=365)).isoformat()
    found: dict[int, dict] = {}
    # Through core.names: the label is spelled `Jose Gonzalez` and the artist
    # `José González`, and a plain fold left his own imprint in the scan. Scoped
    # to the watched artists -- on the producer list it would miss `Sumi Ani`
    # against `Ani Sumiati` and drop `Raso Estudio` (341 releases) for sharing
    # a name, which `--per-label` handles instead.
    names = {normalise(name) for name in watching.values()}
    failed = 0

    for artist_id, name in watching.items():
        _label, albums, ok = artist_releases(artist_id, store, cookies)
        if not ok:
            failed += 1
            continue
        for album in albums:
            if (album.get("release_date_original") or "")[:10] < year:
                continue
            label = album.get("label") or {}
            if not isinstance(label, dict) or not label.get("id"):
                continue
            entry = found.setdefault(int(label["id"]), {
                "id": int(label["id"]), "name": label.get("name") or "",
                "yours": 0, "artists": [], "catalogue": label.get("albums_count") or 0,
            })
            entry["yours"] += 1
            if name not in entry["artists"]:
                entry["artists"].append(name)
        time.sleep(PAUSE)

    for entry in found.values():
        # A label named after one of your artists is their own imprint. Recorded
        # as a FACT here and judged in core/labels.py, the same split as
        # favourites.json's `ended` against `watch`.
        entry["self_release"] = normalise(entry["name"]) in names
        entry["catalogue"] = entry["catalogue"] or _catalogue_size(entry["id"], store, cookies)
        if entry["id"] in existing and "watch" in existing[entry["id"]]:
            entry["watch"] = existing[entry["id"]]["watch"]

    ordered = sorted(found.values(), key=lambda e: (-e["yours"], e["name"]))
    LABELS_FILE.write_text(json.dumps({
        "generated": dt.date.today().isoformat(),
        "note": ('hand-edits are kept: set "watch": false to stop scanning a label. '
                 "Labels over "
                 f"{MAJOR_CATALOGUE} releases and artists' own imprints are skipped "
                 "by core/labels.py without being removed from this file."),
        "labels": ordered,
    }, indent=2, ensure_ascii=False) + "\n")
    scanned = len(watching) - failed
    print(f"wrote {LABELS_FILE} - {len(ordered)} labels from {scanned} of "
          f"{len(watching)} artists" + (f", {failed} failed" if failed else ""))
    return 0


def _catalogue_size(label_id: int, store: str, cookies: str) -> int:
    """The catalogue size for a label whose album rows did not carry one."""
    time.sleep(PAUSE)
    _name, _rows, total, _ok = label_catalogue(label_id, store, cookies, max_pages=1)
    return total


def people_from(pattern: str) -> int:
    """Rebuild data/producers.json from discovery_*.json files. Offline.

    Those files are `stages/discover.py`'s output on the `ranking` branch: one
    per seed artist, listing every person credited on their records with the
    roles and the albums. D41 is the reason this reads them rather than
    importing the stage -- the walk belongs on that branch, and what main needs
    from it is a list of names.

    Keeps anyone with a production or engineering credit, records which of your
    artists they worked for, and carries a `watch` flag already in the file.
    """
    paths = sorted(glob.glob(pattern))
    if not paths:
        sys.exit(f"no files matched {pattern!r} - these are written by "
                 "stages/discover.py on the `ranking` branch.")
    existing = {e["name"]: e for e in json.loads(PEOPLE_FILE.read_text()).get("people", [])
                if e.get("name")} if PEOPLE_FILE.exists() else {}

    found: dict[str, dict] = {}
    for path in paths:
        blob = json.loads(open(path).read())
        seed = (blob.get("seed") or {}).get("name") or path
        for person in blob.get("people") or []:
            roles = person.get("roles") or {}
            kept = {role: n for role, n in roles.items()
                    if family_of(role) in {"production", "engineering"}}
            if not kept:
                continue
            entry = found.setdefault(person["key"], {
                "name": person.get("names", [person["key"]])[0],
                "names": person.get("names") or [], "roles": {}, "for": [],
                "albums": 0, "production": 0,
            })
            for role, n in kept.items():
                entry["roles"][role] = entry["roles"].get(role, 0) + n
            for album in person.get("albums") or []:
                held = {family_of(role) for role in album.get("roles") or []}
                if held & {"production", "engineering"}:
                    entry["albums"] += 1
                # Counted apart, because the thin test is about PRODUCTION
                # credits and `albums` folds engineering in with them -- which
                # is 615 of the file's 1,538 people, nearly all of them
                # mastering and mixing engineers.
                if "production" in held:
                    entry["production"] += 1
            if seed not in entry["for"]:
                entry["for"].append(seed)

    for entry in found.values():
        entry["roles"] = dict(sorted(entry["roles"].items(), key=lambda kv: -kv[1]))
        if entry["name"] in existing and "watch" in existing[entry["name"]]:
            entry["watch"] = existing[entry["name"]]["watch"]

    ordered = sorted(found.values(),
                     key=lambda e: (-e["production"], -e["albums"], e["name"]))
    PEOPLE_FILE.write_text(json.dumps({
        "generated": dt.date.today().isoformat(),
        "note": ('hand-edits are kept: set "watch": false to stop looking for '
                 "somebody. `albums` is how many records they hold a production or "
                 "engineering credit on across the discovery files read, and "
                 "`production` is how many of those are production -- the second is "
                 "what decides whether they are looked for at all."),
        "people": ordered,
    }, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {PEOPLE_FILE} - {len(ordered)} people from {len(paths)} discovery files")
    return 0


def main() -> int:
    radar = LabelRadar()
    args = parser(radar, "Report new releases on the labels your artists use, "
                         "where somebody you follow is credited.").parse_args()
    if args.discover:
        return discover(args.store)
    if args.people_from:
        return people_from(args.people_from)
    return execute(radar, args)


if __name__ == "__main__":
    raise SystemExit(main())
