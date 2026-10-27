"""Ordering a list of candidates by a strategy that arrives from outside.

Plumbing, so no judgement lives here: this module knows how to turn a stored
row into FEATURES and how to sort by a score, and nothing about what a feature
is worth. The weights and the strategies are in `policy.py`, where D1 says
every contestable number goes, and they reach this module as an argument --
the same shape `core` already uses for every threshold.

The features are the ones todo.md step 3 named, plus one it did not:

    seeds          how many of your artists made a record with this person
    albums         how many DISTINCT records that is, across those seeds
    corroboration  the smaller of the two -- independent evidence
    on_seeds     records where they guested on YOUR artist's record
    on_theirs    records where your artist guested on THEIRS
    roles        what they did, already filtered to what may be named
    role_weight  what the strongest of those roles is worth
    recency      how recent the most recent shared record is, 0.0 to 1.0
    span         first to last, in years -- one session or a decade
    seed_plays   how much you play the seeds they connect to

`seed_plays` is the addition. A co-appearance with Jorge Drexler, whom the
export has 6,988 times, is not the same evidence as one with an artist played
327 times, and every strategy that ignores it is treating the two alike.

`corroboration` is the second. Two of your artists billed on ONE record are
one piece of evidence and two seeds, and the seed count cannot tell the
difference -- which put a remixer at the top of the list on a single single.
"""
from __future__ import annotations

import datetime as dt

# A shared record older than this carries no recency signal at all. Not a
# threshold on what to KEEP -- nothing is dropped here -- just the window the
# 0.0-to-1.0 recency feature is measured over, so a strategy that weights
# recency and one that ignores it are reading the same number.
RECENCY_YEARS = 10.0


def year_fraction(date: str | None, today: dt.date) -> float | None:
    """Years from `date` to `today`, or None when there is no date.

    None rather than 0.0: "no date on the record" and "released today" are
    different facts, and a strategy that treats the first as the second ranks
    an undated row as the most recent thing in the list.
    """
    if not date:
        return None
    try:
        when = dt.date.fromisoformat(date[:10])
    except ValueError:
        return None
    return (today - when).days / 365.25


def recency(last_seen: str | None, today: dt.date,
            window: float = RECENCY_YEARS) -> float:
    """1.0 for a record out today, 0.0 for one `window` years old or older.

    Clamped at both ends, and 0.0 for an undated row -- the absence is scored
    as "no recency evidence" rather than guessed at.
    """
    years = year_fraction(last_seen, today)
    if years is None:
        return 0.0
    return max(0.0, min(1.0, 1.0 - years / window))


def span_years(first_seen: str | None, last_seen: str | None,
               today: dt.date) -> float:
    """How long the collaboration ran, in years. One session is 0.0.

    A decade of records together is a different relationship from two tracks
    in one afternoon, and no stored column says which -- only these two dates.
    """
    first = year_fraction(first_seen, today)
    last = year_fraction(last_seen, today)
    if first is None or last is None:
        return 0.0
    return max(0.0, first - last)


def features(row, today: dt.date) -> dict:
    """One candidate's features, from the aggregated store row.

    `row` is anything with the keys stages/rank.py's query produces. Returned
    as a plain dict because that is what a strategy reads and what the log
    writes -- one shape, so the number a strategy saw is the number recorded.
    """
    return {
        "person_key": row["person_key"],
        "name": row["name"],
        "seeds": row["seeds"] or 0,
        "albums": row["albums"] or 0,
        # Bounded by both: a person cannot be corroborated by more artists
        # than chose them, nor by more records than exist.
        "corroboration": min(row["seeds"] or 0, row["albums"] or 0),
        "seed_names": row["seed_names"],
        "on_seeds": row["on_seeds"] or 0,
        "on_theirs": row["on_theirs"] or 0,
        "records": (row["on_seeds"] or 0) + (row["on_theirs"] or 0),
        "roles": row["roles"] or [],
        "role_weight": row["role_weight"] or 0.0,
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
        "recency": recency(row["last_seen"], today),
        "span": span_years(row["first_seen"], row["last_seen"], today),
        "seed_plays": row["seed_plays"] or 0,
        "plays": row["plays"] or 0,
        # The raw count for the log and the explanation, and the factor a
        # strategy multiplies by. Both, because "0.3" in a logged run is not
        # readable a month later and "859 releases" is.
        #
        # Injected by the caller, like `role_weight` beside it: the bands are a
        # judgement and `core/` does not import `policy`.
        "total_releases": row["total_releases"],
        "ubiquity": row["ubiquity"],
    }


def ranked(rows, strategy, limit: int | None = None) -> list[dict]:
    """Feature rows scored and ordered, highest first.

    `strategy` is a callable from a feature row to a float, OR to a tuple of
    them for a rule that is lexicographic rather than a weighted sum. Both
    shapes matter: "how many of your artists made a record with this person,
    FIRST" cannot be written as a weighted sum without a constant big enough
    to dominate every other term, and no such constant exists -- at
    SEED_BREADTH 10.0, eight records tied with one extra seed, which is the
    opposite of what the strategy claimed.

    Two fields come back on each row. `sort_key` is what the ordering used,
    and `score` is its leading number, which is what a report prints -- so the
    number shown is never recomputed, and a tuple strategy still has something
    to display.

    Ties break on the person key, so two runs over one store produce the same
    order. `top_role` already taught this project what an order-dependent field
    costs.
    """
    scored: list[tuple[tuple[float, ...], str, dict]] = []
    for row in rows:
        value = strategy(row)
        key: tuple[float, ...] = (
            tuple(float(part) for part in value) if isinstance(value, tuple)
            else (float(value),))
        scored.append((key, row["person_key"],
                       {**row, "score": key[0], "sort_key": key}))
    scored.sort(key=lambda item: (tuple(-part for part in item[0]), item[1]))
    out = [item[2] for item in scored]
    return out[:limit] if limit else out


def rank_delta(left: list[dict], right: list[dict]) -> list[dict]:
    """The same candidates under two strategies, by how far they moved.

    Comparing two orders is the whole reason for having several strategies, and
    eyeballing two columns does not scale past ten rows. Positive `moved`
    means `right` ranks it higher than `left` does.
    """
    places = {row["person_key"]: i for i, row in enumerate(right, 1)}
    out = []
    for position, row in enumerate(left, 1):
        other = places.get(row["person_key"])
        if other is None:
            continue
        out.append({"person_key": row["person_key"], "name": row["name"],
                    "left": position, "right": other,
                    "moved": position - other})
    out.sort(key=lambda r: (-abs(r["moved"]), r["person_key"]))
    return out
