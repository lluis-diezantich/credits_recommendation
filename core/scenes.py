"""Which seeds are one scene, from who they made records with.

`breadth` counts how many of your artists independently made a record with
somebody, and D22's thesis is that several of them choosing one person is
strong evidence. Measured 2026-10-24, the independence does not hold: the
seeds fall into a few scenes, and **2 of 380 candidates connect to more than
one of them**. So the count is almost always "how many artists WITHIN one
scene", and a scene where everyone guests on everyone hands out more of them
-- Bad Bunny has 116 co-artists, Bjork has 15, El Gran Combo has 9.

Two numbers on different scales in one ranked list is what makes that list
read badly whatever is weighted on top, so the lists are drawn per scene
instead. See docs/adr/D37.

Pure and offline, like everything in core/: the threshold arrives as an
argument because it is a judgement and lives in `policy`.
"""
from __future__ import annotations

from collections.abc import Iterable


def _union_find(seeds: list[str], linked) -> dict[str, str]:
    parent = {s: s for s in seeds}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]        # path halving
            x = parent[x]
        return x

    for a, b in linked:
        parent[find(a)] = find(b)
    return {s: find(s) for s in seeds}


def sessions(listens, gap: int, wanted: set[str]):
    """(sessions a key appears in, sessions a pair shares, total sessions).

    A session is listens with no gap longer than `gap`. `listens` is (when,
    key) ordered by time -- a sequence rather than a query, so this stays pure.

    Sessions and not days: a day holds a commute and an evening, and the point
    is what was played in one sitting. The same shape as the ListenBrainz
    algorithm `core/similar.py` pins, over one profile rather than everyone's.
    """
    seen: list[set[str]] = []
    current: set[str] = set()
    previous = None
    for when, key in listens:
        if previous is not None and when - previous > gap:
            seen.append(current)
            current = set()
        previous = when
        if key in wanted:
            current.add(key)
    seen.append(current)

    total: dict[str, int] = {}
    together: dict[tuple[str, str], int] = {}
    counted = 0
    for members in seen:
        # EVERY session counts, including ones holding none of `wanted`.
        # Otherwise the denominator depends on which keys were asked about: in
        # this project, adding 11 candidates to the question raised the count
        # from 3,177 to 14,109, multiplied every lift by 4.4 and silently
        # moved which SEEDS were one scene. The grouping must not depend on
        # who is being tested against it.
        counted += 1
        if not members:
            continue
        ordered = sorted(members)
        for key in ordered:
            total[key] = total.get(key, 0) + 1
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                together[(a, b)] = together.get((a, b), 0) + 1
    return total, together, counted


def lift(shared: int, total_a: int, total_b: int, n_sessions: int) -> float:
    """How much more often two keys share a session than chance predicts.

    1.0 is exactly chance. Raw co-occurrence cannot be used instead: Bad Bunny
    is in 551 of 3,177 seed sessions, so he shared sessions with nearly every
    seed and a raw count called him close to all of them. Dividing by what the
    two play counts predict is what removes that.
    """
    if not shared or not total_a or not total_b or not n_sessions:
        return 0.0
    expected = total_a * total_b / n_sessions
    return shared / expected if expected else 0.0


def linked_pairs(names: list[str], reason_for) -> list[tuple[str, str, str]]:
    """[(a, b, why)] for every pair the caller's rule links, a < b.

    The rule is a callable because it is a judgement over three signals and
    lives in `policy`; two stages ask the same question of it and must not
    each have their own loop. `reason_for(a, b)` returns words or None.
    """
    found = []
    ordered = sorted(names)
    for index, a in enumerate(ordered):
        for b in ordered[index + 1:]:
            why = reason_for(a, b)
            if why:
                found.append((a, b, why))
    return found


def joins(name: str, others: Iterable[str], reason_for) -> list[tuple[str, str]]:
    """[(other, why)] for everyone an UNWALKED artist would link to.

    The same rule asked of a candidate rather than of a seed, which is what
    makes a scene predictable before 50 requests are spent: the co-listening
    and genre signals need no credits, so they can be read off the profile.
    Only the credit signal cannot, and for a candidate it is simply absent.
    """
    out = []
    for other in sorted(others):
        if other == name:
            continue
        why = reason_for(name, other)
        if why:
            out.append((other, why))
    return out


def group_links(sizes: dict[str, int],
                links: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Key -> scene label, from an explicit set of links.

    The linking rule is the caller's: it is a judgement over three signals and
    lives in `policy`. This only does the grouping, and `sizes` decides the
    label.
    """
    keys = sorted(sizes)
    root_of = _union_find(keys, links)
    members: dict[str, list[str]] = {}
    for key, root in root_of.items():
        members.setdefault(root, []).append(key)

    labels: dict[str, str] = {}
    for group_members in members.values():
        best = max(sorted(group_members), key=lambda k: sizes.get(k, 0))
        for key in group_members:
            labels[key] = best
    return labels


def group(by_seed: dict[str, set[str]], floor: int) -> dict[str, str]:
    """Seed name -> scene label, linking on shared co-artists alone.

    Named after its best-connected member -- "Bad Bunny", "Celia Cruz" -- so a
    heading says something a person recognises. `scene 1` would be stable and
    meaningless, and the scenes are DERIVED, so a number would also change
    under the reader whenever a seed is added.

    TRANSITIVE, which is the trap. Two seeds are linked when they share at
    least `floor` co-artists, and linkage chains: at a floor of 2, Bjork joined
    Bad Bunny's scene through ROSALIA, on the strength of one remix. The floor
    is what keeps a chain from swallowing everything, so it belongs to a
    measurement rather than to taste -- policy.SCENE_SHARED_FLOOR has it.
    """
    seeds = sorted(by_seed)
    linked = [(a, b)
              for i, a in enumerate(seeds) for b in seeds[i + 1:]
              if len(by_seed[a] & by_seed[b]) >= floor]
    return group_links({s: len(by_seed[s]) for s in seeds}, linked)


def of_candidate(seed_names: Iterable[str], labels: dict[str, str]) -> list[str]:
    """Every scene one candidate reaches, best-connected first.

    A list rather than one value because a candidate CAN span scenes -- Papo
    Lucca reaches Sonora Ponceña and Celia Cruz -- and those two rows are the
    only ones D22's thesis is actually about. Collapsing them into a single
    scene would hide the project's own evidence.
    """
    seen: dict[str, None] = {}
    for name in seed_names:
        label = labels.get(name)
        if label is not None:
            seen[label] = None
    return list(seen)


def split(rows: list[dict], labels: dict[str, str],
          seeds_of) -> dict[str, list[dict]]:
    """Candidates grouped by scene, each row appearing in every scene it reaches.

    Duplicated on purpose: a cross-scene candidate is a real recommendation in
    both of its scenes, and dropping it from one would make the per-scene lists
    disagree with the global one for no reason a reader could see.
    """
    out: dict[str, list[dict]] = {}
    for row in rows:
        for scene in of_candidate(seeds_of(row), labels):
            out.setdefault(scene, []).append(row)
    return out
