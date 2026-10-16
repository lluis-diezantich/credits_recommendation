#!/usr/bin/env python3
"""Recover the people Qobuz could not resolve, using Discogs as a reverse index.

qobuz_resolve.py loses roughly 44% of discovered names, and it loses them where
it hurts: Qobuz indexes performers, not studio staff, so the top collaborator
(21 of the seed's albums) and the mastering engineer (13) have no Qobuz artist
page at all. Discogs has entities for everyone, and -- unlike Qobuz -- a real
person -> work index.

This does NOT map Discogs releases back to Qobuz releases; that would be a second
lossy per-release join. Instead it asks Discogs only "which ARTISTS did this
person work with", then resolves those artists in Qobuz, which is reliable
because billed artists do have Qobuz pages:

    unresolved name -> Discogs artist -> their credits -> the artists on them
                                                              |
                                    Qobuz autosuggest (exact) -+-> releases -> pool

Discogs needs no token, but is rate limited to 25 requests/minute (60 with a
token in DISCOGS_TOKEN). That is the binding constraint, so this processes the
most important unresolved people first and caps pagination.

    ./discogs_resolve.py                    # top 15 unresolved, 3 pages each
    ./discogs_resolve.py --top 40 --max-pages 6
    ./discogs_resolve.py --no-pool          # Discogs lookup only, skip Qobuz
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
from collections.abc import Callable
from pathlib import Path

# Run directly (./stages/discover.py) or as a module (python -m stages.discover):
# either way the project root has to be importable before core/policy resolve.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.paths import CACHE, DATA
from core.discogs import (NOT_A_CREDIT, Throttle, discogs_credits, discogs_get,
                          find_discogs_artist)
from core.names import normalise, strip_discogs_suffix
from core.qobuz import API, APP_ID, PAGE_LIMIT, SITE, STORE
from core.qobuz import PAUSE as QOBUZ_PAUSE
from core.qobuz import UA as QOBUZ_UA
from core.qobuz import get as _qobuz_get
from core.qobuz import store_cookies
from policy import (CLASS_NAMES, MIN_ROLE_WEIGHT, MIN_SIGNAL, person_role_weight,
                    person_roles, role_class, role_key, role_weight, selectivity)


def parse_role_selection(raw: str) -> tuple[set[str], set[str]]:
    """--roles accepts class names and/or specific roles, comma separated.

    Returns (selected classes, selected normalised role keys).
    """
    classes, roles = set(), set()
    for token in (t.strip() for t in raw.split(",")):
        if not token:
            continue
        if token.lower() in CLASS_NAMES:
            classes.add(token.lower())
        else:
            roles.add(role_key(token))
    return classes, roles


def wanted(person: dict, classes: set[str], roles: set[str], match_any: bool) -> bool:
    """Does this person's role selection include them?

    Default matches only their TOP role -- what they mainly are. --roles-any
    matches if any credited role qualifies, which lets in an engineer who once
    played guitar, so it is opt-in.
    """
    if not classes and not roles:
        return True                      # no selection = keep everyone
    have = person_roles(person)
    if not have:
        return False
    candidates = have if match_any else have[:1]
    for role in candidates:
        if role_key(role) in roles or role_class(role) in classes:
            return True
    return False


# ---- Qobuz side (same conventions as qobuz_resolve.py) -------------------


def qobuz_find_artist(name: str, store: str) -> tuple[dict | None, str]:
    """Exact-match an artist name to a Qobuz artist.

    Returns (hit, outcome) so "genuinely not in Qobuz" is distinguishable from
    "the request failed". Qobuz autosuggest returns intermittent HTTP 500 under
    sustained load, and treating that as a miss silently discarded 146 of 154
    collaborators on one run -- an error must never look like an answer.
    """
    url = f"{SITE}/v4/{store}/catalog/search/autosuggest?q={urllib.parse.quote(name)}"
    for attempt in range(3):
        status, body, _ = _qobuz_get(url, {"x-requested-with": "XMLHttpRequest"})
        if status == 200:
            try:
                candidates = json.loads(body).get("artists") or []
            except json.JSONDecodeError:
                return None, "bad_json"
            exact = [c for c in candidates
                     if normalise(c.get("name") or "") == normalise(name)]
            if not exact:
                return None, "not_found"
            exact.sort(key=lambda c: -(c.get("albumsCount") or 0))
            return exact[0], "exact"
        if status < 500:
            return None, f"http_{status}"
        time.sleep(0.8 * (attempt + 1))        # transient: back off and retry
    return None, "http_5xx"


def qobuz_releases(artist_id: int, store: str, cookies: str) -> list[dict]:
    zone = store.split("-")[0].upper()
    headers = {"x-app-id": APP_ID, "cookie": cookies}
    collected, offset = [], 0
    while True:
        query = urllib.parse.urlencode({
            "artist_id": artist_id, "extra": "albums_with_last_release",
            "limit": PAGE_LIMIT, "offset": offset, "zone": zone, "store": store})
        status, body, _ = _qobuz_get(f"{API}/artist/get?{query}", headers)
        if status != 200:
            return collected
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return collected
        page = (data.get("albums_without_last_release") or {}).get("items") or []
        collected += [a for a in page
                      if any(str(x.get("id")) == str(artist_id) for x in (a.get("artists") or []))]
        if len(page) < PAGE_LIMIT:
            return collected
        offset += PAGE_LIMIT


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recover Qobuz-unresolved people via Discogs, and turn them into a pool.")
    parser.add_argument("--in", dest="infile", default="watchlist.json",
                        help="watchlist json with an `unresolved` array")
    parser.add_argument("--out", default="discogs_watchlist.json")
    parser.add_argument("--pool-out", default="pool_discogs.json")
    parser.add_argument("--store", default=STORE)
    parser.add_argument("--top", type=int, default=15,
                        help="how many unresolved people to process, most seed albums first")
    parser.add_argument("--max-pages", type=int, default=3,
                        help="Discogs release pages per person (100 each)")
    parser.add_argument("--roles", default="",
                        help="only look up people whose TOP role is in this comma separated "
                             "list. Accepts classes (production, engineering, performance, "
                             "writing, billing) and/or specific roles "
                             "(\"Producer,Mixed by,Bass\"). Default: everyone.")
    parser.add_argument("--roles-any", action="store_true",
                        help="with --roles, match if ANY of their roles qualifies, not just "
                             "their top one")
    parser.add_argument("--list-roles", action="store_true",
                        help="print the roles present in the unresolved set and exit; "
                             "costs no requests")
    parser.add_argument("--min-releases", type=int, default=1,
                        help="minimum credited releases together to keep a collaborator")
    parser.add_argument("--min-role-weight", type=float, default=MIN_ROLE_WEIGHT,
                        help="skip people whose TOP seed role weighs less than this. 0.2 "
                             "drops mastering (0.15) and keeps assistant engineers (0.20); "
                             "0.25 drops both. Costs no requests. 0 = keep everyone")
    parser.add_argument("--min-signal", type=float, default=MIN_SIGNAL,
                        help="once page 1 reveals how many releases they have, skip anyone "
                             "whose role_weight x selectivity falls below this. Catches the "
                             "prolific engineer that --min-role-weight cannot see")
    parser.add_argument("--explain-gate", action="store_true",
                        help="show what both gates would do and exit; costs no requests "
                             "(reuses totals already in --out when it exists)")
    parser.add_argument("--no-pool", action="store_true",
                        help="stop after the Discogs lookup; do not touch Qobuz")
    parser.add_argument("--pool-only", action="store_true",
                        help="skip Discogs and rebuild the pool from an existing --out file "
                             "(use after a run where Qobuz errored)")
    args = parser.parse_args()

    source = DATA / args.infile
    if not source.exists():
        raise SystemExit(f"{args.infile} not found - run ./qobuz_resolve.py first")
    watchlist = json.loads(source.read_text())
    seed = watchlist.get("seed") or {}
    unresolved = watchlist.get("unresolved") or []
    if not unresolved:
        print("nothing unresolved - done.")
        return 0

    # Already-resolved Qobuz ids and the seed are not discoveries.
    known_qobuz = {a["qobuz_id"] for a in watchlist.get("artists", []) if a.get("qobuz_id")}
    seed_key = normalise(seed.get("name") or "")

    if args.pool_only:
        saved_path = DATA / args.out
        if not saved_path.exists():
            raise SystemExit(f"--pool-only needs an existing {args.out}")
        saved = json.loads(saved_path.read_text())
        collaborators = {normalise(c["name"]): c
                         for c in saved.get("collaborator_candidates") or []}
        print(f"--pool-only: {len(collaborators)} collaborators from {args.out}",
              file=sys.stderr)
        return build_pool(args, seed, known_qobuz, collaborators)

    token = os.environ.get("DISCOGS_TOKEN") or None
    throttle = Throttle(60 if token else 25)
    print(f"discogs: {'token' if token else 'anonymous'} "
          f"({'60' if token else '25'} req/min)", file=sys.stderr)

    if args.list_roles:
        # Roles are stored most-frequent-first, so [0] is their top role.
        tops = collections.Counter(person_roles(u)[0] for u in unresolved if person_roles(u))
        print(f"top roles across {len(unresolved)} unresolved people "
              f"(pass any of these to --roles):\n")
        for role, count in tops.most_common():
            print(f"  {count:>3}  {role:<24} class={role_class(role):<12} "
                  f"weight={role_weight(role)}")
        by_class = collections.Counter(role_class(r) for u in unresolved
                                      for r in person_roles(u)[:1])
        print(f"\nby class: " + ", ".join(f"{k} {v}" for k, v in by_class.most_common()))
        return 0

    if args.explain_gate:
        # Replay both gates offline. Role weight needs nothing; selectivity needs
        # a Discogs total, which a previous run may already have written to --out.
        known: dict[str, int] = {}
        saved_path = DATA / args.out
        if saved_path.exists():
            saved = json.loads(saved_path.read_text())
            for row in (saved.get("recovered") or []):
                for name in row.get("names") or []:
                    if row.get("discogs_total_releases"):
                        known[normalise(name)] = row["discogs_total_releases"]
            for row in (saved.get("still_unresolved") or []):
                for name in row.get("names") or []:
                    if row.get("discogs_total"):
                        known[normalise(name)] = row["discogs_total"]
            print(f"totals for {len(known)} name(s) reused from {args.out}\n")
        else:
            print(f"no {args.out} yet - selectivity unknown, role weight only\n")

        print(f"{'person':<28}{'weight':>7}{'total':>7}{'sel':>6}{'signal':>8}  verdict")
        counts: collections.Counter = collections.Counter()
        for person in sorted(unresolved, key=lambda u: -u.get("albums", 0)):
            names = person.get("names") or ["?"]
            weight = person_role_weight(person)
            if weight < args.min_role_weight:
                verdict, counts["gated free"] = "GATED (no request)", counts["gated free"] + 1
                total = select = signal = None
            else:
                total = next((known[normalise(n)] for n in names
                              if normalise(n) in known), None)
                if total is None:
                    verdict, counts["unknown"] = "would look up", counts["unknown"] + 1
                    select = signal = None
                else:
                    select = selectivity(total)[0]
                    signal = weight * select
                    if signal < args.min_signal:
                        verdict = "GATED (after page 1)"
                        counts["gated after 1 page"] += 1
                    else:
                        verdict = "keep"
                        counts["keep"] += 1
            print(f"{names[0][:27]:<28}{weight:>7.2f}"
                  f"{(total if total is not None else '-'):>7}"
                  f"{(f'{select:.1f}' if select is not None else '-'):>6}"
                  f"{(f'{signal:.2f}' if signal is not None else '-'):>8}  {verdict}")
        print(f"\n--min-role-weight {args.min_role_weight}, "
              f"--min-signal {args.min_signal}: "
              + ", ".join(f"{k} {v}" for k, v in counts.most_common()))
        return 0

    sel_classes, sel_roles = parse_role_selection(args.roles)
    ordered = sorted(unresolved, key=lambda u: -u.get("albums", 0))
    if sel_classes or sel_roles:
        before = len(ordered)
        ordered = [u for u in ordered if wanted(u, sel_classes, sel_roles, args.roles_any)]
        print(f"--roles kept {len(ordered)} of {before} people "
              f"(classes={sorted(sel_classes) or '-'}, roles={sorted(sel_roles) or '-'}"
              f"{', any-role' if args.roles_any else ''})", file=sys.stderr)
    # Before --top, not after: the budget should buy N viable people, not N rows
    # of which a third are masterers.
    if args.min_role_weight > 0:
        before = len(ordered)
        ordered = [u for u in ordered if person_role_weight(u) >= args.min_role_weight]
        if len(ordered) != before:
            print(f"--min-role-weight {args.min_role_weight} kept {len(ordered)} of "
                  f"{before} people, at no request cost", file=sys.stderr)
    targets = ordered[:args.top]
    print(f"processing {len(targets)} of {len(unresolved)} unresolved people",
          file=sys.stderr)

    people, misses = [], []
    # collaborator name -> evidence about who linked us to them
    collaborators: dict[str, dict] = {}

    for index, person in enumerate(targets, 1):
        names = person.get("names") or []
        if not names:
            continue
        artist, how = find_discogs_artist(names, throttle, token)
        if artist is None:
            misses.append({"names": names, "albums": person.get("albums"), "reason": how})
            print(f"  [{index}/{len(targets)}] {names[0][:28]:<28} MISS ({how})", file=sys.stderr)
            continue

        did = int(artist["id"])
        weight = person_role_weight(person)
        credits, own, total, gated = discogs_credits(
            did, throttle, token, args.max_pages,
            gate=lambda t: weight * selectivity(t)[0] >= args.min_signal)
        select_score, select_label = selectivity(total)

        if gated:
            # A prolific engineer: the credits are real but say little about the
            # seed, and each one would cost a Qobuz resolve plus release fetches.
            misses.append({"names": names, "albums": person.get("albums"),
                           "reason": "low_signal", "discogs_id": did,
                           "discogs_total": total, "selectivity_band": select_label,
                           "signal": round(weight * select_score, 3)})
            print(f"  [{index}/{len(targets)}] {names[0][:28]:<28} "
                  f"discogs {did} | {total} releases, {select_label}, signal "
                  f"{weight * select_score:.2f} < {args.min_signal}, skipped",
                  file=sys.stderr)
            continue

        roles = collections.Counter(r["role"] for r in credits)

        if not credits:
            # Resolved, but every row was an Appearance or the pages were empty:
            # they contribute nothing and only cost calls.
            misses.append({"names": names, "albums": person.get("albums"),
                           "reason": "no_usable_credits", "discogs_id": did,
                           "discogs_total": total})
            print(f"  [{index}/{len(targets)}] {names[0][:28]:<28} "
                  f"discogs {did} | 0 usable credits, skipped", file=sys.stderr)
            continue

        # Who did they work with? Exclude the seed - that is where we came from.
        with_artists = collections.Counter()
        role_by_artist: dict[str, set] = collections.defaultdict(set)
        for row in credits:
            name = row["artist"]
            if not name or normalise(name) == seed_key:
                continue
            with_artists[name] += 1
            role_by_artist[name].add(row["role"])

        entry = {
            "names": names,
            "seed_albums": person.get("albums"),
            "qobuz": "unresolved",
            "discogs_id": did,
            "discogs_name": strip_discogs_suffix(artist.get("title") or ""),
            "match": how,
            "credited_releases": len(credits),
            "discogs_total_releases": total,
            "selectivity": {"score": select_score, "band": select_label},
            "own_releases": len(own),
            "roles": dict(roles.most_common()),
            "worked_with": [{"name": n, "releases": c, "roles": sorted(role_by_artist[n])}
                            for n, c in with_artists.most_common(40)],
        }
        people.append(entry)
        print(f"  [{index}/{len(targets)}] {names[0][:28]:<28} "
              f"discogs {did} | {len(credits)} credits | {len(with_artists)} artists",
              file=sys.stderr)

        for name, count in with_artists.items():
            if count < args.min_releases:
                continue
            slot = collaborators.setdefault(normalise(name), {
                "name": name, "releases": 0, "via": []})
            slot["releases"] += count
            best_role = max(role_by_artist[name], key=role_weight, default=None)
            slot["via"].append({"name": names[0], "discogs_id": did,
                                "roles": sorted(role_by_artist[name]),
                                "person_seed_albums": person.get("albums"),
                                "role_weight": role_weight(best_role),
                                "selectivity": select_score,
                                "selectivity_band": select_label})

    out_path = DATA / args.out
    out_path.write_text(json.dumps({
        "version": 1, "generated": dt.date.today().isoformat(),
        "seed": seed, "source": args.infile,
        "recovered": people, "still_unresolved": misses,
        "collaborator_candidates": sorted(collaborators.values(),
                                          key=lambda c: -c["releases"]),
    }, indent=2, ensure_ascii=False))

    print(f"\nrecovered {len(people)} of {len(targets)} via Discogs "
          f"({len(misses)} still unresolved)")
    low = [m for m in misses if m.get("reason") == "low_signal"]
    if low:
        print(f"  {len(low)} gated on signal after one page each: "
              + ", ".join(f"{m['names'][0]} ({m['signal']})" for m in low))
    print(f"{len(collaborators)} distinct artists they worked with")
    if people:
        print("\nrecovered people:")
        for entry in people[:10]:
            print(f"  {entry['seed_albums']:>2} seed alb  {entry['names'][0][:26]:<26} "
                  f"{entry['credited_releases']:>4} credits  "
                  f"{list(entry['roles'])[:3]}")
    print(f"wrote {out_path.name}")

    if args.no_pool:
        return 0

    return build_pool(args, seed, known_qobuz, collaborators)


def build_pool(args, seed, known_qobuz, collaborators) -> int:
    """Resolve collaborators in Qobuz and write the pool."""
    ranked = sorted(collaborators.values(), key=lambda c: -c["releases"])
    print(f"\nresolving {len(ranked)} collaborator artists in Qobuz...", file=sys.stderr)
    cookies = store_cookies(args.store)
    resolved, unmatched, errored = [], [], []
    for index, candidate in enumerate(ranked, 1):
        hit, outcome = qobuz_find_artist(candidate["name"], args.store)
        if hit is None and outcome != "not_found":
            # A failure, not an answer. Keep it visible so it can be retried.
            errored.append({"name": candidate["name"], "outcome": outcome})
        elif hit is None:
            unmatched.append(candidate["name"])
        elif int(hit["id"]) in known_qobuz or str(hit["id"]) == str(seed.get("qobuz_id")):
            pass                                   # already watched, or the seed
        else:
            resolved.append({**candidate, "qobuz_id": int(hit["id"]),
                             "qobuz_name": hit.get("name"),
                             "albums_count": hit.get("albumsCount") or 0})
        if index % 25 == 0:
            print(f"  ...{index}/{len(ranked)}", file=sys.stderr)
        time.sleep(QOBUZ_PAUSE)

    print(f"resolved {len(resolved)} in Qobuz, {len(unmatched)} not found, "
          f"{len(errored)} FAILED (retryable with --pool-only)", file=sys.stderr)

    pool, seen = [], set()
    for index, artist in enumerate(resolved, 1):
        # Best referral wins: role weight x selectivity x how embedded that
        # person is in the seed's catalogue.
        best = max(artist["via"], key=lambda v: v["role_weight"] * v["selectivity"])
        embedded = min((best.get("person_seed_albums") or 0) / 10.0, 1.0)
        signal = {"role_weight": best["role_weight"],
                  "selectivity": best["selectivity"],
                  "selectivity_band": best["selectivity_band"],
                  "person_seed_albums": best.get("person_seed_albums"),
                  "embedded": round(embedded, 3),
                  "score": round(best["role_weight"] * best["selectivity"] * embedded, 4),
                  "flags": (["single_token_name"]
                            if len((artist.get("qobuz_name") or "").split()) == 1 else [])}
        for release in qobuz_releases(artist["qobuz_id"], args.store, cookies):
            rid = str(release.get("id") or "")
            if not rid or rid in seen:
                continue
            seen.add(rid)
            pool.append({
                "album_id": rid,
                "title": release.get("title"),
                "artists": [x.get("name") for x in (release.get("artists") or []) if x.get("name")],
                "date": (release.get("release_date_original") or "")[:10],
                "tracks": release.get("tracks_count") or 0,
                "hires": bool(release.get("hires")),
                "streamable": bool(release.get("streamable")),
                # Same two fields resolve_qobuz.py already keeps. artist/get
                # returns them for every album, on the identical
                # extra=albums_with_last_release request this function already
                # makes -- they were simply never copied, which left 0 of 6,392
                # rows with a genre while pool.json had 1,470 of 1,470.
                "label": (release.get("label") or {}).get("name"),
                "genre": (release.get("genre") or {}).get("name"),
                # Provenance chains through the studio person Qobuz could not see.
                "via": {"qobuz_id": artist["qobuz_id"], "name": artist["qobuz_name"],
                        "path": "discogs",
                        "through": [v["name"] for v in artist["via"]],
                        "through_roles": sorted({r for v in artist["via"] for r in v["roles"]}),
                        "signal": signal},
            })
        if index % 25 == 0:
            print(f"  ...{index}/{len(resolved)}", file=sys.stderr)
        time.sleep(QOBUZ_PAUSE)

    pool.sort(key=lambda r: (-r["via"]["signal"]["score"], r["date"]))
    pool_path = DATA / args.pool_out
    pool_path.write_text(json.dumps({
        "version": 1, "generated": dt.date.today().isoformat(),
        "seed": seed, "store": args.store, "path": "discogs",
        "artists_fetched": len(resolved), "releases": len(pool),
        "qobuz_unmatched": unmatched, "qobuz_errors": errored, "pool": pool,
    }, indent=2, ensure_ascii=False))

    print(f"\npool: {len(pool)} releases from {len(resolved)} artists "
          f"reached only via Discogs")
    print(f"wrote {pool_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
