#!/usr/bin/env python3
"""Step 3 - WRITING: what one person wrote, including for other artists.

The rest of the pipeline runs outward from a seed: seed -> credits -> people ->
their releases. This runs the other way. Given one person, it finds the songs
they are CREDITED AS WRITING, on anyone's record.

That direction has no index in the sources this project already uses:

    Qobuz  artist/get      only albums where they are a BILLED artist
    Discogs /artists/{id}/releases   379 rows for Drexler, zero writing roles
                                     (Written-By lives in the per-release
                                      tracklist, not the artist index)
    MusicBrainz work?artist=         has it, but only 42 authored works against
                                     the 162 songs Qobuz already proves he wrote

Qobuz `track/search` does have it, which is not obvious: it matches against the
per-track `performers` credit string, so searching a PERSON'S NAME returns
tracks they are credited on in any role, with the credits inline in the
response. No per-album fetch. 910 rows for Drexler in ten requests.

Two rules make the output mean what it says, both in policy.py:

  writing_tier()   Lyricist-while-someone-else-composes is not the same as
                   having written the song. Three tiers, and the ambiguous one
                   is flagged rather than dropped.
  TITLE_ALIASES    "La Edad Del Cielo" and "A Idade do Céu" are one song. No
   + fuzzy fold    string folding finds that; a curated table does.

Also flagged, because both were large enough to distort a real run: album-wide
credit smear (every track of "Amigo É Casa" carries `Jorge Drexler, Author` --
26 of 227 pairs) and covers mills (9 of 19 "performers" of "Al Otro Lado Del
Río"). Flags, not filters: the judgement stays yours.

    ./stages/writing.py --artist "Jorge Drexler" --alias "Jorge Abner Drexler"
    ./stages/writing.py --artist "Bebu Silvetti" --explain-gate   # 1 request
    ./stages/writing.py --from-watchlist          # everyone worth asking about
    ./stages/writing.py --artist "X" --tier authored --for-others-only

Writes writing_<slug>.json.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import difflib
import json
import re
import sys
import time
import unicodedata
import urllib.parse
from pathlib import Path

from core.credits import parse_performers
from core.names import normalise
from core.paths import CACHE, DATA
from core.qobuz import API, APP_ID, PAUSE, STORE, get_json
from policy import (
    COMPOSER_ROLES,
    COVERS_MILL_HINTS,
    MIN_WRITING_SHARE,
    PERFORMANCE_ROLES,
    TITLE_ALIASES,
    TITLE_SIMILARITY,
    WRITING_ROLES,
    role_key,
    writing_tier,
)

SEARCH_PAGE = 100            # track/search caps at 100 per call
MAX_PAGES = 25               # 2,500 rows; Drexler needed 10
CACHE_DIR = CACHE / "search"


# ---- parsing -------------------------------------------------------------


def credits_by_person(performers: str) -> dict[str, set[str]]:
    """Whole `performers` string -> {normalised name: {role_key, ...}}.

    A fold over core.credits.parse_performers, which owns the parsing and the
    co-artist rule. Every person is kept, not one, because writing_tier() has
    to know whether SOMEBODY ELSE composed. Names collapse via normalise() and
    roles via role_key(), so "Co- Producer" and "CoProducer" meet -- the two
    foldings that live outside core on purpose.
    """
    out: dict[str, set[str]] = collections.defaultdict(set)
    for name, roles in parse_performers(performers):
        if roles:
            out[normalise(name)] |= {role_key(role) for role in roles}
    return out


def title_key(title: str) -> str:
    """Fold a track title to a song key.

    Strips accents, case, bracketed and parenthesised decoration (feat., en
    vivo, Remix, Original Version, Radio Edit) and punctuation. This gets
    variants of the SAME title; TITLE_ALIASES gets translations.
    """
    text = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", text)
    text = re.sub(r"\b(feat|ft|with)\b.*$", " ", text)
    text = re.sub(r"\s+-\s+.*$", " ", text)          # "Frontera - Drexler"
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text).split())


def collapse(keys: list[str]) -> dict[str, str]:
    """key -> canonical key, applying TITLE_ALIASES then a fuzzy merge.

    The fuzzy pass catches typos and cross-language spellings ("orcuridad",
    "Reio"). Longest key wins as canonical so the fuller title survives, and
    merging is single-pass rather than transitive: chaining A~B~C would let two
    dissimilar titles end up in one bucket.
    """
    mapping = {k: TITLE_ALIASES.get(k, k) for k in keys}
    canon = sorted(set(mapping.values()), key=lambda k: (-len(k), k))
    for key in list(mapping):
        target = mapping[key]
        if target in canon and target != key:
            continue
        for other in canon:
            if other == target or len(other) <= len(target):
                continue
            if difflib.SequenceMatcher(None, target, other).ratio() >= TITLE_SIMILARITY:
                mapping[key] = other
                break
    return mapping


def is_covers_mill(name: str) -> bool:
    low = normalise(name)
    return any(hint in low for hint in COVERS_MILL_HINTS)


# ---- fetching ------------------------------------------------------------


def search_page(query: str, offset: int, store: str,
                refresh: bool = False) -> tuple[list[dict], int, bool]:
    """One page of track/search, cached on disk. -> (items, total, from_cache).

    Cached for the same reason discover.py caches album/get: track/search is NOT
    stable. The same query returned 654 writing rows one run and 683 the next,
    with identical `total` and page sizes both times -- the index shifts
    underneath you. Without a cache the output file is not reproducible, and a
    change in the numbers cannot be told apart from a change you made to
    TITLE_ALIASES or a tier rule.

    Note that `store` narrows the result set (910 rows unscoped, 827 for gb-en),
    so it is part of the cache key along with the query and the offset.

    Only the fields this step reads are stored, as in discover.py -- the nested
    shape is kept so callers need no changes.
    """
    CACHE_DIR.mkdir(exist_ok=True)
    safe = urllib.parse.quote(query, safe="")
    cached = CACHE_DIR / f"{store}_{safe}_{offset}.json"
    if cached.exists() and not refresh:
        try:
            blob = json.loads(cached.read_text())
            return blob["items"], blob["total"], True
        except (json.JSONDecodeError, OSError, KeyError):
            pass   # fall through and refetch
    url = f"{API}/track/search?" + urllib.parse.urlencode(
        {"query": query, "limit": SEARCH_PAGE, "offset": offset,
         "app_id": APP_ID, "store": store})
    # Qobuz returns intermittent 5xx under sustained load, and a transient
    # failure must not look like the end of the result set
    # (qobuz_resolve.py:81). The retrying is core.http's adapter's job now --
    # with jitter and Retry-After, which the loop that used to sit here
    # ignored -- so an outcome arriving back is already final. get_json has
    # warned by this point; `False` for "not from the cache" is all that is
    # left to say.
    data, outcome = get_json(url, {"x-app-id": APP_ID},
                             f"track/search {query!r} at offset {offset}")
    if outcome != "ok" or not isinstance(data, dict):
        return [], 0, False
    block = data.get("tracks") or {}
    items = block.get("items") or []
    total = int(block.get("total") or 0)
    slim = [{"title": t.get("title"),
             "performers": t.get("performers") or "",
             "performer": {"name": (t.get("performer") or {}).get("name")},
             "album": {"title": (t.get("album") or {}).get("title"),
                       "id": (t.get("album") or {}).get("id")}} for t in items]
    cached.write_text(json.dumps({"total": total, "items": slim}))
    return slim, total, False


def writing_share(items: list[dict], aliases: set[str]) -> tuple[int, int]:
    """(tracks where they hold a writing role, tracks where they are credited).

    The gate. Computed on page 1 only, in the same spirit as the page-1 gate in
    core/discogs.py: the cheapest request already carries enough to decide
    whether the rest are worth paying for.
    """
    credited = writing = 0
    for track in items:
        roles = credits_by_person(track.get("performers") or "")
        mine: set[str] = set()
        for name, r in roles.items():
            if name in aliases:
                mine |= r
        if not mine:
            continue
        credited += 1
        if mine & WRITING_ROLES:
            writing += 1
    return writing, credited


# ---- main ----------------------------------------------------------------


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalise(text)).strip("-") or "artist"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find the songs one person is credited as writing, on anyone's record.")
    parser.add_argument("--artist", help="name as it appears in credits")
    parser.add_argument("--alias", action="append", default=[],
                        help="another spelling to accept (Qobuz credits Drexler both as "
                             "'Jorge Drexler' and 'Jorge Abner Drexler'); repeatable")
    parser.add_argument("--from-watchlist", metavar="FILE", nargs="?", const="watchlist.json",
                        help="run over the people in a watchlist whose classes include "
                             "'writing' - the free relevance gate, costs no requests")
    parser.add_argument("--store", default=STORE)
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES,
                        help=f"pages of {SEARCH_PAGE} (default {MAX_PAGES})")
    parser.add_argument("--min-writing-share", type=float, default=MIN_WRITING_SHARE,
                        help="after page 1, stop unless this share of their credits carry a "
                             "writing role. 0 disables")
    parser.add_argument("--explain-gate", action="store_true",
                        help="fetch page 1, print the gate decision, stop. Costs ONE request "
                             "- unlike resolve_discogs.py's free gate, the share is not "
                             "knowable without looking")
    parser.add_argument("--tier", action="append", default=[],
                        choices=["authored", "lyrics_only", "adaptation"],
                        help="keep only these tiers (default: all, each labelled)")
    parser.add_argument("--for-others-only", action="store_true",
                        help="drop songs they also perform on - leaves only songs handed to "
                             "another artist")
    parser.add_argument("--refresh", action="store_true",
                        help="ignore the search cache. track/search is not stable between "
                             "runs, so the cache is what makes the output reproducible")
    parser.add_argument("--out", help="output path (default: writing_<slug>.json)")
    args = parser.parse_args()

    if args.from_watchlist:
        return run_watchlist(args)
    if not args.artist:
        parser.error("--artist is required (or --from-watchlist)")
    return run_one(args, args.artist, args.alias)


def run_watchlist(args) -> int:
    """The relevance gate, for free: writing.py is only worth running on people
    already credited as writers somewhere.

    policy.WEAK_CLASSES drops writing-only people from the collaborator pool
    because a shared writing credit is not a working relationship. This selects
    exactly the set that discards -- the same judgement, read the other way.
    """
    path = DATA / args.from_watchlist
    if not path.exists():
        raise SystemExit(f"{path.name} not found - run ./stages/resolve_qobuz.py first")
    data = json.loads(path.read_text())
    people = [a for a in data.get("artists") or []
              if "writing" in (a.get("classes") or [])]
    print(f"{len(people)} of {len(data.get('artists') or [])} watchlist people carry a "
          f"writing credit (free gate, no requests)", file=sys.stderr)
    for person in people:
        names = person.get("name_variants") or [person.get("name")]
        print(f"\n=== {names[0]}", file=sys.stderr)
        run_one(args, names[0], names[1:])
        time.sleep(PAUSE)
    return 0


def run_one(args, artist: str, extra_aliases: list[str]) -> int:
    aliases = {normalise(a) for a in [artist, *extra_aliases] if a}

    items, total, cached = search_page(artist, 0, args.store, args.refresh)
    if not items:
        print(f"no credited tracks for {artist!r}")
        return 0
    writing, credited = writing_share(items, aliases)
    share = (writing / credited) if credited else 0.0

    if args.explain_gate or share < args.min_writing_share:
        verdict = "keep" if share >= args.min_writing_share else "GATED"
        print(f"{artist}: page 1 has {credited} credited track(s), {writing} with a writing "
              f"role -> share {share:.2f} vs min {args.min_writing_share} -> {verdict} "
              f"({total} total rows would cost "
              f"{min(args.max_pages, -(-total // SEARCH_PAGE))} requests)")
        if args.explain_gate or verdict == "GATED":
            return 0

    pages = min(args.max_pages, max(1, -(-total // SEARCH_PAGE)))
    rows = list(items)
    requests = 0 if cached else 1
    cache_hits = 1 if cached else 0
    for page in range(1, pages):
        more, _, was_cached = search_page(artist, page * SEARCH_PAGE, args.store, args.refresh)
        requests += 0 if was_cached else 1
        cache_hits += 1 if was_cached else 0
        if not more:
            break
        rows += more
        time.sleep(PAUSE)
    print(f"{artist}: fetched {len(rows)} of {total} rows in {requests} request(s)"
          f"{f', {cache_hits} page(s) from cache' if cache_hits else ''}", file=sys.stderr)

    # ---- classify each row ------------------------------------------------
    writing_hits, own = [], 0
    for track in rows:
        people = credits_by_person(track.get("performers") or "")
        mine: set[str] = set()
        for name, roles in people.items():
            if name in aliases:
                mine |= roles
        if not (mine & WRITING_ROLES):
            continue
        co_composers = [name for name, roles in people.items()
                        if name not in aliases and (roles & COMPOSER_ROLES)]
        others_compose = bool(co_composers)
        tier = writing_tier(mine, others_compose)
        performer = ((track.get("performer") or {}).get("name") or "")
        performs = bool(mine & PERFORMANCE_ROLES) or normalise(performer) in aliases
        if performs:
            own += 1
        writing_hits.append({
            "title": track.get("title"), "key": title_key(track.get("title") or ""),
            # How many people this release credits at all. A master release
            # lists 40+; a karaoke re-record lists 2. Used to pick which
            # recording's tier to trust -- see below.
            "credit_depth": len(people),
            "co_composers": co_composers,
            "performer": performer, "album": ((track.get("album") or {}).get("title")),
            "album_id": ((track.get("album") or {}).get("id")),
            "tier": tier, "roles": sorted(mine & WRITING_ROLES),
            "performs": performs,
        })

    # ---- album-wide credit smear -----------------------------------------
    # Every track of "Amigo É Casa (Special Edition)" carries the same lone
    # Author credit. That is a blanket credit on the album, not authorship of
    # 25 songs. Signature: 4+ tracks from one album, all the same single role.
    by_album = collections.defaultdict(list)
    for hit in writing_hits:
        by_album[hit["album_id"]].append(hit)
    smeared = set()
    for album_id, group in by_album.items():
        roles = {tuple(h["roles"]) for h in group}
        if (album_id and len(group) >= 4 and len(roles) == 1
                and len(next(iter(roles))) == 1
                and not any(h["performs"] for h in group)):
            smeared.add(album_id)
            for hit in group:
                hit.setdefault("flags", []).append("album_wide_credit")

    # ---- collapse titles into songs --------------------------------------
    canon = collapse([h["key"] for h in writing_hits])
    songs: dict[str, dict] = {}
    for hit in writing_hits:
        key = canon[hit["key"]]
        song = songs.setdefault(key, {
            "song": key, "titles": collections.Counter(), "tier": "none",
            "_depth": -1, "roles": set(), "tier_votes": collections.Counter(),
            "co_composers": collections.Counter(),
            "performers": {}, "flags": set(), "own_recording": False})
        song["titles"][hit["title"]] += 1
        song["roles"] |= set(hit["roles"])
        # Trust the DEEPEST credit block, not the strongest claim. Taking the
        # strongest made "Waka Waka" come out `authored`: karaoke re-records
        # credit Drexler as Composer, while Shakira's master -- 44 credit lines,
        # with the Zangalewa authors holding Composer -- has him as Lyricist
        # only. A 2-line stub must not outvote that.
        song["tier_votes"][hit["tier"]] += 1
        song["co_composers"].update(hit["co_composers"])
        song["_depth"] = max(song["_depth"], hit["credit_depth"])
        song["flags"] |= set(hit.get("flags") or [])
        if hit["performs"]:
            song["own_recording"] = True
            continue
        entry = song["performers"].setdefault(normalise(hit["performer"]), {
            "name": hit["performer"], "albums": set(),
            "covers_mill": is_covers_mill(hit["performer"])})
        if hit["album"]:
            entry["albums"].add(hit["album"])

    out_songs = []
    for song in songs.values():
        # Plurality across recordings, not one chosen recording. Trusting the
        # deepest credit block alone made "12 Segundos de Oscuridad" -- his own
        # song -- come out lyrics_only, because Vitor Ramil's cover credits
        # Ramil as composer. Five recordings say authored, two say otherwise.
        song["tier"] = song["tier_votes"].most_common(1)[0][0] if song["tier_votes"] else "none"
        performers = sorted(song["performers"].values(), key=lambda p: normalise(p["name"]))
        real = [p for p in performers if not p["covers_mill"]]
        out_songs.append({
            "song": song["song"],
            "title": min(song["titles"], key=lambda t: (-song["titles"][t], len(t), t)),
            "variants": sorted(song["titles"]),
            # A HINT, from the deepest credit block. Cover and karaoke
            # metadata is wrong in both directions -- it credits Drexler as
            # Composer on "Waka Waka" (he wrote only the Spanish lyric) and
            # credits the cover artist as Composer on "12 Segundos de
            # Oscuridad" (his own song). No single recording settles it, so
            # read co_composers and tier_votes, not this field alone.
            "tier": song["tier"],
            "tier_votes": dict(song["tier_votes"].most_common()),
            "tier_disagreement": len(song["tier_votes"]) > 1,
            # Everyone else credited as composer on any recording, with counts.
            # This is the actual evidence: co_composers naming the Zangalewa
            # authors means the song is not his; a single name matching the
            # cover artist means the cover's metadata is junk.
            "co_composers": dict(song["co_composers"].most_common(8)),
            "roles": sorted(song["roles"]),
            "own_recording": song["own_recording"],
            "performer_count": len(performers),
            "performer_count_excl_mills": len(real),
            "performers": [{"name": p["name"], "albums": sorted(p["albums"]),
                            "covers_mill": p["covers_mill"]} for p in performers],
            "flags": sorted(song["flags"]),
        })

    if args.tier:
        out_songs = [s for s in out_songs if s["tier"] in args.tier]
    if args.for_others_only:
        out_songs = [s for s in out_songs if s["performers"]]
    # Most independent recordings first; mills excluded from the sort so a
    # karaoke pile cannot outrank a Mercedes Sosa cover.
    out_songs.sort(key=lambda s: (-s["performer_count_excl_mills"],
                                  -s["performer_count"], s["song"]))

    out = Path(args.out) if args.out else DATA / f"writing_{slug(artist)}.json"
    out.write_text(json.dumps({
        "version": 1, "generated": dt.date.today().isoformat(),
        "artist": {"query": artist, "aliases": sorted(aliases), "store": args.store},
        "search": {"reported_total": total, "fetched": len(rows),
                   "requests": requests, "cached_pages": cache_hits,
                   "writing_rows": len(writing_hits), "own_recording_rows": own},
        "gate": {"writing_share": round(share, 3), "min": args.min_writing_share,
                 "passed": share >= args.min_writing_share},
        "rules": {"title_similarity": TITLE_SIMILARITY,
                  "aliased_titles": len(TITLE_ALIASES),
                  "smeared_albums": len(smeared)},
        "songs": out_songs,
    }, indent=2, ensure_ascii=False))

    tiers = collections.Counter(s["tier"] for s in out_songs)
    others = [s for s in out_songs if s["performers"]]
    print(f"\n{len(writing_hits)} writing rows -> {len(out_songs)} distinct songs "
          f"({len(others)} recorded by someone else)")
    print("  by tier: " + ", ".join(f"{k} {v}" for k, v in tiers.most_common()))
    if smeared:
        print(f"  {len(smeared)} album(s) flagged album_wide_credit")
    mills = sum(1 for s in out_songs for p in s["performers"] if p["covers_mill"])
    if mills:
        print(f"  {mills} performer row(s) flagged covers_mill")
    split = [s for s in out_songs if s["tier_disagreement"]]
    if split:
        print(f"  {len(split)} song(s) where recordings DISAGREE on the tier "
              f"- read co_composers")
    print("\ntop songs recorded by others:")
    for song in others[:12]:
        names = ", ".join(p["name"] for p in song["performers"] if not p["covers_mill"])
        mark = "?" if song["tier_disagreement"] else " "
        print(f"  {song['performer_count_excl_mills']:>2}  {song['title'][:30]:<32}"
              f"{song['tier']:<13}{mark} {names[:46]}")
    print(f"\nwrote {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
