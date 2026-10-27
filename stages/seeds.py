#!/usr/bin/env python3
"""Which artist to walk next, and why -- the input to discover.py.

The first four seeds were picked by hand, and two of them intersect with
nothing: Little Simz and Björk share no co-artist with each other or with the
Iberian pair, so "how many of your artists made a record with this person" is 1
for 97 of 99 rows and a cross-seed ranker has nothing to rank. A seed costs ~50
requests and ten minutes of reading its alias report, so this picks them by
rule instead -- `policy.seedable`, with the measurement behind both numbers.

    ./stages/seeds.py                    # the pool, in walk order
    ./stages/seeds.py --next 8           # the next eight, with their commands
    ./stages/seeds.py --all              # include the ones the rule rejects
    ./stages/seeds.py --json

Reads data/profile.json (the bands and the month counts), data/favourites.json
(the Qobuz id and the mbid a walk needs) and data/music.db (who is already a
co-artist, which decides the ORDER). Offline, no requests.

WHY THE ORDER IS NOT THE RULE. The rule says who is worth 50 requests; the
order says which 50 to spend first. An artist already seen as a co-artist of a
walked seed is a guaranteed intersection, so walking those first puts range
into the ranker's main column after two or three walks instead of after eight.
It is deliberately not part of `seedable` -- that would make the corpus grow
only along links it already knows, which is the opposite of discovery.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys

import policy
from core import musicbrainz, scenes
from core.names import normalise
from core.paths import DATA
from policy import SEED_PLAYS_FLOOR, SEED_RECENT_FLOOR, seedable

# Everyone already in the store as a co-appearance somebody holds. A seed drawn
# from here will intersect the existing graph by construction.
CO_ARTISTS = """
SELECT DISTINCT person_key FROM co_artists
WHERE seed_records + their_records > 0
"""

# What the scene grouping needs, for seeds AND for candidates. The same three
# signals D38 settled on, except that a candidate has no credit graph yet --
# so only co-listening and the genre veto can speak for it, and both are
# readable before a single request. That is what makes a scene predictable
# before 50 requests are spent.
SEED_NAMES = "SELECT name, mbid FROM seeds"
SEED_CO_ARTISTS = """
SELECT s.name AS seed, co.person_key
FROM co_artists co JOIN seeds s USING (seed_qobuz_id)
WHERE co.seed_records + co.their_records > 0
"""
GENRES = "SELECT mbid, genre FROM artist_genres"
LISTENS_IN_ORDER = """
SELECT listened_at, artist_key FROM listens
WHERE listened_at IS NOT NULL ORDER BY listened_at
"""


def walkable(path=None) -> dict[str, dict]:
    """Artist key -> the ids a walk needs, from favourites.json.

    Both ids, not either: `discover.py` needs the Qobuz id to read the
    discography and the mbid to know which names the seed is credited under
    (D23). Without the second the walk still runs and reports the seed as its
    own biggest collaborator, so an artist missing one is not a candidate.
    """
    blob = json.loads((path or DATA / "favourites.json").read_text())
    entries = blob.get("artists") if isinstance(blob, dict) else blob
    return {normalise(e["name"]): e for e in entries or []
            if e.get("name") and e.get("qobuz_id") and e.get("mbid")}


def reason(artist: dict, ids: dict | None) -> str:
    """Why this artist is not a candidate, in the words of the test it failed.

    Three branches for `seedable`'s two tests, and no branch for the band:
    "lapsed" means a long history with a recent count under `policy`'s m24
    floor of 10, which is below SEED_RECENT_FLOOR, so the month test has
    already answered and a band branch here would be unreachable.
    """
    if ids is None:
        return "no qobuz id or no mbid in favourites.json"
    if artist["recent"] < SEED_RECENT_FLOOR:
        return f"{artist['recent']} recent months, floor is {SEED_RECENT_FLOOR}"
    return f"{artist['plays']} plays on a short history, floor is {SEED_PLAYS_FLOOR}"


def scene_of_seeds(con, also: set[str] | None = None
                   ) -> tuple[dict[str, str], dict, dict, dict, int, set]:
    """Everything the grouping needs, read once: labels plus the raw inputs.

    The inputs come back as well as the labels, because a CANDIDATE has to be
    tested against the same sessions and genres and refetching them per
    candidate would read 190k listens 27 times.

    `also` is the candidate keys, and it is not optional in practice: the
    session counts are built for a FIXED set of keys, so a candidate left out
    of it has zero sessions, zero lift and joins nothing. That was the first
    version's bug, and it failed silently -- every candidate simply reported
    "new cluster", which is what the old ordering said anyway.
    """
    by_seed: dict[str, set[str]] = {}
    for row in con.execute(SEED_CO_ARTISTS):
        by_seed.setdefault(row["seed"], set()).add(row["person_key"])

    mbid_of = {row["name"]: row["mbid"] for row in con.execute(SEED_NAMES)}
    by_mbid: dict[str, set[str]] = {}
    for row in con.execute(GENRES):
        by_mbid.setdefault(row["mbid"], set()).add(row["genre"])
    genres = {name: by_mbid.get(mbid or "", set()) for name, mbid in mbid_of.items()}
    broad = policy.broad_genres(genres)

    names = sorted(mbid_of)
    wanted = {normalise(n) for n in names} | (also or set())
    totals, together, counted = scenes.sessions(
        ((row["listened_at"], row["artist_key"])
         for row in con.execute(LISTENS_IN_ORDER)),
        policy.SCENE_SESSION_GAP, wanted)

    def reason_for(a: str, b: str) -> str | None:
        ka, kb = normalise(a), normalise(b)
        pair = (min(ka, kb), max(ka, kb))
        shared = together.get(pair, 0)
        return policy.scene_link(
            len(by_seed.get(a, set()) & by_seed.get(b, set())), shared,
            scenes.lift(shared, totals.get(ka, 0), totals.get(kb, 0), counted),
            (genres.get(a, set()) & genres.get(b, set())) - broad)

    found = scenes.linked_pairs(names, reason_for)
    sizes = {name: len(by_seed.get(name, set())) for name in names}
    labels = scenes.group_links(sizes, [(a, b) for a, b, _ in found])
    return labels, genres, totals, together, counted, broad


def scene_for(row: dict, labels: dict[str, str], genres: dict,
              candidate_genres: dict, totals: dict, together: dict,
              counted: int, broad: set) -> tuple[str | None, str]:
    """(the scene this unwalked artist would join, why), or (None, "").

    Credits are absent by definition -- the artist has not been walked -- so
    this is the co-listening signal with the genre veto, which is exactly the
    part of D38's rule that needs no requests. Largest scene wins when an
    artist would join two: the point of the ordering is to deepen a list, and
    the deeper list is the one more rows are already in.
    """
    name = row["name"]
    mine = candidate_genres.get(row["key"], set())

    def reason_for(_candidate: str, seed: str) -> str | None:
        ka, kb = normalise(name), normalise(seed)
        pair = (min(ka, kb), max(ka, kb))
        shared = together.get(pair, 0)
        return policy.scene_link(
            0, shared,
            scenes.lift(shared, totals.get(ka, 0), totals.get(kb, 0), counted),
            (mine & genres.get(seed, set())) - broad)

    joined = scenes.joins(name, labels, reason_for)
    if not joined:
        return None, ""
    sizes = {label: sum(1 for v in labels.values() if v == label)
             for label in set(labels.values())}
    best = max(joined, key=lambda pair: (sizes.get(labels[pair[0]], 0),
                                         labels[pair[0]]))
    return labels[best[0]], f"{best[1]} with {best[0]}"


def candidates(profile: dict, ids: dict[str, dict], walked: set[int],
               co_artists: set[str], scene=None) -> tuple[list[dict], list[dict]]:
    """(candidates in walk order, the rejected with their reason).

    Walk order is the scene it would join first, then intersections, then
    recent months, then plays -- see the module docstring for why that is
    separate from the rule.

    `scene` is the callable `scene_for` wants, or None when there is no store
    to read: the order degrades rather than failing, as it already did for
    intersections.
    """
    kept, dropped = [], []
    for artist in profile.get("artists") or []:
        key = normalise(artist["name"])
        entry = ids.get(key)
        if entry is None or not seedable(artist["band"], artist["recent"],
                                         artist["plays"]):
            dropped.append({**artist, "key": key, "why": reason(artist, entry)})
            continue
        row = {**artist, "key": key, "qobuz_id": entry["qobuz_id"],
               "mbid": entry.get("mbid"),
               "walked": entry["qobuz_id"] in walked,
               "intersects": key in co_artists}
        row["scene"], row["scene_why"] = scene(row) if scene else (None, "")
        kept.append(row)
    # A seed that deepens an existing scene first, because eight of twenty
    # seeds currently group with nobody and another isolated one adds a list
    # of its own rather than range to a list that exists (D38).
    kept.sort(key=lambda r: (r["walked"], r["scene"] is None,
                             not r["intersects"], -r["recent"], -r["plays"]))
    return kept, dropped


def known_genres(ids: dict[str, dict], genre_rows: dict[str, set[str]],
                 fetch: bool, wanted: set[str]) -> dict[str, set[str]]:
    """Candidate key -> genres, from the store, optionally filling the gaps.

    `wanted` is the seedable candidates and nothing else. Scoped because the
    first version asked about all 148 artists in favourites.json -- three
    minutes of MusicBrainz for 137 answers no ordering would ever read.

    Offline by default, which is this stage's whole contract: a candidate
    whose genres the store lacks gets an empty set, and an empty set means the
    veto can never confirm its co-listening links. `--fetch-genres` is the
    explicit opt-in, one request per missing artist.
    """
    out: dict[str, set[str]] = {}
    missing = []
    for key in sorted(wanted):
        mbid = (ids.get(key) or {}).get("mbid")
        if not mbid:
            out[key] = set()
            continue
        if mbid in genre_rows:
            out[key] = genre_rows[mbid]
        else:
            out[key] = set()
            missing.append((key, mbid))

    if not missing:
        return out
    if not fetch:
        print(f"{len(missing)} candidates have no genre in the store, so no "
              "co-listening link of theirs can be confirmed - "
              "--fetch-genres asks MusicBrainz", file=sys.stderr)
        return out

    print(f"fetching {len(missing)} genres from MusicBrainz, ~1.2s each",
          file=sys.stderr)
    for key, mbid in missing:
        rows = musicbrainz.genres(mbid)
        out[key] = {name for name, _ in rows or []}
    print("fetched - run ./stages/load.py to put them in the store",
          file=sys.stderr)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(DATA / "music.db"))
    parser.add_argument("--next", type=int, metavar="N",
                        help="print the commands for the next N unwalked seeds")
    parser.add_argument("--all", action="store_true",
                        help="also list the artists the rule rejects, with why")
    parser.add_argument("--fetch-genres", action="store_true",
                        help="ask MusicBrainz for any candidate genre the store "
                             "lacks (1 request each, cached) - the genre veto "
                             "cannot confirm a scene without it")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        profile = json.loads((DATA / "profile.json").read_text())
        ids = walkable()
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{exc} - run ./stages/profile.py first") from exc

    walked: set[int] = set()
    co_artists: set[str] = set()
    scene = None
    genre_rows: dict[str, set[str]] = {}
    try:
        con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        walked = {r[0] for r in con.execute("SELECT seed_qobuz_id FROM seeds")}
        co_artists = {r[0] for r in con.execute(CO_ARTISTS)}
        for row in con.execute(GENRES):
            genre_rows.setdefault(row["mbid"], set()).add(row["genre"])
        # Which candidates pass the rule is decided before anything is fetched
        # or counted, so only they are asked about and only their sessions are
        # tallied.
        shortlist, _ = candidates(profile, ids, walked, co_artists)
        fresh_keys = {r["key"] for r in shortlist if not r["walked"]}
        labels, genres, totals, together, counted, broad = scene_of_seeds(
            con, fresh_keys)
        if not counted:
            print("warning: no listens in the store, so no scene can be "
                  "predicted - run ./stages/load.py with the export",
                  file=sys.stderr)
        candidate_genres = known_genres(ids, genre_rows, args.fetch_genres,
                                        fresh_keys)

        def scene(row):
            return scene_for(row, labels, genres, candidate_genres, totals,
                             together, counted, broad)
    except sqlite3.OperationalError:
        # No store yet is not an error here: the rule does not need it, and
        # only the ORDER degrades -- to recent months, which is the fallback
        # the hand-picking used.
        print(f"warning: no readable store at {args.db}, so no seed is known "
              "to intersect and the order falls back to recent months",
              file=sys.stderr)

    kept, dropped = candidates(profile, ids, walked, co_artists, scene)
    fresh = [r for r in kept if not r["walked"]]

    if args.json:
        print(json.dumps({"candidates": kept, "rejected": dropped},
                         indent=2, ensure_ascii=False))
        return 0

    if args.next:
        count = min(args.next, len(fresh))
        picked = fresh[:args.next]
        print(f"# the next {count} seeds, ~50 requests each, "
              f"~{count * 50} in total")
        for row in picked:
            if row["scene"]:
                note = f"joins the {row['scene']} scene - {row['scene_why']}"
            elif row["intersects"]:
                note = "intersects the graph already"
            else:
                note = "new cluster"
            print(f"#   {row['name']} - {note}")
        # One command: discover.py takes several ids and reads the storefront
        # cookie and the alias file once for the run.
        print("\n./stages/discover.py --artist "
              + " ".join(str(row["qobuz_id"]) for row in picked))
        print("./stages/load.py")
        print("\n# read each walk's 'might be one person' list and add to "
              "data/aliases.json before ranking (D25)")
        return 0

    print(f"{len(kept)} artists pass the rule, {len(kept) - len(fresh)} already walked")
    joining = sum(1 for r in fresh if r["scene"])
    print(f"{len(fresh)} to go, {joining} of them would deepen an existing "
          f"scene, {sum(1 for r in fresh if r['intersects'])} are already a "
          "co-artist of a walked seed\n")
    for row in kept:
        flag = ("walked" if row["walked"]
                else f"-> {row['scene']}" if row["scene"]
                else "INTERSECTS" if row["intersects"] else "")
        print(f"  {row['qobuz_id']:>8}  {row['name'][:28]:<28} {row['band']:<9} "
              f"{row['recent']:>2}/24 months  {row['plays']:>5} plays  {flag}")

    if args.all:
        print(f"\n{len(dropped)} rejected:")
        for row in sorted(dropped, key=lambda r: (-r["recent"], -r["plays"])):
            print(f"            {row['name'][:28]:<28} {row['band']:<9} "
                  f"{row['recent']:>2}/24 months  {row['why']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
