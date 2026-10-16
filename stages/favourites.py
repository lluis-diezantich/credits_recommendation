#!/usr/bin/env python3
"""Your top artists from ListenBrainz, resolved to Qobuz ids.

One GET per stats window for who you actually play, then one Qobuz autosuggest
per artist to turn each name into a Qobuz artist id. Writes
data/favourites.json, which the radars read instead of their own hardcoded
WATCHED_ARTISTS dicts.

By default it asks for EVERY window and unions the results, because the windows
answer different questions: all_time is who you are, this_week is what you are
on right now, and an artist you played 400 times in 2019 and never since should
not share a list with one you discovered on Tuesday without that being visible.
Each entry records its rank in every window it charted in, so the file says
which kind of favourite each artist is.

Run this monthly, not weekly. The windows move slowly, the resolve spends one
request per NEW name, and a wrong match nobody looked at poisons a radar
quietly -- exactly the failure mode stages/resolve_qobuz.py is split out to
contain. The radars are the cheap, schedulable half.

Live stats rather than the listenbrainz_top parquet export on purpose: the
export is a point-in-time ZIP, and reading it needs pandas, which would end this
project's no-dependencies property. What it loses is aliases.yml name merging,
so two spellings of one artist can both appear -- mute one with "watch": false.

    ./stages/favourites.py --user lluisdiezantich
    ./stages/favourites.py --user X --dry-run             # print, write nothing
    ./stages/favourites.py --user X --range all_time      # one window only
    ./stages/favourites.py --user X --range week,month    # some of them
    ./stages/favourites.py --user X --count 20            # per window, not total
    ./stages/favourites.py --user X --refresh             # re-ask about ids we have
    ./stages/favourites.py --review                       # fix the doubtful ones

--review needs no --user and makes no ListenBrainz call: it walks the entries
that did not resolve cleanly, shows you Qobuz's candidates for each, and writes
your choice back. One Qobuz request per row reviewed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
import time
from pathlib import Path

# Run directly (./stages/favourites.py) or as a module (python -m stages.favourites).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import favourites
from core.http import get as _http_get
from core.paths import DATA
from core.names import normalise

# pick() refuses fuzzy matches on purpose, which is why unresolved names are
# reported for hand-filling instead of being guessed at.
from core.qobuz import PAUSE, STORE, artist_name, pick, search_artists, store_cookies

STATS_URL = "https://api.listenbrainz.org/1/stats/user/{user}/artists"

# Breadth at or below this is reported as thin. Nothing is muted automatically:
# a one-track artist can still be a real one you only just found.
THIN_TRACKS = 2
USER_AGENT = "favourites-resolver/1.0 (personal use)"

# Every window ListenBrainz calculates, widest first so that the all_time rank
# is the one a tie falls back on. The this_* variants are calendar-to-date
# ("this month so far"); the bare ones are trailing ("the last 30 days").
RANGES = (
    "all_time",
    "year",
    "half_yearly",
    "quarter",
    "month",
    "week",
    "this_year",
    "this_month",
    "this_week",
)


def fetch_top(user: str, period: str, count: int) -> list[dict]:
    """Your most-played artists in one window, as ListenBrainz ranks them.

    A window with no stats is NOT fatal: these are precomputed per range, so a
    quiet week or a range LB has not got round to must not lose the other eight.
    """
    url = f"{STATS_URL.format(user=user)}?range={period}&count={count}"
    status, body, _ = _http_get(url, user_agent=USER_AGENT, service="ListenBrainz")
    if status == 204:
        print(f"  {period:<11} no stats calculated", file=sys.stderr)
        return []
    if status == 404:
        # User-level, not range-level, so this one really is fatal.
        sys.exit(f"ListenBrainz does not know a user called {user!r}")
    if status != 200:
        print(f"  {period:<11} HTTP {status}", file=sys.stderr)
        return []
    try:
        return json.loads(body).get("payload", {}).get("artists") or []
    except json.JSONDecodeError:
        print(f"  {period:<11} response was not JSON", file=sys.stderr)
        return []


def collect(user: str, periods: list[str], count: int) -> dict[str, dict]:
    """Union the windows, keyed by normalised name, keeping each window's rank.

    `plays` is the largest listen count any window reported, which is the
    all_time one wherever all_time charted them -- the others are subsets of it.
    """
    merged: dict[str, dict] = {}
    for period in periods:
        rows = fetch_top(user, period, count)
        print(f"  {period:<11} {len(rows)} artists", file=sys.stderr)
        for rank, row in enumerate(rows, 1):
            name = row.get("artist_name")
            if not name:
                continue
            found = merged.setdefault(
                normalise(name), {"name": name, "mbid": None, "plays": 0, "ranks": {}}
            )
            found["mbid"] = found["mbid"] or row.get("artist_mbid")
            found["plays"] = max(found["plays"] or 0, row.get("listen_count") or 0)
            found["ranks"][period] = rank
    return merged


def review(store: str, dry_run: bool) -> int:
    """Walk the doubtful entries, show candidates, write the choice back.

    Only rows that are still open: an `exact` match needs no second opinion and
    a `manual` one has already had yours. A muted row is a decision too, so it
    is not re-asked either.

    Candidates are re-fetched rather than stored, because a stored candidate
    list would be a second copy of Qobuz's catalogue going stale in data/.
    """
    entries = favourites.load()
    if not entries:
        sys.exit(f"no {favourites.FILE.name} yet - run without --review first")

    pending = [
        entry for entry in entries
        if entry.get("watch", True) and entry.get("qobuz_match") not in ("exact", "manual")
    ]
    if not pending:
        print(f"nothing to review: every artist in {favourites.FILE.name} is "
              "an exact match, a manual pick, or muted.")
        return 0

    print(f"{len(pending)} artists to review. Numbers pick a candidate, "
          "#<id> enters one by hand,\n/text searches again, s skips, m mutes, "
          "q saves and quits. Ctrl-C aborts without writing.\n")

    picked = muted = skipped = 0
    # Fetched on the first #<id> only, so a review that never uses one pays
    # nothing: autosuggest needs no cookies, artist/get does.
    cookies: str | None = None
    try:
        for position, entry in enumerate(pending, 1):
            query = entry["name"]
            while True:
                # 9 because the keys are 1-9; a tenth candidate is never the
                # right answer for a name you actually listen to.
                candidates = search_artists(query, store)[:9]
                print(f"[{position}/{len(pending)}] {entry['name']}  "
                      f"({entry.get('plays') or 0} plays, "
                      f"{entry.get('qobuz_match') or 'no match'})")
                if query != entry["name"]:
                    print(f"  searching {query!r}")
                if not candidates:
                    print("  no candidates")
                for number, candidate in enumerate(candidates, 1):
                    # Mark the id the entry already holds, so an `ambiguous`
                    # row shows what it would keep if you just skip it.
                    current = str(candidate.get("id")) == str(entry.get("qobuz_id"))
                    print(f"  {'*' if current else ' '}{number}. "
                          f"{str(candidate.get('id')):>9}  {candidate.get('name')}"
                          f"   ({candidate.get('albumsCount') or 0} albums)")

                answer = input("  > ").strip()

                if answer in ("", "s"):
                    skipped += 1
                    break
                if answer == "q":
                    print(f"\nstopped at {position} of {len(pending)}.")
                    raise StopIteration
                if answer == "m":
                    entry["watch"] = False
                    muted += 1
                    print("  muted")
                    break
                if answer.startswith("#"):
                    raw = answer[1:].strip()
                    if not raw.isdigit():
                        print("  ? #<id> wants a number, e.g. #41620")
                        continue
                    if cookies is None:
                        try:
                            cookies = store_cookies(store)
                        except SystemExit as error:
                            # store_cookies exits on a bad storefront, which
                            # would throw away every decision made so far.
                            print(f"  ? {error}")
                            continue
                    name, outcome = artist_name(int(raw), store, cookies)
                    if outcome == "not_found":
                        print(f"  ? Qobuz has no artist {raw}")
                        continue
                    if outcome == "error":
                        print(f"  ? could not confirm {raw}, try again")
                        continue
                    entry["qobuz_id"] = int(raw)
                    entry["qobuz_match"] = "manual"
                    picked += 1
                    print(f"  set {raw}  {name}")
                    break
                if answer.startswith("/"):
                    query = answer[1:].strip() or entry["name"]
                    continue
                if answer.isdigit() and 1 <= int(answer) <= len(candidates):
                    chosen = candidates[int(answer) - 1]
                    entry["qobuz_id"] = chosen["id"]
                    entry["qobuz_match"] = "manual"
                    picked += 1
                    print(f"  set {chosen['id']}  {chosen.get('name')}")
                    break
                print("  ? expected a number, #<id>, /text, s, m or q")
    except StopIteration:
        pass
    except KeyboardInterrupt:
        print("\naborted, nothing written.")
        return 1

    print(f"\n{picked} picked, {muted} muted, {skipped} left open.")
    if dry_run:
        print("--dry-run: nothing written.")
        return 0

    favourites.save(entries, dt.datetime.now(dt.UTC).isoformat(timespec="seconds"))
    print(f"wrote {favourites.FILE}")
    return 0


def set_tracks(entry: dict, key: str, counts: dict[str, int]) -> None:
    """Record this artist's breadth, without destroying a number we already had.

    A missing store or an artist the export predates both mean "unknown", so
    they must not overwrite a real count with 0 -- that would read as "one song
    on repeat" and invite muting a genuine favourite.
    """
    known = counts.get(entry.get("mbid") or "")
    if known is None:
        known = counts.get(key)
    if known is not None:
        entry["tracks"] = known
    else:
        entry.setdefault("tracks", None)


def track_counts() -> dict[str, int]:
    """Distinct recordings per artist, from the local listen store.

    Breadth, not depth. A top-artists list cannot tell one song on repeat from
    an artist you play across a dozen records, and that is exactly the
    difference between a featured credit and a favourite: a collaboration
    counts a play for every artist on it, so a single beloved track carries
    strangers onto the list with it.

    Read from data/music.db rather than the stats API because the API would
    only report breadth within your top-N recordings per window -- at a few
    hundred artists that number reflects the request limit, not your
    listening. The store holds every listen, so the count is real.

    Empty when the store has not been built, which is why the caller leaves an
    existing count alone instead of writing 0: no store means unknown, not
    zero. The store is also a point-in-time export, so recent artists are
    undercounted and the newest are absent entirely.
    """
    store = DATA / "music.db"
    if not store.exists():
        print(f"note: no {store.name}, so track counts are left as they are "
              "(build it with ./stages/load.py)", file=sys.stderr)
        return {}

    counts: dict[str, int] = {}
    # Read-only: this stage must never be the thing that corrupts the store.
    with sqlite3.connect(f"file:{store}?mode=ro", uri=True) as db:
        rows = db.execute("""
            select artist_mbid, artist_name,
                   count(distinct coalesce(recording_mbid, track_name)) tracks
            from listens
            group by coalesce(artist_mbid, lower(artist_name))
        """)
        for mbid, name, tracks in rows:
            if mbid:
                counts[mbid] = tracks
            if name:
                # One artist can appear both with and without an MBID, so the
                # name key takes the larger of the groups rather than the last.
                key = normalise(name)
                counts[key] = max(counts.get(key, 0), tracks)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve your top ListenBrainz artists to Qobuz ids."
    )
    parser.add_argument("--user", help="ListenBrainz username (not needed with --review)")
    parser.add_argument("--range", dest="period", default="all",
                        help="stats windows, comma-separated, or 'all' for every one "
                             f"(default: all). Valid: {', '.join(RANGES)}")
    parser.add_argument("--count", type=int, default=40,
                        help="top artists to ask for PER WINDOW, not in total (default: 40)")
    parser.add_argument("--store", default=STORE, help=f"Qobuz storefront (default: {STORE})")
    parser.add_argument("--refresh", action="store_true",
                        help="re-resolve artists that already have a Qobuz id, except the "
                             "ones you picked by hand")
    parser.add_argument("--review", action="store_true",
                        help="walk the entries that did not resolve cleanly and pick by hand")
    parser.add_argument("--dry-run", action="store_true",
                        help="report without writing data/favourites.json")
    args = parser.parse_args()

    if args.review:
        return review(args.store, args.dry_run)
    if not args.user:
        parser.error("--user is required (or use --review)")

    if args.period == "all":
        periods = list(RANGES)
    else:
        periods = [p.strip() for p in args.period.split(",") if p.strip()]
        unknown = [p for p in periods if p not in RANGES]
        if unknown:
            parser.error(f"unknown range(s): {', '.join(unknown)}. Valid: {', '.join(RANGES)}")

    print(f"asking ListenBrainz for the top {args.count} in "
          f"{len(periods)} window{'s' if len(periods) != 1 else ''}:", file=sys.stderr)
    merged = collect(args.user, periods, args.count)
    if not merged:
        sys.exit(f"ListenBrainz returned no artists for {args.user!r} in any of: "
                 f"{', '.join(periods)}")

    # Existing entries win on ids: a hand-corrected or hand-filled id has to
    # survive every later run, which is the whole reason this file is merged
    # rather than overwritten.
    existing = {normalise(e["name"]): e for e in favourites.load() if e.get("name")}

    def still_open(entry: dict) -> bool:
        """Whether this entry wants a (re-)resolve.

        A hand-picked id is never re-resolved: --refresh exists to re-ask
        autosuggest, not to overrule you.
        """
        if not entry.get("qobuz_id"):
            return True
        return args.refresh and entry.get("qobuz_match") != "manual"

    needs_resolving = sum(1 for key in merged if still_open(existing.get(key) or {}))
    print(f"\n{len(merged)} unique artists across {len(periods)} windows, "
          f"{needs_resolving} to resolve "
          f"({needs_resolving} Qobuz request{'s' if needs_resolving != 1 else ''}).",
          file=sys.stderr)

    tracks = track_counts()

    out: list[dict] = []
    resolved = kept = unresolved = 0

    for key, row in merged.items():
        entry = existing.pop(key, {"name": row["name"]})
        entry["mbid"] = entry.get("mbid") or row["mbid"]
        entry["plays"] = row["plays"]
        entry["ranks"] = row["ranks"]
        set_tracks(entry, key, tracks)
        # Best rank in any window, so the file can be sorted and skimmed.
        entry["rank"] = min(row["ranks"].values()) if row["ranks"] else None
        entry.setdefault("itunes_id", None)

        if not still_open(entry):
            kept += 1
        else:
            hit, how = pick([row["name"]], search_artists(row["name"], args.store))
            entry["qobuz_match"] = how
            if hit:
                entry["qobuz_id"] = hit["id"]
                resolved += 1
            else:
                entry.setdefault("qobuz_id", None)
                unresolved += 1
                print(f"  unresolved  {row['name']}  ({how})", file=sys.stderr)
            time.sleep(PAUSE)

        out.append(entry)

    # Artists who dropped out of every window keep their entry: falling off a
    # top-40 this quarter is not a reason to stop watching someone. Mute with
    # "watch": false, or delete the line.
    for leftover in existing.values():
        leftover["rank"] = None
        leftover["ranks"] = {}
        set_tracks(leftover, normalise(leftover["name"]), tracks)
        out.append(leftover)

    # Widest-window rank first, then play count; unranked leftovers at the end.
    out.sort(key=lambda e: (e["rank"] is None, e["rank"] or 0, -(e.get("plays") or 0)))

    print(f"\n{len(merged)} unique artists: {resolved} newly resolved, "
          f"{kept} already had a Qobuz id, {unresolved} unresolved.")

    thin = [e for e in out if e.get("tracks") is not None and e["tracks"] <= THIN_TRACKS]
    unknown = sum(1 for e in out if e.get("tracks") is None)
    if thin:
        print(f"\n{len(thin)} artists play on {THIN_TRACKS} or fewer distinct tracks "
              "- most likely one song you love rather than an artist you follow:")
        for entry in sorted(thin, key=lambda e: -(e.get("plays") or 0))[:15]:
            print(f"  {entry['plays'] or 0:>5} plays  {entry['tracks']} track"
                  f"{'s' if entry['tracks'] != 1 else ''}  {entry['name']}")
        if len(thin) > 15:
            print(f"  ... and {len(thin) - 15} more")
        print('  mute one with "watch": false, or leave it and see what it reports.')
    if unknown:
        print(f"\n{unknown} artists have no local listen history, so their breadth is "
              "unknown and they are left in.")
    if existing:
        print(f"{len(existing)} kept from a previous run, no longer in any window.")
    if unresolved:
        print(f"Fill ids in by hand in {favourites.FILE.name}, or find one with:\n"
              f"  ./radars/qobuz.py --find \"Artist Name\"")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    favourites.save(out, dt.datetime.now(dt.UTC).isoformat(timespec="seconds"))
    print(f"\nwrote {favourites.FILE} ({len(out)} artists)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
