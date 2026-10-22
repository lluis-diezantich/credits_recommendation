"""Turning stored credit facts into one readable sentence.

Pure and offline, like the rest of core/: it formats what it is handed and
looks nothing up. Which roles are worth naming is a judgement and stays in
policy.py -- this module is given the roles already chosen.

Every clause has to be a fact somebody can check in the store. No "87%
similar", no "fans also like": the point of a credits-based recommendation is
that the reason is verifiable, so a sentence that cannot be traced back to a
row does not belong here.

    Juan Falu is billed with Silvia Perez Cruz on 4 of Silvia Perez Cruz's
    records, credited on 13 tracks (guitar, producer) - e.g. Chacarera de las
    Piedras (2024). Never played.
"""
from __future__ import annotations

# How a credit reads in a sentence. Anything not here is used as-is and
# lowercased, which is why the fallback phrasing is "credited on N tracks
# (<role>)" rather than a verb: "played mastering engineer" is the sort of
# sentence a lexicon with a guessy fallback produces.
ROLE_WORDS: dict[str, str] = {
    "producer": "producer", "co-producer": "co-producer",
    "co- producer": "co-producer", "executive producer": "executive producer",
    "composer": "writer", "composerlyricist": "writer", "lyricist": "lyricist",
    "vocals": "vocals", "vocal": "vocals", "background vocal": "backing vocals",
    "backing vocals": "backing vocals", "voices": "vocals",
    "arranger": "arranger", "conductor": "conductor",
}


def role_phrase(roles) -> str:
    """"guitar, producer" -- the roles, in the order given, de-duplicated."""
    seen: dict[str, None] = {}
    for role in roles or []:
        seen.setdefault(ROLE_WORDS.get(role.lower(), role.lower()), None)
    return ", ".join(seen)


def year(date: str | None) -> str:
    return (date or "")[:4]


def co_artist_sentence(name: str, seed: str, own: int, guest: int, *,
                       tracks: int = 0, roles=None, example=None,
                       plays: int | None = None) -> str:
    """One sentence for "why might I like this artist".

    `own` is records of the SEED's that this artist is billed on, `guest` is
    records of their own that the seed appears on. Both are records the two
    made together, which is the whole claim -- see docs/adr/D14.

    No pronouns for either of them: the store knows names, not genders, so the
    seed's name is repeated where a pronoun would go.
    """
    if own and guest:
        clause = (f"{name} and {seed} share {own + guest} records: "
                  f"{own} of {seed}'s and {guest} of {name}'s")
    elif own == 1:
        clause = f"{name} is billed on one of {seed}'s records"
    elif own:
        clause = f"{name} is billed on {own} of {seed}'s records"
    elif guest == 1:
        clause = f"{seed} appears on {name}'s own record"
    elif guest:
        clause = f"{seed} appears on {guest} of {name}'s own records"
    else:
        clause = f"{name} is credited alongside {seed}"

    phrase = role_phrase(roles)
    if phrase and tracks:
        t = "track" if tracks == 1 else "tracks"
        clause += f", credited on {tracks} {t} ({phrase})"

    if example:
        title, date = example
        when = f" ({year(date)})" if year(date) else ""
        # "e.g." only when there is more than one to pick from. With a single
        # record it is not an example, it is the whole claim.
        lead = "e.g. " if own + guest > 1 else ""
        clause += f" - {lead}{title}{when}"

    if plays is None:
        return clause + "."
    heard = "Never played." if not plays else f"Played {plays} times."
    return f"{clause}. {heard}"


def seed_list(names) -> str:
    """"Bjork", "Bjork and ROSALIA", "Bjork, ROSALIA and 2 others".

    Two is the shape worth naming in full: by three the clause is longer than
    the fact it carries, and the names are in the row beside the sentence
    anyway.
    """
    names = [n for n in names or [] if n]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    others = len(names) - 2
    return f"{names[0]}, {names[1]} and {others} other{'' if others == 1 else 's'}"


def cross_seed_sentence(name: str, seeds, own: int, guest: int, *,
                        tracks: int = 0, roles=None, example=None,
                        plays: int | None = None) -> str:
    """The same sentence for a candidate reached through SEVERAL of your artists.

    todo.md step 4 asked for this and it turned out to be load-bearing rather
    than cosmetic: stages/rank.py ranks across seeds, so its top rows are the
    multi-seed ones by construction, and passing "2 artists you play" to
    co_artist_sentence as if it were a name produced "billed on 2 of 2 artists
    you play's records".

    One seed delegates, so there is one sentence shape per claim and not two
    that drift. Several seeds get the count AND the names, because "3 artists
    you play" is the number that matters and "Drexler, ROSALIA and 1 other" is
    what makes it checkable.
    """
    names = [n for n in seeds or [] if n]
    if len(names) <= 1:
        return co_artist_sentence(name, names[0] if names else "", own, guest,
                                  tracks=tracks, roles=roles, example=example,
                                  plays=plays)

    records = own + guest
    thing = "record" if records == 1 else "records"
    clause = (f"{name} has made {records} {thing} with {len(names)} artists "
              f"you play - {seed_list(names)}")
    if guest and not own:
        clause += ", on their own records"
    elif guest:
        clause += f", {guest} of them theirs"

    phrase = role_phrase(roles)
    if phrase and tracks:
        t = "track" if tracks == 1 else "tracks"
        clause += f", credited on {tracks} {t} ({phrase})"

    if example:
        title, date = example
        when = f" ({year(date)})" if year(date) else ""
        lead = "e.g. " if records > 1 else ""
        clause += f" - {lead}{title}{when}"

    if plays is None:
        return clause + "."
    heard = "Never played." if not plays else f"Played {plays} times."
    return f"{clause}. {heard}"
