"""The radar loop, once: tell me what I have not been told yet.

Four scripts in radars/ grew the same main(): load what you watch, fetch from
one source, normalise the rows, subtract the state file, filter by date, print,
record. They had drifted on the parts that matter rather than the parts that
do not. radars/qobuz.py learned that nothing from anybody is a BROKEN run
rather than a quiet week; radars/itunes.py never did, so an Apple outage
reports "Nothing new." and looks correct, every Friday, forever. Only qobuz
grew --json, so only qobuz could be formatted by radars/report.py and posted
as an issue.

What lives here is everything that was the same: the seen-diff, the date
window, the within-run dedup, the broken-run guard, --all, --dry-run, --json,
the state write, the exit code. What stays in a radar is only what is really
different about its source -- where the ids come from, how to fetch, and how to
turn one of its rows into a Release.

So the gain is not the line count. It is that a lesson learned in one radar is
from now on learned by all of them, and that a fifth source is a fetch function
rather than another 250-line script to keep in step with three others.

radars/remezcla.py is deliberately NOT here. It pages a blog by curator, has no
artist ids at all, and emits picks plus a pile of untitled rows: the three
things this module factors out are the three things it does not have. An
abstraction that fits three sources of four is doing its job, and forcing the
fourth one in is how these go bad.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from core.paths import DATA
from core.state import load_seen, save_seen


@dataclass(frozen=True)
class Release:
    """One release, in the shape every radar reports and report.py formats.

    `kind` is written as "type" on the wire. `type` shadows a builtin and is a
    poor attribute name, but radars/report.py and every report already written
    use the key "type", and renaming a field in files on disk to tidy an
    attribute is not a trade worth making. row() does that translation and is
    the only place that knows about it.

    The optional fields are genuinely optional rather than defaulted to
    something false: Qobuz knows whether a release is hi-res, Apple does not,
    and None says "no idea" where False would claim "no it is not".
    """

    id: str
    date: str
    kind: str
    artist: str
    title: str
    source: str
    tracks: int = 0
    hires: bool | None = None
    streamable: bool | None = None
    url: str | None = None

    def row(self) -> dict:
        """The JSON shape. Absent knowledge is absent, not false."""
        row = {"date": self.date, "type": self.kind, "artist": self.artist,
               "title": self.title, "id": self.id, "source": self.source,
               "tracks": self.tracks}
        if self.hires is not None:
            row["hires"] = self.hires
        if self.streamable is not None:
            row["streamable"] = self.streamable
        if self.url:
            row["url"] = self.url
        return row


@dataclass
class Batch:
    """One call to a source: what came back, and whether it worked.

    `ok=False` means the fetch failed. An empty `releases` with ok=True means
    the call succeeded and found nothing. Collapsing those two into "no rows"
    is exactly the mistake the broken-run guard exists to catch, so they stay
    separate all the way through.
    """

    releases: list[Release] = field(default_factory=list)
    ok: bool = True
    label: str = ""
    warning: str = ""
    #: Rows the call looked at, when that differs from the records it produced.
    #: A per-artist source examines exactly what it returns, so it leaves this
    #: alone; a feed source reads thousands of rows and keeps the handful
    #: crediting someone you watch, and "scanned 3" would misreport the run.
    scanned: int | None = None

    @property
    def examined(self) -> int:
        return len(self.releases) if self.scanned is None else self.scanned


@dataclass
class Run:
    """What happened, for the summary line, the JSON report and the exit code."""

    watching: int = 0
    calls: int = 0
    scanned: int = 0
    failed: int = 0
    empty: int = 0
    shared: int = 0
    releases: list[Release] = field(default_factory=list)
    # Every id this run laid eyes on, reported or not.
    everything: set[str] = field(default_factory=set)

    @property
    def fetched(self) -> int:
        return self.calls - self.failed


def verdict(release: Release, seen: set[str], collected: set[str],
            cutoff: str, keep_types: set[str] | None) -> str:
    """Why a release is or is not news: new, seen, shared, kind or old.

    Pure on purpose -- this is the actual judgement in a radar run, and it is
    worth being able to test it without a network, a clock or a state file.

    The order is load-bearing. `shared` must be checked before `kind` and
    `old`, or a release credited to two watched artists is counted as filtered
    the second time rather than as a duplicate, and the "listed once" note in
    the report goes quiet.
    """
    if release.id in seen:
        return "seen"
    if release.id in collected:
        return "shared"
    if keep_types is not None and release.kind not in keep_types:
        return "kind"
    if cutoff and release.date < cutoff:
        return "old"
    return "new"


class Radar(ABC):
    """A source. Implement watching() and batches(); inherit the rest.

    Everything below is overridable, and the defaults are the behaviour the
    three migrated radars already had -- a new source should need to set `name`
    and little else.
    """

    name: str = "radar"
    #: Release kinds worth reporting. None keeps everything.
    keep_types: set[str] | None = {"Album", "EP", "Single"}
    #: Seconds between calls. A few hundred back-to-back requests is what
    #: provokes the 5xx in the first place.
    pause: float = 0.0
    default_days: int = 90
    days_help: str = "only report releases this recent; 0 disables"
    #: Record every id SCANNED, not just the ones reported, so that the date
    #: cutoff does not let an old release resurface the week it falls out of
    #: the window. False where the source IS a window rather than a catalogue:
    #: see radars/listenbrainz.py, where recording an unmatched release would
    #: hide it for good if you later started watching that artist.
    record_scanned: bool = True
    #: Nothing from anybody is a broken run, not a quiet week. Off for sources
    #: that answer with a window, where zero rows is a legitimate answer and
    #: indistinguishable from a failure.
    guard_empty_run: bool = True

    @property
    def state_file(self) -> Path:
        return DATA / f"{self.name}_seen.json"

    # -- what a source must say -------------------------------------------

    @abstractmethod
    def watching(self) -> dict:
        """{id: label} of what to watch. Empty means misconfigured, and exits."""

    @abstractmethod
    def batches(self, args, watching: dict) -> Iterator[Batch]:
        """Fetch, in however many calls the source needs. One Batch per call."""

    # -- what a source may say --------------------------------------------

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:  # noqa: B027
        """Source-specific flags, e.g. --store.

        Not abstract, and empty on purpose: most sources add no flags, and
        making them write `pass` to say so is noise.
        """

    def empty_message(self) -> str:
        return f"nothing to watch - see {self.name} in data/favourites.json."

    def window(self, args) -> str:
        return f"last {args.days} days" if args.days > 0 else "all dates"

    def cutoff(self, args, today: dt.date) -> str:
        if args.days <= 0:
            return ""
        return (today - dt.timedelta(days=args.days)).isoformat()

    def badges(self, release: Release) -> str:
        return f"{release.tracks} tr" if release.tracks else ""

    def describe(self, release: Release, today: dt.date) -> str:
        # The radar flags anything dated after the run as upcoming: a pre-order
        # would otherwise read as something you had somehow missed.
        upcoming = " [upcoming]" if release.date > today.isoformat() else ""
        badges = self.badges(release)
        suffix = f" ({badges})" if badges else ""
        return (f"{release.date}  {release.kind:<7}{upcoming:<11} "
                f"{release.artist} - {release.title}{suffix}")

    def summary(self, args, run: Run) -> str:
        plural = "s" if run.watching != 1 else ""
        return (f"Scanned {run.scanned} releases from {run.fetched} of "
                f"{run.watching} artist{plural} ({self.window(args)}).")

    def report_extra(self, args) -> dict:
        """Extra keys for the JSON report, e.g. {"store": args.store}."""
        return {}

    def broken_run_message(self, run: Run) -> str:
        """Why the run is being called broken. Overridable for vocabulary.

        A source that calls once per artist should say "artists" and name what
        came back empty; a feed source would be lying if it did. The runner
        decides WHETHER the run is broken, and the source says it in its own
        words.
        """
        return (f"nothing came back from any of {run.calls} calls "
                f"({run.failed} failed, {run.empty} returned nothing)")


def parser(radar: Radar, description: str) -> argparse.ArgumentParser:
    """The flags every radar has, plus whatever the source adds.

    Separate from execute() so a radar can own a mode that exits before any
    fetch happens -- radars/qobuz.py --find is an artist-id lookup, and it
    should not have to pretend to be a run to get at the parsed arguments.
    """
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--days", type=int, default=radar.default_days,
                    help=f"{radar.days_help} (default: {radar.default_days})")
    ap.add_argument("--all", action="store_true",
                    help="report everything, ignoring the state file")
    ap.add_argument("--dry-run", action="store_true",
                    help="report without recording anything")
    ap.add_argument("--json", metavar="PATH",
                    help="also write the report as JSON, for radars/report.py to format")
    ap.add_argument("--run-log", metavar="PATH",
                    help="append one JSON line describing this run, for telling a quiet "
                         "week from a broken one over time")
    radar.add_arguments(ap)
    return ap


def log_run(path: Path, radar: Radar, args, run: Run, reported: int) -> None:
    """Append one line about this run. Never fails the run.

    A single radar run cannot tell a quiet week from a broken one -- that is
    only visible as a shape over time, which is why the summary line alone was
    never enough. Scanned dropping to a tenth while every call still "succeeds"
    is the signal, and nothing in the report shows it.

    JSON lines, append-only, because that is the cheapest thing that is also a
    table later: one COPY statement moves this into Postgres the day there is a
    Postgres to move it into.
    """
    row = {
        "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "source": radar.name,
        "window": radar.window(args),
        "watching": run.watching,
        "calls": run.calls,
        "failed": run.failed,
        "empty": run.empty,
        "scanned": run.scanned,
        "reported": reported,
        "shared": run.shared,
        "dry_run": bool(args.dry_run),
        "stateless": bool(args.all),
    }
    try:
        with path.open("a") as handle:
            handle.write(json.dumps(row) + "\n")
    except OSError as error:
        # A log that cannot be written is not worth losing a report over.
        print(f"warning: could not append to {path} ({error})", file=sys.stderr)


def execute(radar: Radar, args) -> int:
    """One radar run: fetch, diff, report, record. Returns the exit code."""
    watching = radar.watching()
    if not watching:
        sys.exit(radar.empty_message())

    today = dt.date.today()
    cutoff = radar.cutoff(args, today)
    seen = set() if args.all else load_seen(radar.state_file)

    run = Run(watching=len(watching))
    # Ids collected THIS run. `seen` holds previous runs only, so without this
    # a release credited to two watched artists is fetched once per artist and
    # reported twice, identically -- invisible with one artist watched, routine
    # with ninety.
    collected: set[str] = set()

    for batch in radar.batches(args, watching):
        if run.calls and radar.pause:
            time.sleep(radar.pause)
        run.calls += 1
        run.scanned += batch.examined
        if not batch.ok:
            run.failed += 1
        elif not batch.examined:
            run.empty += 1
        if batch.warning:
            print(f"warning: {batch.warning}", file=sys.stderr)

        for release in batch.releases:
            if not release.id:
                continue
            if radar.record_scanned:
                run.everything.add(release.id)
            outcome = verdict(release, seen, collected, cutoff, radar.keep_types)
            if outcome == "shared":
                run.shared += 1
            if outcome != "new":
                continue
            collected.add(release.id)
            run.releases.append(release)
            if not radar.record_scanned:
                run.everything.add(release.id)

    # Nothing at all from anybody is a broken run, and it arrives two ways: the
    # service refusing the caller outright, or answering 200 with an empty
    # discography for everyone. The second is the dangerous one, because every
    # call "succeeds" -- the report would say "Nothing new.", with the warnings
    # folded into a block nobody opens, and would say it every week. A real
    # quiet week still returns catalogue; it is the DATE FILTER that empties
    # the list, not the fetch, so this cannot fire on one.
    if radar.guard_empty_run and run.calls and run.failed + run.empty == run.calls:
        print(f"{radar.broken_run_message(run)} - treating this as a broken run, "
              "not an empty one.", file=sys.stderr)
        return 1

    ordered = sorted(run.releases, key=lambda r: r.date)

    if args.json:
        # The reporting stage's input: no formatting decisions, just what was
        # found and what the run was.
        report = {
            "generated": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "source": radar.name,
            "window": radar.window(args),
            "days": args.days,
            "watching": run.watching,
            "fetched": run.fetched,
            "failed": run.failed,
            "scanned": run.scanned,
            "shared": run.shared,
            # Stamped here, not in the formatter: only the run knows what
            # "today" was, and a report can be formatted days later.
            "releases": [dict(r.row(), upcoming=r.date > today.isoformat())
                         for r in ordered],
            **radar.report_extra(args),
        }
        Path(args.json).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {args.json} ({len(ordered)} releases)", file=sys.stderr)

    if args.run_log:
        log_run(Path(args.run_log), radar, args, run, reported=len(ordered))

    print(radar.summary(args, run))
    if run.failed:
        plural = "s" if run.failed != 1 else ""
        print(f"{run.failed} lookup{plural} could not be fetched; their releases are "
              "not recorded as seen, so a later run will report them.")

    if not ordered:
        print("Nothing new.")
    else:
        print()
        for release in ordered:
            print(f"  {radar.describe(release, today)}")
        print()
        print(f"{len(ordered)} new release{'s' if len(ordered) != 1 else ''}.")
        if run.shared:
            print(f"({run.shared} were credited to more than one artist you watch, "
                  "and are listed once.)")

    if not args.dry_run and not args.all and run.everything:
        save_seen(radar.state_file, seen | run.everything)

    return 0
