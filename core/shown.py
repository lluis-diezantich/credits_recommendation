"""What a list claimed, and when -- the file that will settle D29.

Four ranking strategies and now a similarity baseline all make predictions
nobody can check, because nothing scores this list. The only way to fix that
is to write down what each one showed BEFORE the listening that would confirm
it arrives, which is what D11 did for the radar and what this does here.

One file, `data/shown.json`, shared by every source. That is the whole point:
a hit rate is only a comparison if the co-appearance list and the
similar-artist list are scored the same way, from the same record, over the
same window.

Plumbing, so the arithmetic is here and the SQL is not: `hit_rate` takes a
callable that answers "was this person played after this date", and the stage
that has a store open supplies it.
"""
from __future__ import annotations

import json
from pathlib import Path

FILE = "shown.json"
VERSION = 1


def path(directory: Path) -> Path:
    return directory / FILE


def load(directory: Path) -> list[dict]:
    """Every run on file, oldest first. An unreadable file is no runs.

    A file somebody hand-edited into another shape is not a reason to crash,
    but it IS a reason not to append to whatever is there -- see `append`.
    """
    try:
        blob = json.loads(path(directory).read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    runs = blob.get("runs") if isinstance(blob, dict) else None
    return runs if isinstance(runs, list) else []


def entry(source: str, shown: str, rows, limit: int) -> dict:
    """One run's record: the source, the date, and what it put in front of you.

    `rows` are ranked dicts carrying at least `person_key` and `name`, and
    optionally `sort_key` -- the score the ordering actually used, kept so a
    later read reports that number rather than recomputing it from a store
    that has since changed.
    """
    top = []
    for position, row in enumerate(rows[:limit], 1):
        key = row.get("sort_key")
        top.append({
            "rank": position,
            "person_key": row["person_key"],
            "name": row["name"],
            "score": [round(float(part), 3) for part in key] if key else None,
            "seeds": row.get("seeds"),
        })
    return {"shown": shown, "source": source, "candidates": len(rows),
            "top": top}


def append(directory: Path, run: dict) -> int:
    """Add one run and return how many are on file."""
    runs = load(directory)
    runs.append(run)
    path(directory).write_text(
        json.dumps({"version": VERSION, "runs": runs}, indent=2,
                   ensure_ascii=False) + "\n")
    return len(runs)


def hit_rate(runs, played_after) -> dict[str, tuple[int, int, int]]:
    """source -> (runs, names shown, names played since).

    `played_after(person_key, date)` answers whether the listening arrived
    AFTER the run that claimed the name. Without that condition the log would
    score itself on listening that predated the claim, which is hindsight
    rather than evidence.

    A name shown twice by one source counts once: the question is whether the
    recommendation worked, not how often it was repeated.
    """
    out: dict[str, tuple[int, int, int]] = {}
    seen: dict[str, set[str]] = {}
    hits: dict[str, set[str]] = {}
    counts: dict[str, int] = {}
    for run in runs:
        source = run.get("source") or run.get("strategy") or "?"
        counts[source] = counts.get(source, 0) + 1
        for row in run.get("top") or []:
            key = row["person_key"]
            seen.setdefault(source, set()).add(key)
            if played_after(key, run["shown"]):
                hits.setdefault(source, set()).add(key)
    for source, names in seen.items():
        out[source] = (counts[source], len(names),
                       len(hits.get(source, set())))
    return out
