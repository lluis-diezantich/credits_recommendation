#!/usr/bin/env python3
"""Rank the co-appearance candidates across every seed, under one strategy.

todo.md step 3. `co_artists.py` lists who a seed made records with, grouped by
seed and ordered inside each group; this asks the cross-seed question instead --
of everyone your artists have made records with, who is worth hearing first.

    ./stages/rank.py                         # the default strategy, unheard
    ./stages/rank.py --strategy taste
    ./stages/rank.py --compare breadth taste # what the choice actually changes
    ./stages/rank.py --list                  # the strategies and their claims
    ./stages/rank.py --log                   # record what this run showed
    ./stages/rank.py --score                 # did the logged names get played?
    ./stages/rank.py --markdown --log        # an issue body, and record it

Reads data/music.db and nothing else -- no network. The strategies are in
`policy.py` (D1) and the ordering is `core.rank` (D2); what lives here is the
SQL that builds a feature row and the printing.

WHY SEVERAL STRATEGIES. Not one of their weights is measured, because nothing
scores this list yet. --log writes what a run showed and --score asks, against
the listens that have arrived since, how many of them you played. Until that
has run for a while the ranking is a hypothesis with an order, and saying so
is the point of docs/adr/D29.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
from contextlib import closing

import policy
from core import rank, shown
from core.explain import cross_seed_sentence
from core.names import normalise
from core.paths import DATA
from policy import MADE_TOGETHER, nameable_roles, why_not_a_co_artist

TOGETHER = ", ".join(f"'{p}'" for p in sorted(MADE_TOGETHER))

LOG = shown.FILE

# One row per person, aggregated over every seed they connect to. The grain is
# the person, which is what makes this different from co_artists.py: `seeds` is
# the column D22's thesis rests on and the one a per-seed report cannot show.
ROWS = """
SELECT c.person_key,
       MIN(c.name) AS name,
       COUNT(DISTINCT c.seed_qobuz_id) AS seeds,
       (SELECT COUNT(DISTINCT a.album_id) FROM co_artist_albums a
        WHERE a.person_key = c.person_key
          AND a.provenance IN ('own', 'guest')) AS albums,
       GROUP_CONCAT(DISTINCT s.name) AS seed_names,
       SUM(c.seed_records) AS on_seeds,
       SUM(c.their_records) AS on_theirs,
       MIN(c.first_seen) AS first_seen,
       MAX(c.last_seen) AS last_seen,
       (SELECT COUNT(*) FROM listens l WHERE l.artist_key = c.person_key) AS plays
