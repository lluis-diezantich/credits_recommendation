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
EXCLUSIONS = (("muted", "muted by hand"), ("ended", "ended or split up"),
              ("unresolved", "with no id yet"))


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


def to_markdown(report: dict, warnings: str = "") -> str:
    releases = report.get("releases") or []
    watching = report.get("watching") or 0
    fetched = report.get("fetched", watching)
    source = report.get("source", "radar")
    store = report.get("store")
    where = f"`{store}` store" if store else source

    head = (f"**{len(releases)} new release{'s' if len(releases) != 1 else ''}** from "
            f"{fetched} of {watching} artists in the {where} "
            f"({report.get('window', 'unknown window')}).")

    lines = [head]
    watchlist = watchlist_line(report.get("watchlist") or {})
    if watchlist:
        lines += ["", watchlist]

    shared = report.get("shared")
    if shared:
        lines += ["", f"{shared} release{'s' if shared != 1 else ''} "
                      f"{'were' if shared != 1 else 'was'} credited to more than one "
                      "artist you watch, and "
                      f"{'are' if shared != 1 else 'is'} listed once."]

    if releases:
        lines += ["", "| date | type | artist | release | | id |", "|---|---|---|---|---|---|"]
        for release in releases:
            # The radar flags anything dated after the run as upcoming; it
            # cannot be recomputed here without assuming today is the run day.
            date = release.get("date", "????-??-??")
            if release.get("upcoming"):
                date += " *(upcoming)*"
            lines.append(
                f"| {date} | {release.get('type', '?')} | {cell(release.get('artist', '?'))} "
                f"| {cell(release.get('title', '(untitled)'))} | {badges(release)} "
                f"| `{release.get('id', '')}` |"
            )
    else:
        lines += ["", "Nothing new."]

    if report.get("failed"):
        lines += ["", f"⚠ {report['failed']} of {watching} artists could not be fetched, "
                      "so this list is incomplete."]

    if warnings.strip():
        lines += ["", "<details><summary>warnings</summary>", "", "```",
                  warnings.rstrip(), "```", "", "</details>"]

    lines += ["", f"<sub>{source} · generated {report.get('generated', '?')}</sub>"]
    return "\n".join(lines) + "\n"


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
