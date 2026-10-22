#!/usr/bin/env python3
"""Who the seeds have made records WITH, in sentences.

Reads `data/music.db` and nothing else -- no network, no API key, no cache.
Everything it prints is a row somebody can go and check, which is the point of
a credits-based recommendation: the reason is verifiable.

    ./stages/co_artists.py                   # unheard, both seeds
    ./stages/co_artists.py --seed 41620      # one seed
    ./stages/co_artists.py --all             # include artists you already play
    ./stages/co_artists.py --json            # for anything downstream

Measured 59% already-played for Drexler and 40% for Perez Cruz, against 13-16%
for the crew graph -- docs/adr/D14. The ones you have NOT played are what this
prints by default.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys

from core.explain import co_artist_sentence
from core.paths import DATA
from policy import MADE_TOGETHER, nameable_roles, why_not_a_co_artist

# The provenances worth counting, as a SQL list. Built from policy so the
# filter here and the labelling in discover.py cannot drift apart.
TOGETHER = ", ".join(f"'{p}'" for p in sorted(MADE_TOGETHER))

# `albums` counts every record the two are printed on; seed_records +
# their_records counts the ones somebody HOLDS. The difference is a
# various-artists record, which is nobody's and was being reported as a
# collaboration -- 20 of Bjork's 35 co-artists came off "Army Of Me" alone
# (D24). The ordering moves to the same number for the same reason: ranking by
# `albums` would still put a remix compilation above a real record.
ROWS = f"""
SELECT c.seed_qobuz_id, s.name AS seed, c.person_key, c.name,
       c.seed_records, c.their_records, c.last_seen,
       c.seed_records + c.their_records AS together,
       (SELECT COUNT(*) FROM listens l WHERE l.artist_key = c.person_key) AS plays
FROM co_artists c JOIN seeds s USING (seed_qobuz_id)
WHERE (:seed IS NULL OR c.seed_qobuz_id = :seed)
  AND EXISTS (SELECT 1 FROM co_artist_albums a
              WHERE a.seed_qobuz_id = c.seed_qobuz_id
                AND a.person_key = c.person_key
                AND a.provenance IN ({TOGETHER}))
ORDER BY s.name, together DESC, c.last_seen DESC
"""
#        ^ the seed FIRST, so the report groups. The print loop writes a header
#        whenever the seed changes, and a purely global order made the same
#        seed's header appear once per run of its rows -- five seeds interleaved
#        printed "Björk" four separate times. Grouping is this ORDER BY and
#        nothing else; there is no nested loop to keep in step with it.
#
#        Alphabetical between seeds, which is arbitrary but stable: ranking the
#        GROUPS wants the cross-seed score that todo.md step 3 is about, and
#        inventing a worse one here would be in its way.

# The roles a person holds on the records they share with the seed, and the
# tracks they hold them on. Scoped by co_artist_albums so a role earned on one
# seed's record is never reported under the other's.
EVIDENCE = f"""
SELECT cr.role, COUNT(DISTINCT cr.track_id) AS tracks
FROM co_artist_albums a
JOIN credits cr ON cr.person_key = a.person_key AND cr.album_id = a.album_id
WHERE a.seed_qobuz_id = ? AND a.person_key = ?
  AND a.provenance IN ({TOGETHER})
GROUP BY cr.role ORDER BY tracks DESC
"""

# The record to name. Prefer one the seed is a guest on -- that direction is
# the stronger claim, since it is the seed choosing to appear on someone
# else's album -- then the most recent. Never a record nobody holds: naming
# "Army Of Me" as the album two artists made together is the junk row at its
# most convincing.
EXAMPLE = f"""
SELECT title, date FROM co_artist_albums
WHERE seed_qobuz_id = ? AND person_key = ?
  AND provenance IN ({TOGETHER})
