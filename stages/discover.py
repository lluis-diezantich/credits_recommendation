#!/usr/bin/env python3
"""Step 1 of 2 - DISCOVERY: who made a seed artist's records.

Walks every release by each seed artist given, reads the per-track `performers`
credits Qobuz ships with each album, and reduces them to distinct people with
the evidence for each: which of the seed's albums they worked on, how many
tracks, and in what roles. One file per seed, one `walk()` per seed, and the
storefront login and the alias file read once for the run.

Exact and cacheable: this only parses what Qobuz already returned, so it does no
name matching and makes no guesses. The fuzzy part (name -> Qobuz artist id) is
qobuz_resolve.py, kept separate so it can be re-run without re-crawling albums.

No login, no API key -- a public app id plus the cookies any storefront page
issues. Album credits are cached, so a second run costs one request.

    ./stages/discover.py                     # the seed in SEED_ARTIST
    ./stages/discover.py --artist 41620
    ./stages/discover.py --artist 219860 148515 717509      # in one run
    ./stages/discover.py --include-all       # keep artwork/studio people too
    ./stages/discover.py --refresh           # ignore the credits cache

`./stages/seeds.py --next 5` prints the ids worth walking, in the order worth
walking them (D26). A seed that cannot be read is fatal to its own file and not
to the batch, so the run reports which ones failed and exits non-zero.

--out and --mbid name ONE artist, so they are refused with several ids rather
than silently applied to the first: Björk's mbid on Residente's walk would
label his own records as somebody else's.

Writes discovery_<artist_id>.json per seed, the input to resolve_qobuz.py.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import difflib
import itertools
import json
import sys
import time
import urllib.parse
from pathlib import Path

from core import aliases, favourites, musicbrainz
from core.credits import main_artists, parse_performers
from core.names import normalise
from core.paths import CACHE, DATA
from core.qobuz import API, APP_ID, PAUSE, STORE, artist_releases, store_cookies
from core.qobuz import get as _get
from core.qobuz import message as _message
from policy import MUSICAL_ROLES, album_provenance, alias_candidate, classify_roles

CACHE_DIR = CACHE / "credits"

SEED_ARTIST = 41620          # Jorge Drexler


def seed_releases(artist_id: int, store: str, cookies: str) -> tuple[str, list[dict]]:
    """(seed name, releases where the seed is a primary artist).

    A partial discography IS fatal here, unlike in the radars: every later
    number in the file -- who the seed worked with, on how many albums -- is
    computed over this list, so a half-read one produces a plausible,
    silently wrong discovery file. core.qobuz has already warned with the
    API's own message by the time this raises.
    """
    name, releases, ok = artist_releases(artist_id, store, cookies)
    if not ok:
        raise SystemExit(f"could not read the discography for artist {artist_id} "
                         "- see the warning above")
    return name, releases


def album_tracks(album_id: str, store: str, cookies: str,
                 refresh: bool) -> tuple[list[dict] | None, bool]:
    """(tracks for one album, came-from-cache). None tracks means it failed.

    The second value exists so the caller can skip the politeness pause on a
    cache hit. Without it, a fully cached re-run still slept PAUSE per release
    and took half a minute to do nothing.
    """
    CACHE_DIR.mkdir(exist_ok=True)
    safe = urllib.parse.quote(str(album_id), safe="")
    cached = CACHE_DIR / f"{store}_{safe}.json"
    if cached.exists() and not refresh:
        try:
            return json.loads(cached.read_text()), True
        except (json.JSONDecodeError, OSError):
            pass   # fall through and refetch
    zone = store.split("-")[0].upper()
    query = urllib.parse.urlencode({"album_id": album_id, "zone": zone, "store": store})
    status, body, _ = _get(f"{API}/album/get?{query}",
                           {"x-app-id": APP_ID, "cookie": cookies})
    if status != 200:
        print(f"warning: album/get {album_id} HTTP {status}: {_message(body)}", file=sys.stderr)
        return None, False
    try:
        tracks = (json.loads(body).get("tracks") or {}).get("items") or []
    except json.JSONDecodeError:
        print(f"warning: album/get {album_id} returned non-JSON", file=sys.stderr)
        return None, False
    # Cache only what this step needs.
    slim = [{"id": t.get("id"), "title": t.get("title"),
             "performers": t.get("performers") or ""} for t in tracks]
    cached.write_text(json.dumps(slim))
    return slim, False


def fold_editions(albums: list[dict]) -> list[dict]:
    """One row per release, not per edition, keeping the earliest of each.

    Qobuz issues a single under several album ids -- "WE PRAY", the Coldplay
    single Little Simz features on, is FIVE -- so counting album ids made
    Coldplay, Burna Boy, Elyanna and tINI score five co-appearances off one
    song. Bjork's discography is 141 ids for 99 titles.

    Folded on normalise(title), which is the only key the two editions share:
    there is no release group id in what Qobuz returns here. That is coarse on
    purpose and it has one known cost -- a genuine reissue with a different
    track list folds into the original, as "Granada" does in the Perez Cruz
    corpus (15 tracks and 21) -- and for counting who someone made records
    with, those two ARE one record.
    """
    folded: dict[str, dict] = {}
    for album in sorted(albums, key=lambda a: a.get("date") or ""):
        folded.setdefault(normalise(album.get("title") or ""), album)
    return list(folded.values())


def seed_names(qobuz_id: int, name: str, mbid: str | None) -> tuple[set[str], int]:
    """(every key the seed is credited under, how many MusicBrainz added).

    Qobuz credits a record to whichever name the label filed, so the seed is
    their own biggest "collaborator" wherever that is not their performing
    name: "Bjork Gudmundsdottir" held 120 of Bjork's 148 own albums, and
    "Simbiatu Ajikawo" 20 of Little Simz's 44. Both read as the top of their
    own crew graph until something knows they are the seed.

    One request, cached, and the mbid comes off data/favourites.json, which
    already carries one per artist. Without an mbid this returns just the
    performing name -- the old behaviour, and the caller says so out loud.
    """
    keys = {normalise(name)}
    if not mbid:
        return keys, 0
    found = {normalise(n) for n in musicbrainz.names(musicbrainz.artist(mbid))}
    return keys | found, len(found - keys)


def album_billing(tracks: list[dict], seed_keys) -> tuple[str, list[str]]:
    """(provenance, the other artists billed on this album).

    `seed_keys` is every name the seed is credited under, not one: a record
    billed to "Bjork Gudmundsdottir" is still Bjork's own record, and reading
    only the performing name files it as a guest spot.

    Pure and offline: `tracks` is what album_tracks already returned, so this
    makes no request and the labelling of a whole discography costs nothing.

    Both halves answer the same question -- who is this record BY -- and the
    answer runs in two directions, which is why they come back together:

        own    the seed is billed on it, and the others billed alongside are
               the guests on the seed's record
        guest  the seed is not billed, so the record is the OTHER artist's and
               the seed is the guest on theirs

    Either way the names returned are artists the seed has made a record with,
    and that is a different list from the people who worked ON the seed's
    records -- the crew graph the rest of this file builds.

    There is a third answer, and it is why the top billed share is counted here
    as well as the seed's: on a various-artists record nobody holds the sleeve,
    so it is neither. "Army Of Me" is 20 tracks by 20 artists and labelled as
    20 separate guest spots until something asks who holds the most of it.
    """
    seed_billed = billed_tracks = 0
    held: collections.Counter[str] = collections.Counter()
    others: dict[str, str] = {}
    for track in tracks:
        billed = main_artists(track.get("performers") or "")
        if not billed:
            continue
        billed_tracks += 1
        keys = {normalise(name) for name in billed}
        if keys & set(seed_keys):
            seed_billed += 1
        for name in billed:
            if normalise(name) not in seed_keys:
                held[normalise(name)] += 1
                others.setdefault(normalise(name), name)
    # The seed's own count is the union across every name they are filed
    # under, which is what seed_billed already holds -- summing `held` per key
    # would split one artist's hold over two spellings and read a record they
    # plainly own as a compilation.
    top_billed = max(seed_billed, max(held.values(), default=0))
    return (album_provenance(seed_billed, billed_tracks, top_billed),
            list(others.values()))


def collapse_credits(performers: str, alias_map) -> dict[str, dict]:
    """One track's credits as key -> {names, roles}, collapsed by person.

    Collapsed BEFORE anything is counted, because two spellings of one person
    can both be credited on one track -- Inflo as Producer and Dean Josiah
    Cover as Composer on 37 of them, Arca as FeaturedArtist and Alejandro
    Ghersi as Composer on 14. Accumulating per parsed name would count the
    track twice for that person and each of their roles twice, so the merge
    would inflate exactly the people it was written to fix.

    `names` holds every spelling the track used, first-seen first, and
    `roles` is an ordered set -- a dict with None values -- so the album's
    role list does not depend on set iteration order and a rebuild on another
    day produces the same file.
    """
    out: dict[str, dict] = {}
    for name, roles in parse_performers(performers):
        slot = out.setdefault(aliases.person_key(name, alias_map),
                              {"names": [], "roles": {}})
        if name not in slot["names"]:
            slot["names"].append(name)
        for role in roles:
            slot["roles"].setdefault(role, None)
    return out


def preferred_first(names, key: str, display: dict[str, str]) -> list[str]:
    """Every spelling seen, with the alias file's own name at the front.

    `names[0]` is what every consumer prints, and a merged person sorted
    alphabetically shows the wrong one of their names -- the legal one, which
    is the half of the split nobody recognises.
    """
    ordered = sorted(names)
    wanted = display.get(key)
    if not wanted:
        return ordered
    return [wanted] + [name for name in ordered if name != wanted]


def alias_report(keys) -> dict[str, list[tuple[str, str]]]:
    """Pairs of person keys that might be one person, grouped by why.

    The feeder for `data/aliases.json`, which is hand-edited because nothing
    on disk can decide these -- see core/aliases.py for what was measured and
    rejected. This only reports: `policy.alias_candidate` holds the rule, and
    neither of them merges anything.

    O(n^2) over one seed's people, which is 287 at the worst and costs
    nothing next to the walk that produced them.
    """
    def ratio(a: str, b: str) -> float:
        return difflib.SequenceMatcher(None, a, b).ratio()

    found: dict[str, list[tuple[str, str]]] = {}
    for a, b in itertools.combinations(sorted(keys), 2):
        kind = alias_candidate(a, b, ratio)
        if kind:
            found.setdefault(kind, []).append((a, b))
    return found


def walk(artist_id: int, cookies: str, alias_map, alias_display, args) -> int:
    """One seed, end to end: fetch, reduce, write discovery_<id>.json, report.

    Extracted from main() so several seeds can be walked in one run -- the five
    guaranteed intersections D26 puts first are one command now rather than
    five. The body is unchanged; what moved out is the login and the alias
    file, which are per-RUN and were being re-read per seed.

    Raises SystemExit for anything fatal to THIS seed, which the caller catches
    so one bad discography does not waste the walks queued behind it. A partial
    discography is still fatal -- seed_releases says why -- it is just fatal to
    one file instead of to the batch.
    """
    seed_name, releases = seed_releases(artist_id, args.store, cookies)
    if not releases:
        raise SystemExit(f"no releases for artist {artist_id} in the {args.store} store")
    print(f"seed: {seed_name} ({artist_id}) - {len(releases)} releases", file=sys.stderr)
    mbid = args.mbid or favourites.mbid_for(artist_id)
    seed_keys, from_mb = seed_names(artist_id, seed_name, mbid)
    if mbid:
        print(f"  seed credited under {len(seed_keys)} names "
              f"({from_mb} from MusicBrainz)", file=sys.stderr)
    else:
        print("  no mbid for this artist in favourites.json: only the exact "
              "performing name will be dropped, so check the top of the "
              "people list below for the seed under another spelling",
              file=sys.stderr)

    # key -> evidence
    people: dict[str, dict] = collections.defaultdict(
        lambda: {"names": set(), "roles": collections.Counter(), "albums": {}, "tracks": 0})
    # key -> the albums that bill this artist alongside the seed
    co_artists: dict[str, dict] = collections.defaultdict(
        lambda: {"names": set(), "albums": []})
    provenances: collections.Counter[str] = collections.Counter()
    # Spellings the alias file folded into somebody else's key, so the run can
    # say what it applied rather than leaving a silent merge in the counts.
    merged_names: set[str] = set()
    credited_tracks = 0
    total_tracks = 0
    failed = 0
    fetched = 0

    for index, release in enumerate(releases, 1):
        tracks, from_cache = album_tracks(release["id"], args.store, cookies, args.refresh)
        if tracks is None:
            failed += 1
            continue
        fetched += 1
        provenance, billed_with = album_billing(tracks, seed_keys)
        provenances[provenance] += 1
        for name in billed_with:
            key = aliases.person_key(name, alias_map)
            if normalise(name) in seed_keys or key in seed_keys:
                continue              # the seed, under a name Qobuz filed
            entry = co_artists[key]
            entry["names"].add(name)
            entry["albums"].append({
                "album_id": str(release["id"]),
                "title": release.get("title"),
                "date": (release.get("release_date_original") or "")[:10],
                "provenance": provenance})
        for track in tracks:
            total_tracks += 1
            credits = (track.get("performers") or "").strip()
            if not credits:
                continue
            credited_tracks += 1
            per_track = collapse_credits(credits, alias_map)
            for slot in per_track.values():
                # What the FILE folded, not what the track spelled twice: two
                # spellings that already share a normalised key were never a
                # merge and must not be reported as one.
                merged_names.update(
                    name for name in slot["names"]
                    if aliases.person_key(name, alias_map) != normalise(name))
            for key, slot in per_track.items():
                entry = people[key]
                entry["names"].update(slot["names"])
                entry["tracks"] += 1
                for role in slot["roles"]:
                    entry["roles"][role] += 1
                album = entry["albums"].setdefault(str(release["id"]), {
                    "album_id": str(release["id"]),
                    "title": release.get("title"),
                    "date": (release.get("release_date_original") or "")[:10],
                    # own or guest: a credit on a record the seed only sang on
                    # is not a credit on the seed's record.
                    "provenance": provenance,
                    "roles": [], "tracks": 0})
                album["tracks"] += 1
                for role in slot["roles"]:
                    if role not in album["roles"]:
                        album["roles"].append(role)
        if index % 15 == 0:
            print(f"  ...{index}/{len(releases)}", file=sys.stderr)
        if not from_cache:
            time.sleep(PAUSE)

    def is_musical(entry: dict) -> bool:
        return any(r.lower() in MUSICAL_ROLES for r in entry["roles"])

    kept, dropped = [], 0
    dropped_as_seed: list[set[str]] = []
    for key, entry in people.items():
        if key in seed_keys:
            dropped_as_seed.append(entry["names"].copy())
            continue                      # the seed is not their own collaborator
        if not args.include_all and not is_musical(entry):
            dropped += 1
            continue
        albums = sorted(entry["albums"].values(), key=lambda a: a["date"] or "")
        billing = collections.Counter(a["provenance"] for a in albums)
        top_role = entry["roles"].most_common(1)[0][0] if entry["roles"] else None
        classes = classify_roles(entry["roles"])
        kept.append({
            "key": key,
            "names": preferred_first(entry["names"], key, alias_display),
            "classes": classes,
            # True when the ONLY link is having written something the seed
            # recorded -- a cover, not a collaboration.
            "cover_source_only": classes == ["writing"],
            "roles": dict(entry["roles"].most_common()),
            "albums": albums,
            # `albums` still counts both, so this file's existing numbers and
            # everything computed from them are unchanged; own_albums is what a
            # consumer should prefer, and resolve_qobuz.py does not yet.
            "stats": {"albums": len(albums), "tracks": entry["tracks"],
                      "own_albums": billing["own"], "guest_albums": billing["guest"],
                      "top_role": top_role,
                      "first": albums[0]["date"] if albums else None,
                      "last": albums[-1]["date"] if albums else None},
        })

    # Albums first, tracks as tie-break: album count reflects the seed choosing
    # this person again, where track count just reflects album length.
    kept.sort(key=lambda p: (-p["stats"]["albums"], -p["stats"]["tracks"], p["key"]))

    # Who the seed has made a record WITH, which is not who worked on the
    # seed's records: measured against real listening it carries 59% (Drexler)
    # and 40% (Perez Cruz) artists already played, against 13-16% for the crew
    # graph above -- see docs/adr/D14-co-appearance-is-its-own-output.md.
    together: list[dict] = []
    for key, entry in co_artists.items():
        albums = fold_editions(entry["albums"])
        billing = collections.Counter(a["provenance"] for a in albums)
        together.append({
            "key": key,
            "names": preferred_first(entry["names"], key, alias_display),
            "albums": albums,
            # their_records: the seed was the guest. seed_records: they were.
            "stats": {"albums": len(albums),
                      "their_records": billing["guest"],
                      "seed_records": billing["own"],
                      "first": albums[0]["date"] if albums else None,
                      "last": albums[-1]["date"] if albums else None},
        })
    together.sort(key=lambda p: (-p["stats"]["albums"], p["key"]))

    out = Path(args.out) if args.out else DATA / f"discovery_{artist_id}.json"
    out.write_text(json.dumps({
        "version": 1,
        "generated": dt.date.today().isoformat(),
        "seed": {"qobuz_id": artist_id, "name": seed_name, "store": args.store,
                 "releases": len(releases), "albums_fetched": fetched,
                 "albums_failed": failed,
                 "albums_own": provenances["own"],
                 "albums_guest": provenances["guest"],
                 "albums_compilation": provenances["compilation"],
                 "albums_unbilled": provenances["unknown"],
                 "tracks": total_tracks, "credited_tracks": credited_tracks},
        "people": kept,
        "co_artists": together,
        "dropped_non_musical": dropped,
    }, indent=2, ensure_ascii=False))

    own_albums = provenances["own"]
    multi = [p for p in kept if p["stats"]["albums"] >= 2]
    covers = [p for p in kept if p["cover_source_only"]]
    by_class = collections.Counter(c for p in kept for c in p["classes"])
    print(f"\n{credited_tracks}/{total_tracks} tracks credited"
          f"{f' ({failed} albums failed)' if failed else ''}")
    unbilled = provenances["unknown"]
    compilations = provenances["compilation"]
    print(f"{provenances['own']} of {fetched} albums are the seed's own, "
          f"{provenances['guest']} are guest spots on someone else's"
          + (f", {compilations} various-artists records nobody holds"
             if compilations else "")
          + (f", {unbilled} with nobody billed" if unbilled else ""))
    if dropped_as_seed:
        shown = ", ".join(sorted(n for names in dropped_as_seed for n in names)[:4])
        print(f"{len(dropped_as_seed)} credits were the seed under another name "
              f"({shown}) - not collaborators")
    print(f"{len(kept)} musical people kept, {dropped} non-musical dropped")
    # The residue MusicBrainz cannot catch: a spelling nobody recorded. Two of
    # Little Simz's three self-credits are like this, so the top of the list is
    # printed with its share for a human to check rather than fuzzy-matched.
    if kept and own_albums:
        top = kept[0]
        share = (top["stats"].get("own_albums") or 0) / own_albums
        if share >= 0.5:
            print(f"CHECK: {top['names'][0]} holds {share:.0%} of the seed's own "
                  "albums - if that is the seed under a spelling MusicBrainz "
                  "does not know, add it to the mbid's aliases there")
    print(f"{len(multi)} appear on 2+ of the seed's albums")
    print("by class: " + ", ".join(f"{k} {v}" for k, v in by_class.most_common()))
    print(f"{len(covers)} are cover sources only (wrote a song the seed recorded, "
          "never worked with them)")
    print(f"{len(together)} artists share a billing with the seed "
          f"(made a record WITH them, not ON their records)")
    print("\nbilled with the seed, top 10:")
    for artist in together[:10]:
        s = artist["stats"]
        print(f"  {s['albums']:>2} alb  {artist['names'][0][:30]:<30} "
              f"{s['seed_records']} on the seed's, {s['their_records']} on their own")
    print("\ntop 10:")
    for person in kept[:10]:
        s = person["stats"]
        print(f"  {s['albums']:>2} alb {s['tracks']:>3} tr  "
              f"{person['names'][0][:30]:<30} {s['top_role']}")
    if merged_names:
        print(f"{len(merged_names)} spellings folded by {aliases.FILE}: "
              + ", ".join(sorted(merged_names)[:6])
              + (" ..." if len(merged_names) > 6 else ""))
    elif not alias_map:
        print(f"no {aliases.FILE} - one person under two names counts as two")
    candidates = alias_report(p["key"] for p in kept)
    if candidates:
        display = {p["key"]: p["names"][0] for p in kept}
        counts = {p["key"]: p["stats"]["albums"] for p in kept}
        print("\nmight be one person, NOT merged - add to "
              f"{aliases.FILE} if they are:")
        for kind in ("subset", "spelling", "bare"):
            for a, b in candidates.get(kind, []):
                print(f"  {kind:<8} {counts[a]:>2}+{counts[b]:<2} "
                      f"{display[a][:32]:<32} | {display[b][:32]}")
    print(f"\nwrote {out.name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover who made a seed artist's records.")
    parser.add_argument("--artist", type=int, nargs="+", default=[SEED_ARTIST],
                        metavar="ID",
                        help="one or more Qobuz seed artist ids, walked in order")
    parser.add_argument("--store", default=STORE, help=f"storefront (default: {STORE})")
    parser.add_argument("--include-all", action="store_true",
                        help="keep people with no musical role (designers, studios)")
    parser.add_argument("--refresh", action="store_true", help="ignore the credits cache")
    parser.add_argument("--mbid", help="seed's MusicBrainz id (default: from favourites.json)")
    parser.add_argument("--out", help="output path (default: discovery_<artist_id>.json)")
    args = parser.parse_args()

    if len(args.artist) > 1:
        for flag, value in (("--out", args.out), ("--mbid", args.mbid)):
            if value:
                raise SystemExit(f"{flag} names one artist, and {len(args.artist)} "
                                 "were given - run them one at a time")

    # Once per run, not once per seed: a storefront cookie is good for the
    # whole batch and the alias file does not change while it is walking.
    alias_map = aliases.load()
    alias_display = aliases.display_names()
    cookies = store_cookies(args.store)

    failed: list[int] = []
    for position, artist_id in enumerate(args.artist, 1):
        if len(args.artist) > 1:
            print(f"\n=== {position}/{len(args.artist)}: artist {artist_id} ===",
                  file=sys.stderr)
        try:
            if walk(artist_id, cookies, alias_map, alias_display, args) != 0:
                failed.append(artist_id)
        except SystemExit as stop:
            # Fatal to this seed, not to the ones behind it.
            print(f"artist {artist_id}: {stop}", file=sys.stderr)
            failed.append(artist_id)

    if len(args.artist) > 1:
        walked = len(args.artist) - len(failed)
        print(f"\n{walked} of {len(args.artist)} seeds walked", file=sys.stderr)
        print("read each one's 'might be one person' list above and add to "
              f"{aliases.FILE} before ranking (D25), then ./stages/load.py",
              file=sys.stderr)
    if failed:
        print("failed: " + ", ".join(str(a) for a in failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
