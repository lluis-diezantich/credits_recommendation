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
import sys
import time

from core.discogs import Throttle, discogs_credits, find_discogs_artist
from core.names import normalise, strip_discogs_suffix
from core.paths import DATA
from core.qobuz import PAUSE as QOBUZ_PAUSE
from core.qobuz import STORE, artist_releases, find_artist, store_cookies
from policy import (
    CLASS_NAMES,
    MIN_ROLE_WEIGHT,
    MIN_SIGNAL,
    match_confidence,
    person_role_weight,
    person_roles,
    role_class,
    role_key,
    role_weight,
    selectivity,
)


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


def signal_of(weight: float, total: int) -> tuple[float, float, str]:
    """(signal, selectivity score, selectivity band) for one person.

    The product that both gates are expressed in: what their credit is worth
    times how much one credit from them tells you.
    """
    score, band = selectivity(total)
    return weight * score, score, band


def gate_verdict(weight: float, total: int | None, min_role_weight: float,
                 min_signal: float) -> tuple[str, float | None, float | None]:
    """(verdict, selectivity, signal) for the two gates, in ONE copy.

    This existed twice. The live run applied the role-weight filter as a list
    comprehension and the signal filter as a lambda handed to
    discogs_credits(); --explain-gate reimplemented both to predict what the
    run would do. Two copies of a prediction and the thing it predicts is the
    one arrangement where drift is invisible -- the explain output would simply
    have been wrong, and confidently.

    Four verdicts, because when a person is dropped decides what it cost:

        gated_free          their top role is too weak to be worth a request.
                            Costs nothing, and is why --min-role-weight is
                            applied before --top: the budget should buy N
                            viable people, not N rows of which a third are
                            masterers.
        unknown             worth a request, and the total is not known yet.
                            Only --explain-gate sees this, replaying offline.
        gated_after_page_1  the Discogs total arrived with page 1 and the
                            signal does not clear the floor. Costs one request
                            instead of max_pages plus the whole Qobuz fan-out.
        keep                pay for the rest.
    """
    if weight < min_role_weight:
        return "gated_free", None, None
    if total is None:
        return "unknown", None, None
    sig, score, _ = signal_of(weight, total)
    if sig < min_signal:
        return "gated_after_page_1", score, sig
    return "keep", score, sig


def select_targets(unresolved: list[dict], classes: set[str], roles: set[str],
                   roles_any: bool, min_role_weight: float, top: int,
                   ) -> tuple[list[dict], int, int]:
    """(targets, after --roles, after --min-role-weight) -- who to spend on.

    Most seed albums first, because Discogs' rate limit means the run may not
    reach the end of the list and the people with most seed albums are the ones
    worth reaching. Both counts are returned so the caller can report what each
    filter removed without recomputing either.
    """
    ordered = sorted(unresolved, key=lambda u: -(u.get("albums") or 0))
    if classes or roles:
        ordered = [u for u in ordered if wanted(u, classes, roles, roles_any)]
    after_roles = len(ordered)
    if min_role_weight > 0:
        ordered = [u for u in ordered
                   if gate_verdict(person_role_weight(u), None, min_role_weight,
                                   0.0)[0] != "gated_free"]
    return ordered[:top], after_roles, len(ordered)


def known_totals(saved: dict) -> dict[str, int]:
    """Discogs totals a previous run already wrote, by normalised name.

    --explain-gate needs a total to replay the second gate, and a total costs a
    request. Reusing what is on disk is what makes the explain free.
    """
    known: dict[str, int] = {}
    for key, field in (("recovered", "discogs_total_releases"),
                       ("still_unresolved", "discogs_total")):
        for row in saved.get(key) or []:
            if row.get(field):
                for name in row.get("names") or []:
                    known[normalise(name)] = row[field]
    return known


