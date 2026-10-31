#!/usr/bin/env python3
"""Turn a radar's JSON report into markdown. Formats, fetches nothing.

The reporting stage radars/itunes.py predicted: "if they are ever merged, the
shared part is the reporting stage, and this is the seam it would work
against." All three radars normalise releases into the same shape, so one
formatter serves all of them, and a radar never has to know what markdown is.

    ./radars/qobuz.py --all --days 10 --json data/releases.json
    ./radars/report.py data/releases.json
    ./radars/report.py data/releases.json --warnings warnings.txt > body.md

Optional fields are treated as optional: `hires` and `streamable` come from
Qobuz, `tracks` from everything, and a report missing them still formats.

The body is the records: one table of what the watched artists released, one of
what they are credited on (D42), and nothing else. Every count about the run --
the release total, the watchlist exclusions, the shared note, the credit funnel
-- is plain text inside the collapsed `warnings` block, because the issue is
read on a phone and the first thing on the page should be a record rather than
arithmetic about the job that found it (D43). `Nothing new.` and the
incomplete-list warning stay in the body, and the docstrings on `run_lines` and
those two branches say why.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cell(text: str) -> str:
    """A pipe inside a cell would break the table, so escape it."""
    return str(text).replace("|", "\\|")


def badges(release: dict) -> str:
    """The small print: length, quality, availability -- whatever is present."""
    bits = []
    if release.get("tracks"):
        bits.append(f"{release['tracks']} tr")
    if release.get("hires"):
        bits.append("hi-res")
    if release.get("streamable") is False:
        bits.append("not streamable")
    return " · ".join(bits)


#: The exclusions worth naming, and what to call them in prose. Ordered, so
#: two reports read the same way. `unresolved` is spelled out because "3
#: unresolved" means nothing to someone who has not read the resolver.
#:
#: The last three are the label radar's (D44). Zeros are left out, so every
#: other report keeps its shape.
EXCLUSIONS = (("muted", "muted by hand"), ("ended", "ended or split up"),
              ("unresolved", "with no id yet"),
              ("major", "too big to mean anything"),
              ("self", "an artist's own imprint"),
              ("thin", "with nothing of yours on them"))


def watchlist_line(info: dict) -> str:
    """The difference between the watchlist file and the run, in one sentence.

    Zeros are left out: "0 muted, 0 ended" is noise, and this line exists
    because a mute used to be invisible -- the issue said "146 of 146 artists"
    and the 26 it had dropped appeared nowhere. Returns "" when there is
    nothing to account for, which is also what a radar that reports no
    watchlist at all gets.
    """
    parts = [f"{info[key]} {label}" for key, label in EXCLUSIONS if info.get(key)]
    if info.get("collapsed"):
        # Not an exclusion: two entries, one artist. Named so the arithmetic
        # between `entries` and `ids` closes.
        parts.append(f"{info['collapsed']} sharing an id")
    if not parts:
        return ""
    return (f"Watching {info.get('ids', 0)} of {info.get('entries', 0)} "
            f"on the list: {', '.join(parts)}.")


def table(releases: list[dict], credit: bool = False) -> str:
    """One markdown table of releases, with or without the credit column.

    The header differs by one column rather than two tables' worth of
    formatting, because the rows are the same Release shape either way -- the
    credit pass finds releases, not a different kind of thing.
    """
    who = " credit |" if credit else ""
    head = [f"| date | type | artist | release |{who} | id |",
            "|---|---|---|---|---|---|" + ("---|" if credit else "")]
    rows = []
    for release in releases:
        # The radar flags anything dated after the run as upcoming; it
        # cannot be recomputed here without assuming today is the run day.
        date = release.get("date", "????-??-??")
        if release.get("upcoming"):
            date += " *(upcoming)*"
        because = f" {cell(release.get('because', ''))} |" if credit else ""
        rows.append(
            f"| {date} | {release.get('type', '?')} | {cell(release.get('artist', '?'))} "
            f"| {cell(release.get('title', '(untitled)'))} |{because} {badges(release)} "
            f"| `{release.get('id', '')}` |"
        )
    return "\n".join(head + rows)


def to_markdown(report: dict, warnings: str = "") -> str:
    releases = report.get("releases") or []
    watching = report.get("watching") or 0
    fetched = report.get("fetched", watching)
    source = report.get("source", "radar")
    # What this radar counts. `artists` is the default, so only the label
    # radar has to say anything.
    unit = report.get("unit", "artists")
    store = report.get("store")
    # No markdown: the only place this is printed now is inside a fenced block,
    # where backticks would render as backticks.
    where = f"{store} store" if store else source

    # Two kinds of row, and they answer different questions. A release without
    # `because` is one a watched artist is billed on -- the thing this radar
    # has always reported. One WITH it is somebody else's record that credits
    # them, which needs the credit printed beside it or the artist column reads
    # as a stranger (D42). Split rather than mixed, because a reader scanning
    # for "what did my artists put out" should not have to filter by eye.
    billed = [r for r in releases if not r.get("because")]
    credited = [r for r in releases if r.get("because")]

    # The body is the records and nothing else. Every count the report used to
    # open with is bookkeeping about the RUN rather than about the music, and
    # it pushed the first row of the table below the fold -- so it moves into
    # the warnings block, which is collapsed but one click away. Nothing is
    # dropped: a number that stops being reported stops being re-measured, and
    # the funnel in particular only earns its keep by being checked (D42).
    lines: list[str] = []

    if billed:
        lines += ["", table(billed)]
    elif not credited:
        lines += ["", "Nothing new."]

    if credited:
        lines += ["", f"**{len(credited)} credited appearance"
                      f"{'s' if len(credited) != 1 else ''}** on other artists' "
                      "releases.", "", table(credited, credit=True)]

    # Stays in the body, deliberately. This is not a count, it is a caveat
    # about whether the list above is the whole answer, and a reader who never
    # opens the warnings still has to see it.
    if report.get("failed"):
        lines += ["", f"⚠ {report['failed']} of {watching} {unit} could not be fetched, "
                      "so this list is incomplete."]

    bookkeeping = run_lines(report, billed, fetched, watching, where, unit, credited)
    folded = "\n".join(bookkeeping) + ("\n\n" + warnings.rstrip()
                                       if warnings.strip() else "")
    lines += ["", "<details><summary>warnings</summary>", "", "```",
              folded, "```", "", "</details>"]

    lines += ["", f"<sub>{source} · generated {report.get('generated', '?')}</sub>"]
    return "\n".join(lines).lstrip("\n") + "\n"


def run_lines(report: dict, billed: list[dict], fetched: int, watching: int,
              where: str, unit: str = "artists",
              credited: list[dict] | None = None) -> list[str]:
    """What the run was, for the collapsed block. Counts, not music.

    Plain text rather than markdown: it goes inside a fenced code block, so a
    bolded headline would render as asterisks and a backticked store code as
    backticks.
    """
    # Counted on the rows this sentence is ABOUT. The credit pass adds rows the
    # watched artists did not release, and folding them in would quietly
    # restate what "9 new releases from 128 artists" has meant in every issue
    # so far.
    # The label radar watches labels, so every row it reports is somebody
    # else's record and this would open on "0 new releases". It counts the
    # credited rows instead; `unit` is absent from every other report.
    counted = billed if unit == "artists" else (credited or [])
    noun = "new release" if unit == "artists" else "credited release"
    out = [f"{len(counted)} {noun}{'s' if len(counted) != 1 else ''} from "
           f"{fetched} of {watching} {unit} in the {where} "
           f"({report.get('window', 'unknown window')})."]

    watchlist = watchlist_line(report.get("watchlist") or {})
    if watchlist:
        out.append(watchlist)

    shared = report.get("shared")
    if shared:
        out.append(f"{shared} release{'s' if shared != 1 else ''} "
                   f"{'were' if shared != 1 else 'was'} credited to more than one "
                   "artist you watch, and "
                   f"{'are' if shared != 1 else 'is'} listed once.")

    funnel = report.get("credits") or {}
    if funnel:
        counted = ", ".join(f"{count} {name}" for name, count in funnel.items())
        out.append(f"credit candidates: {counted}")

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="JSON written by a radar's --json")
    parser.add_argument("--warnings", type=Path,
                        help="a file of stderr output to fold in, collapsed")
    args = parser.parse_args()

    if not args.report.exists():
        sys.exit(f"no such report: {args.report}")
    try:
        report = json.loads(args.report.read_text())
    except json.JSONDecodeError as error:
        sys.exit(f"{args.report} is not valid JSON: {error}")

    warnings = ""
    if args.warnings and args.warnings.exists():
        warnings = args.warnings.read_text()

    print(to_markdown(report, warnings), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
