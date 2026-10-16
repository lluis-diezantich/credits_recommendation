#!/usr/bin/env python3
"""Step 2 of 2 - RESOLUTION: turn discovered names into Qobuz artists and a pool.

Takes the people qobuz_discover.py found, resolves each name to a Qobuz artist id
via the storefront autosuggest, then fetches that artist's own releases to build
a pool of candidate releases to rank later.

This is the lossy half of the pipeline, deliberately separated: a name may match
nothing, the wrong person, or four plausible candidates (Qobuz has two distinct
artists called "Javier Colina"). Keeping it apart from discovery means it can be
re-run, re-tuned, or hand-corrected without re-crawling any albums.

    ./qobuz_resolve.py                       # discovery_41620.json, 2+ albums
    ./qobuz_resolve.py --min-albums 1        # everyone (slower, noisier)
    ./qobuz_resolve.py --no-cover-sources    # skip people the seed only covered
    ./qobuz_resolve.py --no-pool             # resolve ids only, skip the releases
    ./qobuz_resolve.py --in discovery_41620.json --out watchlist.json

Writes watchlist.json (resolved people, with provenance and a `watch` flag) and
pool.json (their releases). Existing `watch: false` mutes are preserved, so a
person you rejected is not silently re-added on the next run.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
import time
import urllib.parse
from pathlib import Path

# Run directly (./stages/discover.py) or as a module (python -m stages.discover):
# either way the project root has to be importable before core/policy resolve.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.paths import DATA
from core.qobuz import (
    API,
    APP_ID,
    PAGE_LIMIT,
    PAUSE,
    STORE,
    pick,
    search_artists,
    store_cookies,
)
from core.qobuz import get as _get
from policy import WEAK_CLASSES, role_weight


def signal_for(artist: dict) -> dict:
    """A comparable score for how much a referral is worth.

    role_weight  x  how embedded the person is in the seed's catalogue.
    Selectivity (how many records they touch in total) needs Discogs and is
    added by discogs_resolve.py; here it is absent, not assumed.
    """
    stats = artist.get("stats") or {}
    weight = role_weight(stats.get("top_role"))
    seed_albums = stats.get("albums") or 0
    embedded = min(seed_albums / 10.0, 1.0)      # 10+ of the seed's albums saturates
    flags = []
    if len((artist.get("name") or "").split()) == 1:
        # Single-word names are what Qobuz collapses into bucket entities
        # (one "Morgan" holding a 1972 prog album and 2026 reggaeton). A flag,
        # never a rejection: Titas and Gonzaguinha are single-token and real.
        flags.append("single_token_name")
    if set(artist.get("classes") or []) <= WEAK_CLASSES:
        flags.append("weak_classes")
    return {"role_weight": round(weight, 3), "seed_albums": seed_albums,
            "embedded": round(embedded, 3),
            "score": round(weight * embedded, 4), "flags": flags}


def artist_releases(artist_id: int, store: str, cookies: str) -> list[dict]:
    zone = store.split("-")[0].upper()
    headers = {"x-app-id": APP_ID, "cookie": cookies}
    collected, offset = [], 0
    while True:
        query = urllib.parse.urlencode({
            "artist_id": artist_id, "extra": "albums_with_last_release",
            "limit": PAGE_LIMIT, "offset": offset, "zone": zone, "store": store})
        status, body, _ = _get(f"{API}/artist/get?{query}", headers)
        if status != 200:
            print(f"warning: artist/get {artist_id} HTTP {status}", file=sys.stderr)
            return collected
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return collected
        page = (data.get("albums_without_last_release") or {}).get("items") or []
        collected += [a for a in page
                      if any(str(x.get("id")) == str(artist_id)
                             for x in (a.get("artists") or []))]
        if len(page) < PAGE_LIMIT:
            return collected
        offset += PAGE_LIMIT


def load_mutes(path: Path) -> set[int]:
    """Qobuz ids previously set to watch:false. Never re-add those."""
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return set()
    return {a["qobuz_id"] for a in data.get("artists", [])
            if a.get("qobuz_id") and not a.get("watch", True)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve discovered people to Qobuz artists.")
    parser.add_argument("--in", dest="infile",
                        help="discovery json (default: newest discovery_*.json)")
    parser.add_argument("--out", default="watchlist.json", help="watchlist output")
    parser.add_argument("--pool-out", default="pool.json", help="pool output")
    parser.add_argument("--store", default=STORE)
    parser.add_argument("--min-albums", type=int, default=2,
                        help="only resolve people on at least this many of the seed's albums")
    parser.add_argument("--no-cover-sources", action="store_true",
                        help="skip people whose only link is having written a song "
                             "the seed covered")
    parser.add_argument("--keep-weak", action="store_true",
                        help="keep referrals credited only as writer/composer or main/featured "
                             "artist (dropped by default; they were 45%% of the pool)")
    parser.add_argument("--min-role-weight", type=float, default=0.0,
                        help="skip people whose top role weighs less than this, e.g. 0.2 to "
                             "drop mastering. Off by default: it saves only 2 of 122 lookups "
                             "here, and above 0.25 it eats featured/associated artists that "
                             "--keep-weak already governs. The gate that pays is the one in "
                             "discogs_resolve.py, where one person fans out into dozens of "
                             "Qobuz fetches")
    parser.add_argument("--no-pool", action="store_true",
                        help="resolve ids only, do not fetch releases")
    args = parser.parse_args()

    if args.infile:
        source = Path(args.infile)
    else:
        found = sorted(DATA.glob("discovery_*.json"), key=lambda p: p.stat().st_mtime)
        if not found:
            raise SystemExit("no discovery_*.json found - run ./qobuz_discover.py first")
        source = found[-1]
    discovery = json.loads(source.read_text())
    seed = discovery["seed"]
    print(f"seed: {seed['name']} ({seed['qobuz_id']}) from {source.name}", file=sys.stderr)

    people = [p for p in discovery["people"] if p["stats"]["albums"] >= args.min_albums]
    if args.no_cover_sources:
        people = [p for p in people if not p.get("cover_source_only")]
    if args.min_role_weight > 0:
        before = len(people)
        people = [p for p in people
                  if role_weight((p.get("stats") or {}).get("top_role"))
                  >= args.min_role_weight]
        print(f"--min-role-weight {args.min_role_weight} kept {len(people)} of {before}",
              file=sys.stderr)
    print(f"resolving {len(people)} of {len(discovery['people'])} people "
          f"(min_albums={args.min_albums})", file=sys.stderr)

    out_path = DATA / args.out
    muted = load_mutes(out_path)
    cookies = store_cookies(args.store)

    resolved, unresolved = [], []
    outcomes = collections.Counter()

    for index, person in enumerate(people, 1):
        candidates = search_artists(person["names"][0], args.store)
        choice, how = pick(person["names"], candidates)
        outcomes[how] += 1
        if choice is None:
            unresolved.append({
                "names": person["names"], "classes": person.get("classes"),
                "roles": list(person["roles"])[:4],
                "albums": person["stats"]["albums"], "reason": how,
                "candidates": [{"id": c.get("id"), "name": c.get("name")}
                               for c in candidates[:3]],
            })
        else:
            qid = int(choice["id"])
            resolved.append({
                "qobuz_id": qid,
                "name": choice.get("name"),
                "name_variants": person["names"],
                "watch": qid not in muted,
                "classes": person.get("classes"),
                "cover_source_only": person.get("cover_source_only", False),
                "resolved": {"via": "autosuggest", "confidence": how,
                             "albums_count": choice.get("albumsCount") or 0},
                "seed": {"qobuz_id": seed["qobuz_id"], "name": seed["name"]},
                "roles": person["roles"],
                "appearances": person["albums"],
                "stats": person["stats"],
            })
        if index % 20 == 0:
            print(f"  ...{index}/{len(people)}", file=sys.stderr)
        time.sleep(PAUSE)

    resolved.sort(key=lambda a: (-a["stats"]["albums"], -a["stats"]["tracks"]))
    out_path.write_text(json.dumps({
        "version": 1, "generated": dt.date.today().isoformat(),
        "seed": seed, "store": args.store,
        "artists": resolved, "unresolved": unresolved,
    }, indent=2, ensure_ascii=False))

    print(f"\nresolved {len(resolved)}, unresolved {len(unresolved)}")
    print("  " + ", ".join(f"{k} {v}" for k, v in outcomes.most_common()))
    if muted:
        print(f"  {len(muted)} previously muted id(s) kept muted")

    if args.no_pool:
        print(f"wrote {out_path.name} (no pool)")
        return 0

    # ---- pool -----------------------------------------------------------
    watching = [a for a in resolved if a["watch"]]
    if not args.keep_weak:
        before = len(watching)
        watching = [a for a in watching
                    if not (set(a.get("classes") or []) <= WEAK_CLASSES)]
        print(f"dropped {before - len(watching)} weak referrals "
              f"(writer/composer or billing only); --keep-weak to keep them",
              file=sys.stderr)
    print(f"\nfetching releases for {len(watching)} artists...", file=sys.stderr)
    pool, seen_ids = [], set()
    seed_id = str(seed["qobuz_id"])
    for index, artist in enumerate(watching, 1):
        for release in artist_releases(artist["qobuz_id"], args.store, cookies):
            rid = str(release.get("id") or "")
            if not rid or rid in seen_ids:
                continue
            artists = [x.get("name") for x in (release.get("artists") or []) if x.get("name")]
            # A release by the seed themselves is not a discovery.
            if any(str(x.get("id")) == seed_id for x in (release.get("artists") or [])):
                continue
            seen_ids.add(rid)
            pool.append({
                "album_id": rid,
                "title": release.get("title"),
                "artists": artists,
                "date": (release.get("release_date_original") or "")[:10],
                "tracks": release.get("tracks_count") or 0,
                "hires": bool(release.get("hires")),
                "streamable": bool(release.get("streamable")),
                "label": (release.get("label") or {}).get("name"),
                "genre": (release.get("genre") or {}).get("name"),
                # Why this release is a candidate - the ranking step's input.
                "via": {"qobuz_id": artist["qobuz_id"], "name": artist["name"],
                        "classes": artist["classes"], "top_role": artist["stats"]["top_role"],
                        "seed_albums": artist["stats"]["albums"],
                        "signal": signal_for(artist)},
            })
        if index % 20 == 0:
            print(f"  ...{index}/{len(watching)}", file=sys.stderr)
        time.sleep(PAUSE)

    # Strongest referrals first; date is the tie-break. This is not the ranking
    # step, just a sane default order for eyeballing the file.
    pool.sort(key=lambda r: (-r["via"]["signal"]["score"], r["date"]), reverse=False)
    pool_path = DATA / args.pool_out
    pool_path.write_text(json.dumps({
        "version": 1, "generated": dt.date.today().isoformat(),
        "seed": seed, "store": args.store,
        "artists_fetched": len(watching), "releases": len(pool),
        "pool": pool,
    }, indent=2, ensure_ascii=False))

    print(f"\npool: {len(pool)} distinct releases from {len(watching)} artists")
    print(f"wrote {out_path.name} and {pool_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