ORDER BY CASE provenance WHEN 'guest' THEN 0 ELSE 1 END, date DESC LIMIT 1
"""


# Every role each co-artist holds on the records they share with the seed, for
# the one question the sentence cannot answer: did they do anything musical?
# "Liniers, Designer" is billed on a Drexler live record because he draws on
# stage during the show.
ROLES_HELD = f"""
SELECT a.seed_qobuz_id, a.person_key, cr.role
FROM co_artist_albums a
JOIN credits cr ON cr.person_key = a.person_key AND cr.album_id = a.album_id
WHERE a.provenance IN ({TOGETHER})
GROUP BY a.seed_qobuz_id, a.person_key, cr.role
"""


def describe(con: sqlite3.Connection, row: sqlite3.Row) -> dict:
    """One co-artist, with the evidence behind the sentence kept beside it."""
    key, seed_id = row["person_key"], row["seed_qobuz_id"]
    credits = con.execute(EVIDENCE, (seed_id, key)).fetchall()
    named = nameable_roles([c["role"] for c in credits])
    tracks = max((c["tracks"] for c in credits if c["role"] in named), default=0)
    example = con.execute(EXAMPLE, (seed_id, key)).fetchone()
    return {
        "seed": row["seed"], "seed_qobuz_id": seed_id,
        "person_key": key, "name": row["name"],
        "on_seeds_records": row["seed_records"],
        "on_their_records": row["their_records"],
        "roles": named, "tracks": tracks, "plays": row["plays"],
        "last_seen": row["last_seen"],
        "why": co_artist_sentence(
            row["name"], row["seed"], row["seed_records"], row["their_records"],
            tracks=tracks, roles=named,
            example=(example["title"], example["date"]) if example else None,
            plays=row["plays"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(DATA / "music.db"))
    parser.add_argument("--seed", type=int, help="one seed's Qobuz id")
    parser.add_argument("--all", action="store_true",
                        help="include artists you already play (hidden by default)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(ROWS, {"seed": args.seed}).fetchall()
    except sqlite3.OperationalError as exc:
        raise SystemExit(f"{args.db}: {exc} - run ./stages/load.py first") from exc

    held: dict[tuple, list[str]] = {}
    for r in con.execute(ROLES_HELD):
        held.setdefault((r["seed_qobuz_id"], r["person_key"]), []).append(r["role"])

    def why(row: sqlite3.Row) -> str | None:
        return why_not_a_co_artist(
            row["person_key"], held.get((row["seed_qobuz_id"],
                                         row["person_key"])))

    # Before the counts, not after: a billing with nothing musical behind it,
    # or nothing but a remix, is not a co-appearance to report the total of
    # either. On stderr so --json stays parseable, and grouped by reason
    # because reporting them all as "not an artist" said that about
    # Gesaffelstein, who is one.
    dropped: dict[str, list[str]] = {}
    kept = []
    for row in rows:
        reason = why(row)
        if reason:
            dropped.setdefault(reason, []).append(row["name"])
        else:
            kept.append(row)
    rows = kept
    for reason, names in sorted(dropped.items()):
        unique = sorted(set(names))
        print(f"{len(unique)} dropped as {reason}: " + ", ".join(unique),
              file=sys.stderr)

    out = [describe(con, r) for r in rows if args.all or not r["plays"]]
    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    if not out:
        # Two ways to empty now, and they mean opposite things: an empty list
        # because you play everybody is a result, an empty one because nothing
        # survived the filters is a corpus with no co-appearance in it.
        print("nothing to show - "
              + ("every co-artist is one you already play" if rows else
                 "no co-appearance here is a record somebody holds"))
        return 0
    seed = None
    for item in out:
        if item["seed"] != seed:
            seed = item["seed"]
            print(f"\n{seed}\n{'-' * len(seed)}")
        print(f"  {item['name']}")
        print(f"    {item['why']}")
    heard = sum(1 for r in rows if r["plays"])
    print(f"\n{len(out)} artists, from {len(rows)} co-appearances "
          f"({heard} already played, {'shown' if args.all else 'hidden'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
