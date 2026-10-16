#!/usr/bin/env python3
"""Step 1 of 2 - DISCOVERY: who made a seed artist's records.

Walks every release by one seed artist, reads the per-track `performers` credits
Qobuz ships with each album, and reduces them to distinct people with the
evidence for each: which of the seed's albums they worked on, how many tracks,
and in what roles.

Exact and cacheable: this only parses what Qobuz already returned, so it does no
name matching and makes no guesses. The fuzzy part (name -> Qobuz artist id) is
qobuz_resolve.py, kept separate so it can be re-run without re-crawling albums.

No login, no API key -- a public app id plus the cookies any storefront page
issues. Album credits are cached, so a second run costs one request.

    ./qobuz_discover.py                      # the seed in SEED_ARTIST
    ./qobuz_discover.py --artist 41620
    ./qobuz_discover.py --include-all        # keep artwork/studio people too
    ./qobuz_discover.py --refresh            # ignore the credits cache

Writes discovery_<artist_id>.json, the input to qobuz_resolve.py.
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

from core.credits import parse_performers
from core.names import normalise
from core.paths import CACHE, DATA
from core.qobuz import API, APP_ID, PAGE_LIMIT, PAUSE, STORE, store_cookies
from core.qobuz import get as _get
from core.qobuz import message as _message
from policy import MUSICAL_ROLES, classify_roles

CACHE_DIR = CACHE / "credits"

SEED_ARTIST = 41620          # Jorge Drexler


def seed_releases(artist_id: int, store: str, cookies: str) -> tuple[str, list[dict]]:
    """(seed name, releases where the seed is a primary artist)."""
    zone = store.split("-")[0].upper()
    headers = {"x-app-id": APP_ID, "cookie": cookies}
    name, collected, offset = "?", [], 0
    while True:
        query = urllib.parse.urlencode({
            "artist_id": artist_id, "extra": "albums_with_last_release",
            "limit": PAGE_LIMIT, "offset": offset, "zone": zone, "store": store})
        status, body, _ = _get(f"{API}/artist/get?{query}", headers)
        if status != 200:
            raise SystemExit(f"artist/get failed (HTTP {status}): {_message(body)}")
        data = json.loads(body)
        name = data.get("name") or name
        page = (data.get("albums_without_last_release") or {}).get("items") or []
        collected += [a for a in page
                      if any(str(x.get("id")) == str(artist_id)
                             for x in (a.get("artists") or []))]
        if len(page) < PAGE_LIMIT:
            return name, collected
        offset += PAGE_LIMIT


def album_tracks(album_id: str, store: str, cookies: str, refresh: bool) -> list[dict] | None:
    """Tracks for one album, cached on disk. None means the fetch failed."""
    CACHE_DIR.mkdir(exist_ok=True)
    safe = urllib.parse.quote(str(album_id), safe="")
    cached = CACHE_DIR / f"{store}_{safe}.json"
    if cached.exists() and not refresh:
        try:
            return json.loads(cached.read_text())
        except (json.JSONDecodeError, OSError):
            pass   # fall through and refetch
    zone = store.split("-")[0].upper()
    query = urllib.parse.urlencode({"album_id": album_id, "zone": zone, "store": store})
    status, body, _ = _get(f"{API}/album/get?{query}",
                           {"x-app-id": APP_ID, "cookie": cookies})
    if status != 200:
        print(f"warning: album/get {album_id} HTTP {status}: {_message(body)}", file=sys.stderr)
        return None
    try:
        tracks = (json.loads(body).get("tracks") or {}).get("items") or []
    except json.JSONDecodeError:
        print(f"warning: album/get {album_id} returned non-JSON", file=sys.stderr)
        return None
    # Cache only what this step needs.
    slim = [{"id": t.get("id"), "title": t.get("title"),
             "performers": t.get("performers") or ""} for t in tracks]
    cached.write_text(json.dumps(slim))
    return slim


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover who made a seed artist's records.")
    parser.add_argument("--artist", type=int, default=SEED_ARTIST, help="Qobuz seed artist id")
    parser.add_argument("--store", default=STORE, help=f"storefront (default: {STORE})")
    parser.add_argument("--include-all", action="store_true",
                        help="keep people with no musical role (designers, studios)")
    parser.add_argument("--refresh", action="store_true", help="ignore the credits cache")
    parser.add_argument("--out", help="output path (default: discovery_<artist_id>.json)")
    args = parser.parse_args()

    cookies = store_cookies(args.store)
    seed_name, releases = seed_releases(args.artist, args.store, cookies)
    if not releases:
        raise SystemExit(f"no releases for artist {args.artist} in the {args.store} store")
    print(f"seed: {seed_name} ({args.artist}) - {len(releases)} releases", file=sys.stderr)

    # key -> evidence
    people: dict[str, dict] = collections.defaultdict(
        lambda: {"names": set(), "roles": collections.Counter(), "albums": {}, "tracks": 0})
    credited_tracks = 0
    total_tracks = 0
    failed = 0
    fetched = 0

    for index, release in enumerate(releases, 1):
        tracks = album_tracks(release["id"], args.store, cookies, args.refresh)
        if tracks is None:
            failed += 1
            continue
        fetched += 1
        for track in tracks:
            total_tracks += 1
            credits = (track.get("performers") or "").strip()
            if not credits:
                continue
            credited_tracks += 1
            for name, roles in parse_performers(credits):
                entry = people[normalise(name)]
                entry["names"].add(name)
                entry["tracks"] += 1
                for role in roles:
                    entry["roles"][role] += 1
                album = entry["albums"].setdefault(str(release["id"]), {
                    "album_id": str(release["id"]),
                    "title": release.get("title"),
                    "date": (release.get("release_date_original") or "")[:10],
                    "roles": [], "tracks": 0})
                album["tracks"] += 1
                for role in roles:
                    if role not in album["roles"]:
                        album["roles"].append(role)
        if index % 15 == 0:
            print(f"  ...{index}/{len(releases)}", file=sys.stderr)
        time.sleep(PAUSE if not (CACHE_DIR / "x").exists() else 0)

    def is_musical(entry: dict) -> bool:
        return any(r.lower() in MUSICAL_ROLES for r in entry["roles"])

    kept, dropped = [], 0
    for key, entry in people.items():
        if key == normalise(seed_name):
            continue                      # the seed is not their own collaborator
        if not args.include_all and not is_musical(entry):
            dropped += 1
            continue
        albums = sorted(entry["albums"].values(), key=lambda a: a["date"] or "")
        top_role = entry["roles"].most_common(1)[0][0] if entry["roles"] else None
        classes = classify_roles(entry["roles"])
        kept.append({
            "key": key,
            "names": sorted(entry["names"]),
            "classes": classes,
            # True when the ONLY link is having written something the seed
            # recorded -- a cover, not a collaboration.
            "cover_source_only": classes == ["writing"],
            "roles": dict(entry["roles"].most_common()),
            "albums": albums,
            "stats": {"albums": len(albums), "tracks": entry["tracks"],
                      "top_role": top_role,
                      "first": albums[0]["date"] if albums else None,
                      "last": albums[-1]["date"] if albums else None},
        })

    # Albums first, tracks as tie-break: album count reflects the seed choosing
    # this person again, where track count just reflects album length.
    kept.sort(key=lambda p: (-p["stats"]["albums"], -p["stats"]["tracks"], p["key"]))

    out = Path(args.out) if args.out else DATA / f"discovery_{args.artist}.json"
    out.write_text(json.dumps({
        "version": 1,
        "generated": dt.date.today().isoformat(),
        "seed": {"qobuz_id": args.artist, "name": seed_name, "store": args.store,
                 "releases": len(releases), "albums_fetched": fetched,
                 "albums_failed": failed,
                 "tracks": total_tracks, "credited_tracks": credited_tracks},
        "people": kept,
        "dropped_non_musical": dropped,
    }, indent=2, ensure_ascii=False))

    multi = [p for p in kept if p["stats"]["albums"] >= 2]
    covers = [p for p in kept if p["cover_source_only"]]
    by_class = collections.Counter(c for p in kept for c in p["classes"])
    print(f"\n{credited_tracks}/{total_tracks} tracks credited"
          f"{f' ({failed} albums failed)' if failed else ''}")
    print(f"{len(kept)} musical people kept, {dropped} non-musical dropped")
    print(f"{len(multi)} appear on 2+ of the seed's albums")
    print("by class: " + ", ".join(f"{k} {v}" for k, v in by_class.most_common()))
    print(f"{len(covers)} are cover sources only (wrote a song the seed recorded, "
          "never worked with them)")
    print("\ntop 10:")
    for person in kept[:10]:
        s = person["stats"]
        print(f"  {s['albums']:>2} alb {s['tracks']:>3} tr  "
              f"{person['names'][0][:30]:<30} {s['top_role']}")
    print(f"\nwrote {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