def role_census(unresolved: list[dict]) -> tuple[collections.Counter,
                                                 collections.Counter]:
    """(top roles, their classes) across the unresolved, both most-common first.

    Roles are stored most-frequent-first, so [0] is what a person mainly is --
    which is also what the gate reads, so this census describes the same thing
    --min-role-weight will act on.
    """
    tops = collections.Counter(person_roles(u)[0] for u in unresolved
                               if person_roles(u))
    by_class = collections.Counter(role_class(r) for u in unresolved
                                   for r in person_roles(u)[:1])
    return tops, by_class


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
        tops, by_class = role_census(unresolved)
        print(f"top roles across {len(unresolved)} unresolved people "
              f"(pass any of these to --roles):\n")
        for role, count in tops.most_common():
            print(f"  {count:>3}  {role:<24} class={role_class(role):<12} "
                  f"weight={role_weight(role)}")
        print("\nby class: " + ", ".join(f"{k} {v}" for k, v in by_class.most_common()))
        return 0

    if args.explain_gate:
        # Replay both gates offline. Role weight needs nothing; selectivity needs
        # a Discogs total, which a previous run may already have written to --out.
        saved_path = DATA / args.out
        if saved_path.exists():
            known = known_totals(json.loads(saved_path.read_text()))
            print(f"totals for {len(known)} name(s) reused from {args.out}\n")
        else:
            known = {}
            print(f"no {args.out} yet - selectivity unknown, role weight only\n")

        print(f"{'person':<28}{'weight':>7}{'total':>7}{'sel':>6}{'signal':>8}  verdict")
        counts: collections.Counter = collections.Counter()
        labels = {"gated_free": ("GATED (no request)", "gated free"),
                  "unknown": ("would look up", "unknown"),
                  "gated_after_page_1": ("GATED (after page 1)", "gated after 1 page"),
                  "keep": ("keep", "keep")}
        for person in sorted(unresolved, key=lambda u: -u.get("albums", 0)):
            names = person.get("names") or ["?"]
            weight = person_role_weight(person)
            total = next((known[normalise(n)] for n in names
                          if normalise(n) in known), None)
            outcome, select, signal = gate_verdict(weight, total, args.min_role_weight,
                                                   args.min_signal)
            if outcome == "gated_free":
                total = None               # never looked up, so do not print one
            verdict, bucket = labels[outcome]
            counts[bucket] += 1
            print(f"{names[0][:27]:<28}{weight:>7.2f}"
                  f"{(total if total is not None else '-'):>7}"
                  f"{(f'{select:.1f}' if select is not None else '-'):>6}"
                  f"{(f'{signal:.2f}' if signal is not None else '-'):>8}  {verdict}")
        print(f"\n--min-role-weight {args.min_role_weight}, "
              f"--min-signal {args.min_signal}: "
              + ", ".join(f"{k} {v}" for k, v in counts.most_common()))
        return 0

    sel_classes, sel_roles = parse_role_selection(args.roles)
    targets, after_roles, after_weight = select_targets(
        unresolved, sel_classes, sel_roles, args.roles_any,
        args.min_role_weight, args.top)
    if sel_classes or sel_roles:
        print(f"--roles kept {after_roles} of {len(unresolved)} people "
              f"(classes={sorted(sel_classes) or '-'}, roles={sorted(sel_roles) or '-'}"
              f"{', any-role' if args.roles_any else ''})", file=sys.stderr)
    if after_weight != after_roles:
        print(f"--min-role-weight {args.min_role_weight} kept {after_weight} of "
              f"{after_roles} people, at no request cost", file=sys.stderr)
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
            print(f"  [{index}/{len(targets)}] {names[0][:28]:<28} MISS ({how})",
                  file=sys.stderr)
            continue

        did = int(artist["id"])
        weight = person_role_weight(person)
        credits, own, total, gated = discogs_credits(
            did, throttle, token, args.max_pages,
            gate=lambda t, w=weight: gate_verdict(
                w, t, args.min_role_weight, args.min_signal)[0] == "keep")
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
            # own_albums where the discovery file has it: a guest spot is not
            # one of the seed's records, so it must not count as embedding.
            own = person.get("own_albums")
            slot["via"].append({"name": names[0], "discogs_id": did,
                                "roles": sorted(role_by_artist[name]),
                                "person_seed_albums": (person.get("albums")
                                                       if own is None else own),
                                "albums_labelled": own is not None,
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
    ambiguous = 0
    for index, candidate in enumerate(ranked, 1):
        # Both spellings, because these names came out of Discogs credit rows
        # and nothing has stripped the decorations off them yet: "Valeria
        # Castro*" and "Mauro (5)" fail an exact match verbatim.
        hit, outcome = find_artist(
            [candidate["name"], strip_discogs_suffix(candidate["name"])], args.store)
        if outcome == "error":
            # A failure, not an answer. Keep it visible so it can be retried.
            errored.append({"name": candidate["name"], "outcome": outcome})
        elif hit is None:
            unmatched.append(candidate["name"])
        elif int(hit["id"]) in known_qobuz or str(hit["id"]) == str(seed.get("qobuz_id")):
            pass                                   # already watched, or the seed
        else:
            ambiguous += outcome == "ambiguous"
            resolved.append({**candidate, "qobuz_id": int(hit["id"]),
                             "qobuz_name": hit.get("name"),
                             "qobuz_match": outcome,
                             "albums_count": hit.get("albumsCount") or 0})
        if index % 25 == 0:
            print(f"  ...{index}/{len(ranked)}", file=sys.stderr)
        time.sleep(QOBUZ_PAUSE)

    print(f"resolved {len(resolved)} in Qobuz ({ambiguous} ambiguous), "
          f"{len(unmatched)} not found, "
          f"{len(errored)} FAILED (retryable with --pool-only)", file=sys.stderr)

    pool, seen = [], set()
    for index, artist in enumerate(resolved, 1):
        # Best referral wins: role weight x selectivity x how embedded that
        # person is in the seed's catalogue.
        best = max(artist["via"], key=lambda v: v["role_weight"] * v["selectivity"])
        embedded = min((best.get("person_seed_albums") or 0) / 10.0, 1.0)
        flags = []
        if not best.get("albums_labelled"):
            flags.append("unlabelled_albums")
        if len((artist.get("qobuz_name") or "").split()) == 1:
            flags.append("single_token_name")
        # Folded into the stored score rather than left to each reader, which
        # is what policy.MATCH_PENALTY calls the better fix: this is the path
        # that produced "Morgan" at 1.00, the maximum, on a name match nobody
        # corroborated.
        confidence = match_confidence(flags)
        signal = {"role_weight": best["role_weight"],
                  "selectivity": best["selectivity"],
                  "selectivity_band": best["selectivity_band"],
                  "person_seed_albums": best.get("person_seed_albums"),
                  "embedded": round(embedded, 3),
                  "match_confidence": confidence,
                  "score": round(best["role_weight"] * best["selectivity"]
                                 * embedded * confidence, 4),
                  "flags": flags}
        _, releases, _ = artist_releases(artist["qobuz_id"], args.store, cookies)
        for release in releases:
            rid = str(release.get("id") or "")
            if not rid or rid in seen:
                continue
            seen.add(rid)
            pool.append({
                "album_id": rid,
                "title": release.get("title"),
                "artists": [x.get("name") for x in (release.get("artists") or [])
                            if x.get("name")],
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
                        # The two catalogue sizes, for the corroboration this
                        # path has never had: how many albums the Qobuz artist
                        # we matched holds, against how many releases the
                        # Discogs credit rows put this person on.
                        "albums_count": artist.get("albums_count"),
                        "discogs_releases": artist.get("releases"),
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