FROM co_artists c JOIN seeds s USING (seed_qobuz_id)
WHERE c.seed_records + c.their_records > 0
GROUP BY c.person_key
"""

# How much each seed is played. Joined in Python rather than in SQL because
# `listens.artist_key` is normalise(name) and `seeds.name` is the spelling
# Qobuz returned -- LOWER() does not bridge "Sílvia Pérez Cruz" to
# "silvia perez cruz", and a join that silently matches nothing would have
# made seed_plays zero for every accented seed and looked like a weight.

# Every role a candidate holds on the records they share with ANY seed, which
# is both the evidence for the sentence and the input to billed_as_musician.
ROLES = f"""
SELECT a.person_key, cr.role, COUNT(DISTINCT cr.track_id) AS tracks
FROM co_artist_albums a
JOIN credits cr ON cr.person_key = a.person_key AND cr.album_id = a.album_id
WHERE a.provenance IN ({TOGETHER})
GROUP BY a.person_key, cr.role
"""

# The record to name, per person: the strongest direction, then the most
# recent. Same rule as co_artists.py, across seeds rather than within one.
EXAMPLES = f"""
SELECT person_key, title, date, provenance FROM (
  SELECT person_key, title, date, provenance,
         ROW_NUMBER() OVER (
             PARTITION BY person_key
             ORDER BY CASE provenance WHEN 'guest' THEN 0 ELSE 1 END,
                      date DESC) AS n
  FROM co_artist_albums WHERE provenance IN ({TOGETHER})
) WHERE n = 1
"""


def candidates(con: sqlite3.Connection, today: dt.date) -> list[dict]:
    """Every co-artist as a feature row, with its roles and example record.

    The three read-side filters `co_artists.py` applies are applied here too,
    and for the same reason: a billing that is not an artist (D24), one that
    did nothing musical (D27) or one that only remixed (D30) is not a
    candidate to rank. None of these is hypothetical -- a channel, an
    illustrator and a remixer have each been at or near the top of this list.
    """
    dropped: dict[str, set[str]] = {}
    roles: dict[str, list[tuple[str, int]]] = {}
    for row in con.execute(ROLES):
        roles.setdefault(row["person_key"], []).append((row["role"], row["tracks"]))
    examples = {r["person_key"]: r for r in con.execute(EXAMPLES)}

    plays_by_seed: dict[str, int] = {}
    for row in con.execute("SELECT name FROM seeds"):
        plays_by_seed[row["name"]] = con.execute(
            "SELECT COUNT(*) FROM listens WHERE artist_key = ?",
            (normalise(row["name"]),)).fetchone()[0]

    out = []
    for row in con.execute(ROWS):
        key = row["person_key"]
        held = roles.get(key, [])
        reason = why_not_a_co_artist(key, [role for role, _ in held])
        if reason:
            dropped.setdefault(reason, set()).add(row["name"])
            continue
        named = nameable_roles([role for role, _ in held])
        features = rank.features(
            {**dict(row), "roles": named,
             "role_weight": max((policy.role_weight(r) for r in named),
                                default=0.0),
             "seed_plays": sum(plays_by_seed.get(n, 0)
                               for n in (row["seed_names"] or "").split(","))},
            today)
        features["tracks"] = max((n for role, n in held if role in named), default=0)
        features["example"] = examples.get(key)
        out.append(features)
    for reason, names in sorted(dropped.items()):
        print(f"{len(names)} dropped as {reason}: " + ", ".join(sorted(names)),
              file=sys.stderr)
    return out


def sentence(row: dict) -> str:
    """The row's own explanation, which is the product (D21).

    `core.explain.cross_seed_sentence` handles both arities, so a one-seed row
    reads exactly as `co_artists.py` renders it and a multi-seed row names how
    many of your artists and which.
    """
    example = row.get("example")
    return cross_seed_sentence(
        row["name"], (row["seed_names"] or "").split(","),
        row["on_seeds"], row["on_theirs"],
        tracks=row.get("tracks") or 0, roles=row["roles"],
        example=((example["title"], example["date"]) if example else None),
        plays=row["plays"])


def score_text(row: dict) -> str:
    """The key the ordering used, not a recomputed number.

    A lexicographic strategy has more than one term and printing only the
    first says "2.0" for every two-seed candidate, which hides the thing that
    actually separated them.
    """
    return " | ".join(f"{part:.3g}" for part in row["sort_key"])


def markdown(rows: list[dict], limit: int, source: str, total: int,
             today: dt.date) -> str:
    """The list as an issue body: the sentence is the content, not the score.

    A list rather than a table, because the sentence is the product (D21) and
    a table wide enough to hold one is unreadable on a phone. The score is in
    the provenance line at the bottom, where somebody checking the ordering
    will look for it and nobody else has to.

    NOT a workflow. The Friday radar posts from CI because its inputs are
    committed (data/favourites.json) and its source is a live API. This list
    is built from data/discovery_*.json and data/music.db, both gitignored,
    out of an 85 MB cache that is also not committed -- so there is nothing
    for a runner to read. Delivery is local until that changes, and the
    printed `gh` line is the whole of it.
    """
    out = [f"# Credits radar - {today.isoformat()}", "",
           f"{total} unheard artists your music has in common, "
           f"ranked by **{source}**. Every clause below is a stored row "
           "somebody can go and check.", ""]
    for position, row in enumerate(rows[:limit], 1):
        seeds = (row["seed_names"] or "").replace(",", ", ")
        out.append(f"{position}. **{row['name']}** - {sentence(row)}")
        out.append(f"   <sub>via {seeds} - score {score_text(row)}</sub>")
        out.append("")
    out += ["---", "",
            f"<sub>`stages/rank.py --strategy {source}`, "
            f"{total} candidates, top {min(limit, len(rows))} shown. "
            "Logged to `data/shown.json`; `--score` reads it back.</sub>"]
    return "\n".join(out)


def show(rows: list[dict], limit: int) -> None:
    for position, row in enumerate(rows[:limit], 1):
        seeds = (row["seed_names"] or "").replace(",", ", ")
        print(f"{position:>3}. {row['name']}   [{score_text(row)}]")
        print(f"     via {seeds}")
        print(f"     {sentence(row)}")


def write_log(directory, source: str, rows: list[dict], limit: int,
              today: dt.date) -> int:
    """Append what this run showed. Returns the number of runs on file.

    A committed file, the stance D11 took for the radar: the only way to learn
    whether a ranking was right is to have written down what it claimed BEFORE
    the listens that would confirm it arrived. `core.shown` owns the format,
    because stages/baseline.py writes to the same file and a hit rate is only a
    comparison if both sources are recorded identically.
    """
    return shown.append(directory, shown.entry(source, today.isoformat(),
                                               rows, limit))


def score_log(con: sqlite3.Connection, directory) -> int:
    """Per source: of the names it showed, how many were played since.

    The measurement every weight in policy's strategy block is waiting for,
    and the one that tells a credit graph from a similarity model.
    """
    runs = shown.load(directory)
    if not runs:
        print(f"no runs in {LOG} yet - run with --log first", file=sys.stderr)
        return 1

    def played_after(person_key: str, when: str) -> bool:
        return bool(con.execute(
            "SELECT 1 FROM listens WHERE artist_key = ? AND listened_date > ? "
            "LIMIT 1", (person_key, when)).fetchone())

    results = shown.hit_rate(runs, played_after)
    print(f"{len(runs)} run(s) on file\n")
    print(f"  {'source':<12} {'runs':>5} {'shown':>6} {'played since':>13}")
    for source, (count, names, hits) in sorted(results.items()):
        rate = f"{hits / names:.0%}" if names else "-"
        print(f"  {source:<12} {count:>5} {names:>6} {f'{hits} ({rate})':>13}")
    print("\nA name counts once per source, and only if it was played AFTER "
          "the run that showed it.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(DATA / "music.db"))
    parser.add_argument("--strategy", help="default: " + policy.DEFAULT_STRATEGY)
    parser.add_argument("--compare", nargs=2, metavar=("A", "B"),
                        help="two strategies, and what the choice changes")
    parser.add_argument("--list", action="store_true",
                        help="the strategies and the claim each one makes")
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--all", action="store_true",
                        help="include artists you already play")
    parser.add_argument("--log", action="store_true",
                        help=f"append what this run showed to data/{LOG}")
    parser.add_argument("--score", action="store_true",
                        help="per strategy, how many shown names were played since")
    parser.add_argument("--markdown", action="store_true",
                        help="the list as an issue body, for gh issue create")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.list:
        for name, fn in sorted(policy.RANKING_STRATEGIES.items()):
            claim = (fn.__doc__ or "").strip().splitlines()[0]
            default = "  (default)" if name == policy.DEFAULT_STRATEGY else ""
            print(f"  {name:<10} {claim}{default}")
        return 0

    with closing(sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        return report(con, args)


def report(con: sqlite3.Connection, args) -> int:
    """Everything that needs the store open, so main() can close it.

    Closed rather than left to the interpreter: this runs under pytest as well
    as from a shell, and a leaked read handle is a ResourceWarning per test.
    """
    if args.score:
        return score_log(con, DATA)

    today = dt.date.today()
    try:
        rows = candidates(con, today)
    except sqlite3.OperationalError as exc:
        raise SystemExit(f"{args.db}: {exc} - run ./stages/load.py first") from exc
    if not args.all:
        rows = [r for r in rows if not r["plays"]]

    if args.compare:
        left_name, right_name = args.compare
        left = rank.ranked(rows, policy.strategy(left_name))
        right = rank.ranked(rows, policy.strategy(right_name))
        moved = rank.rank_delta(left, right)
        print(f"{len(rows)} candidates, {left_name} vs {right_name}\n")
        print(f"  {'':>4} {'':>4}  {'moved':>6}  name")
        for row in moved[:args.top]:
            arrow = "up" if row["moved"] > 0 else "down"
            print(f"  {row['left']:>4} {row['right']:>4}  "
                  f"{abs(row['moved']):>5} {arrow:<4}  {row['name']}")
        unmoved = sum(1 for r in moved if not r["moved"])
        print(f"\n{unmoved} of {len(moved)} candidates do not move. "
              f"Columns are {left_name}'s rank, then {right_name}'s.")
        return 0

    name = args.strategy or policy.DEFAULT_STRATEGY
    ordered = rank.ranked(rows, policy.strategy(name))

    if args.markdown:
        print(markdown(ordered, args.top, name, len(ordered), today))
        print("\n# post it with:\n#   ./stages/rank.py --markdown --log "
              f"> body.md && gh issue create --title 'Credits radar "
              f"{today.isoformat()}' --body-file body.md", file=sys.stderr)
    elif args.json:
        # The sentence travels with the facts: it is the product, and a
        # consumer that had to rebuild it would need `example` too.
        print(json.dumps([{**{k: v for k, v in r.items() if k != "example"},
                           "why": sentence(r)}
                          for r in ordered[:args.top]],
                         indent=2, ensure_ascii=False, default=str))
    else:
        print(f"{len(ordered)} candidates by {name}, "
              f"{'all' if args.all else 'unheard only'}\n")
        show(ordered, args.top)

    if args.log:
        runs = write_log(DATA, name, ordered, args.top, today)
        print(f"\nlogged run {runs} to data/{LOG} - "
              "./stages/rank.py --score reads it back", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
