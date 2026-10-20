"""Scoring policy: what a credit is worth, and what it takes to be worth looking up.

This file is the whole reason the project is laid out this way. It is NOT in
core/ -- it lives at the root, one copy, visible, because these numbers are
judgement calls that deserve to be argued with rather than buried in a client.

It merges the two tables that used to be copied into qobuz_resolve.py and
discogs_resolve.py. They never disagreed on a shared key, but each was missing
keys the other had, and a missing key silently returns INSTRUMENT_WEIGHT (0.8):

    mastered by   0.15 in discogs_resolve, 0.8 in qobuz_resolve
    written-by    0.30 in discogs_resolve, 0.8 in qobuz_resolve
    performer     0.40 in qobuz_resolve,   0.8 in discogs_resolve

Nine spellings diverged that way, always upward, always for the credits that
deserve the least weight. The union below is the fix: an explicit value always
beats an absence.
"""
from __future__ import annotations

# How much a credit tells you, by role. Two ideas are baked in:
#   - a producer or a player is CHOSEN for how they sound; a mastering engineer
#     is an industrial service. One facility masters thousands of records across
#     every genre, so "shares a mastering engineer" means "used the same shop".
#   - composer/lyricist and main/featured credits are a different relationship
#     entirely (a song the seed covered, or a billing line), not a collaboration.
# Anything unlisted is an instrument or vocal credit, which scores INSTRUMENT.
#
# Both Qobuz spellings ("MixingEngineer") and Discogs' ("Mixed by") appear, since
# role_key() folds punctuation and case but cannot invent a synonym.
ROLE_WEIGHTS: dict[str, float] = {
    # production
    "producer": 1.0, "co-producer": 0.9, "co- producer": 0.9, "production": 0.9,
    "executive producer": 0.4,            # usually money, not sound
    # arrangement
    "arranger": 0.8, "instrument arranger": 0.8, "vocal arranger": 0.8,
    "conductor": 0.7,
    # engineering, strongest to weakest
    "mixer": 0.5, "mixing engineer": 0.5, "mixed by": 0.5,  # shapes the sound
    "remix": 0.4,
    "engineer": 0.45, "recording engineer": 0.45, "recorded by": 0.45,
    "assistant engineer": 0.2, "assistantengineer": 0.2,
    "mastering engineer": 0.15, "masterer": 0.15, "mastered by": 0.15,
    #                                             ^ weakest signal there is
    # writing - a different relationship, not a collaboration
    "composer": 0.3, "lyricist": 0.3, "composerlyricist": 0.3,
    "written-by": 0.3, "adapter": 0.3,
    # billing
    "mainartist": 0.25, "featuredartist": 0.25, "associatedperformer": 0.25,
    "main": 0.25,
    "performer": 0.4, "performance": 0.4,
}
INSTRUMENT_WEIGHT = 0.8

# Roles that are studio/admin rather than musical, added after --list-roles
# showed StudioPersonnel and AssociatedPerformer scoring as instruments.
EXTRA_WEIGHTS: dict[str, float] = {
    "studiopersonnel": 0.2, "associatedperformer": 0.25,
    "orchestra": 0.7, "choir": 0.6,
}

# Role CLASSES, so --roles can take a group instead of listing every instrument.
# Keys are role_key() normalised, because Qobuz spells the same role several
# ways: "AssistantEngineer", "Assistant Engineer", "Co- Producer".
ROLE_CLASS: dict[str, str] = {
    **{r: "production" for r in (
        "producer", "coproducer", "production", "executiveproducer")},
    **{r: "engineering" for r in (
        "engineer", "recordingengineer", "mixedby", "mixer", "mixingengineer",
        "assistantengineer", "asstrecordingengineer", "masteredby",
        "masteringengineer", "masterer", "studiopersonnel")},
    **{r: "writing" for r in (
        "composer", "lyricist", "composerlyricist", "writtenby", "adapter",
        "author", "writer", "arranger", "instrumentarranger", "vocalarranger")},
    **{r: "billing" for r in (
        "mainartist", "main", "featuredartist", "associatedperformer",
        "performer", "performance")},
}
CLASS_NAMES = {"production", "engineering", "writing", "billing", "performance"}

# Referral classes that are not a working relationship. A person credited ONLY
# under these is dropped by default (--keep-weak overrides): on the Drexler pool
# they were 45% of the rows.
WEAK_CLASSES = {"writing", "billing"}

# Gate defaults, calibrated on the 54 unresolved people in the Drexler run:
#   0.2 sits between mastering (0.15) and assistant engineer (0.20), so it drops
#   the two masterers for free and keeps Manuel Pajaro exactly on the boundary.
MIN_ROLE_WEIGHT = 0.2
MIN_SIGNAL = 0.2


def role_key(role: str) -> str:
    """Fold spelling variants: 'Co- Producer' and 'MixingEngineer' both match."""
    return "".join(ch for ch in role.lower() if ch.isalnum())


_WEIGHTS_BY_KEY: dict[str, float] = {role_key(k): v for k, v in ROLE_WEIGHTS.items()}
_WEIGHTS_BY_KEY.update(EXTRA_WEIGHTS)


def role_weight(role: str | None) -> float:
    if not role:
        return INSTRUMENT_WEIGHT
    return _WEIGHTS_BY_KEY.get(role_key(role), INSTRUMENT_WEIGHT)


def role_class(role: str) -> str:
    """Anything unrecognised is an instrument or vocal credit."""
    return ROLE_CLASS.get(role_key(role), "performance")


def person_roles(person: dict) -> list[str]:
    """The person's roles, most frequent first (resolve_qobuz stores them so)."""
    return list(person.get("roles") or [])


def person_role_weight(person: dict) -> float:
    """What they mainly are, weighted -- their TOP role, as wanted() defaults to.

    Someone who mastered ten of the seed's albums is a mastering engineer
    whatever else they once played. Reads only what resolve_qobuz already
    wrote, so this gates before spending a single request.
    """
    roles = person_roles(person)
    return role_weight(roles[0]) if roles else 0.0


def selectivity(total_releases: int) -> tuple[float, str]:
    """How much one credit from this person is worth.

    The more records someone touches, the less "they touched this one" tells
    you. Fred Kevorkian has mastered 1,070 releases across every genre; Carles
    Campi Campon has 45. Bands rather than a formula, so a score is explainable.
    """
    if total_releases <= 0:
        return 0.5, "unknown"
    if total_releases <= 60:
        return 1.0, "selective"
    if total_releases <= 200:
        return 0.6, "moderate"
    if total_releases <= 600:
        return 0.3, "prolific"
    return 0.1, "service"          # an industrial service, not a collaborator


# ---------------------------------------------------------------------------
# Discovery-stage vocabulary. DELIBERATELY COARSER than ROLE_CLASS above, and
# kept separate rather than merged: qobuz_discover folded every engineering role
# into "production", which is why discovery_*.json and watchlist.json carry the
# classes performance/production/writing/billing and no "engineering" at all.
# Unifying the two would change that written data, so it is a decision to make
# on purpose, not a side effect of tidying. WEAK_CLASSES is unaffected either
# way (engineers are weak under neither vocabulary).
# ---------------------------------------------------------------------------

MUSICAL_ROLES = {
    "producer", "co-producer", "co- producer", "executive producer", "production",
    "mixer", "mixing engineer", "recording engineer", "engineer", "assistant engineer",
    "assistantengineer", "mastering engineer", "masterer",
    "guitar", "electric guitar", "acoustic guitar", "classical guitar", "guitarron guitar",
    "bass", "bass guitar", "double bass", "contrabass", "drums", "percussion",
    "piano", "electric piano", "keyboards", "organ", "synthesizer", "programmer",
    "violin", "viola", "cello", "strings", "trumpet", "trombone", "saxophone",
    "clarinet", "flute", "harmonica", "accordion", "bandoneon", "charango", "cuatro",
    "vocals", "vocal", "background vocal", "backing vocals", "choir", "chorus",
    "arranger", "instrument arranger", "vocal arranger", "orchestra", "conductor",
    "composer", "lyricist", "songwriter", "adapter", "performer", "mainartist",
}

DISCOVERY_ROLE_CLASSES: dict[str, str] = {
    **{r: "production" for r in (
        "producer", "co-producer", "co- producer", "executive producer", "production",
        "mixer", "mixing engineer", "recording engineer", "engineer",
        "assistant engineer", "assistantengineer", "asst. recording engineer",
        "mastering engineer", "masterer", "studiopersonnel")},
    **{r: "writing" for r in (
        "composer", "lyricist", "composerlyricist", "songwriter", "adapter",
        "author", "writer", "arranger", "instrument arranger", "vocal arranger")},
    **{r: "billing" for r in (
        "mainartist", "featuredartist", "associatedperformer", "performer", "performance")},
}


def classify_roles(roles) -> list[str]:
    """Which kinds of relationship this person's credits represent.

    Uses the coarse DISCOVERY_ROLE_CLASSES, matching what already sits in
    discovery_*.json. Lowercase lookup only -- no role_key() folding -- again
    to preserve the existing output exactly.
    """
    return sorted({DISCOVERY_ROLE_CLASSES.get(role.lower(), "performance") for role in roles})


# ---------------------------------------------------------------------------
# WRITING-LOOKUP VOCABULARY (stages/writing.py)
#
# Separate from ROLE_CLASS above, and deliberately finer. ROLE_CLASS answers
# "is this a collaboration?" and folds every writing role into one class. That
# is the wrong granularity here: on Shakira's "Waka Waka" Drexler is Lyricist
# while Dooh Belly Eugene Victor, Ze Bell Jean Paul and Shakira hold Composer
# -- he wrote the Spanish words for someone else's song. ROLE_CLASS calls that
# identical to having composed it.
# ---------------------------------------------------------------------------

# Roles that mean "this person composed the music or is a credited author".
COMPOSER_ROLES = {"composer", "composerlyricist", "writer", "writtenby", "author"}

# Roles that put words to music, which may be original co-writing OR a
# translation. Alone they do not establish authorship -- see writing_tier().
LYRIC_ROLES = {"lyricist", "composerlyricist"}

# Explicitly derivative: the credit itself says the song came from elsewhere.
ADAPTATION_ROLES = {"adapter", "translator", "adaptor"}

WRITING_ROLES = COMPOSER_ROLES | LYRIC_ROLES | ADAPTATION_ROLES

# Roles proving they are on the recording, so it is their track or a
# collaboration rather than a song handed to another artist.
PERFORMANCE_ROLES = {
    "mainartist", "featuredartist", "associatedperformer", "performer",
    "performance", "vocal", "vocals", "backgroundvocal", "backingvocals",
}


def writing_tier(mine: set[str], others_compose: bool) -> str:
    """How strong is this person's claim to have written the song?

    Three outcomes, not two, because roles alone cannot separate a translation
    from a genuine words-and-music partnership:

      authored     they hold a composer/author role. Unambiguous.
      lyrics_only  they hold ONLY a lyric role and somebody else composed.
                   Could be a Spanish adaptation ("Waka Waka") or a real
                   co-write where they wrote the words ("Como Las Mareas").
                   Indistinguishable from credits alone -- so it is FLAGGED,
                   never silently dropped.
      adaptation   an explicit Adapter/Translator credit. Derivative by
                   its own admission.
    """
    if mine & ADAPTATION_ROLES and not (mine & COMPOSER_ROLES):
        return "adaptation"
    if mine & COMPOSER_ROLES:
        return "authored"
    if mine & LYRIC_ROLES:
        return "lyrics_only" if others_compose else "authored"
    return "none"


# Translations are a DIFFERENT TITLE for the same song, which no amount of
# string folding can detect: "La Edad Del Cielo" and "A Idade do Céu" share no
# words. Only a curated table gets these, so the table is here where it can be
# argued with, and it is expected to grow per artist. Keys and values are
# title_key() output (accent-stripped, punctuation-free, lowercase).
TITLE_ALIASES: dict[str, str] = {
    # Jorge Drexler, from the 2026-09 run
    "a idade do ceu": "la edad del cielo",
    "idade do ceu": "la edad del cielo",
    "eu nao": "no voy a ser yo",
    "me faz bem": "me haces bien",
    "12 seconds": "12 segundos de oscuridad",
    "row on": "al otro lado del rio",
    "al outro lado del rio": "al otro lado del rio",
    "la mora judia": "milonga del moro judio",
    "que quieres de mi": "que quer de mim",
}

# Above this, two folded titles are treated as one song. Catches typos and
# cross-language spellings of the SAME title ("orcuridad"/"oscuridad",
# "Reio"/"Río"). Held high on purpose: at 0.92 "todo se transforma" and
# "todo se complica" (0.65) stay apart, which they must.
TITLE_SIMILARITY = 0.92

# Entities that re-record other people's catalogues at volume. Not artists in
# any sense that matters to a recommender: 9 of the 19 "performers" of "Al Otro
# Lado Del Río" are these, so they dominate any cover-count signal. Substring
# match on a normalised name, and a FLAG rather than a filter.
COVERS_MILL_HINTS = (
    "karaoke", "tribute", "string quartet", "piano", "rockabye", "workout",
    "movie sounds", "various interpret", "chill out", "acoustic heartstrings",
    "instrumental", "8-bit", "lullaby", "made famous by", "originally performed",
)

# Share of a person's page-1 credits that must carry a writing role before the
# remaining pages are worth paying for.
#
# Calibrated on four people, one request each (2026-09):
#
#     Jorge Drexler        0.97   songwriter          keep
#     Stephen Marcussen    0.15   mastering engineer  drop
#     Carles Campi Campon  0.12   engineer/player     drop
#     Fred Kevorkian       0.00   mastering engineer  drop
#
# The floor is not zero, because Qobuz mislabels: "Stephen Marcussen, Composer"
# appears verbatim on 15 of his first 100 tracks. That is the source data being
# wrong, not a parse error -- so the threshold has to clear a noise band, not
# just exclude zero. 0.35 sits in the gap between 0.15 and 0.97.
#
# Four people is thin next to the 54 that tuned MIN_ROLE_WEIGHT and MIN_SIGNAL.
# Anyone genuinely between 0.15 and 0.35 is unclassified by this evidence.
MIN_WRITING_SHARE = 0.35


# ---------------------------------------------------------------------------
# WATCHLIST PROFILE (stages/profile.py)
#
# Two numbers, no ratio: lifetime active months is depth, months inside the
# window is currency. A ratio was tried and dropped -- dividing by lifetime
# months made a revival take ten months for a deep artist and five for a new
# one, punishing an artist for having mattered once.
# ---------------------------------------------------------------------------

RECENT_WINDOW = 24       # months that count as recent
M24_FLOOR = 10           # active months inside the window to count as current
DEEP_FLOOR = 24          # lifetime active months to count as established
EMERGING_PLAYS = 100     # recent plays before a SHORT history is worth watching
BURST_RATE = 20          # recent plays per active month that make a lapse doubtful

# Measured on the 2026-05 export (190,131 listens, 159 months):
#
#     Drexler 23   Bjork 20   ROSALIA 19   Mars Volta 17   Waits 13   Extremoduro 12
#     Interpol 7   Mogwai 3   Animal Collective 3   Bob Dylan 3   Radiohead 3
#
# The floor sits in that gap, and the four below it were confirmed by hand as
# tastes that cooled. A 12-month window was worse: Interpol ties Nine Inch
# Nails, and Extremoduro drops out.


# EMERGING_PLAYS applies to emerging ALONE, and that asymmetry is measured, not
# tidy: scaling the month test to a short history (the min() below) let three
# recent months out of three qualify, so 2,006 artists were emerging, Camilo on
# two plays among them. 100 recent plays is roughly eight album listens and
# leaves 72 -- the same order as the 108 entries favourites.json already holds.
#
# It is NOT applied to core, because core artists do not all clear it:
# Sparklehorse has 60 lifetime months and 52 recent plays. Months already carry
# the weight there, and a second constraint would demote him on no evidence.


def band(months: int, recent: int, recent_plays: int) -> str:
    """core | lapsed | emerging | thin.

    `lapsed` is the one that earns the design: real past interest, nothing now.
    Do not watch it for new releases, but keep the credit-graph edge -- that is
    roadmap.md's "prune the first, never the second".

    The min() scales the currency test to a short history, since an artist you
    found four months ago cannot have ten recent months. EMERGING_PLAYS is what
    stops that scaling from admitting everyone you played once.
    """
    current = recent >= min(M24_FLOOR, months)
    if months >= DEEP_FLOOR:
        return "core" if current else "lapsed"
    if current and recent_plays >= EMERGING_PLAYS:
        return "emerging"
    return "thin"


def burst(recent: int, recent_plays: int) -> bool:
    """Were those few months INTENSE? A flag on a lapse, never a verdict.

    Omar Rodriguez-Lopez has 5 active months in the last 24 and 163 plays
    inside them, last played this month: 33 a month, which is somebody gone
    back to, not a taste cooling. Months alone cannot see it.

    It stays a flag because intensity is a THIRD axis, not a correction to this
    one -- Sparklehorse is core at 5 plays per active month and Drexler is core
    at 136, so the rate says nothing about depth or currency. And every rule
    tried that promoted on it also promoted Interpol, who was judged cooled by
    hand on 6 of the last 6 months at 11 a month. Same stance as COVERS_MILL_HINTS
    and writing_tier's lyrics_only: flagged, never silently reclassified.

    Six of the 113 lapsed artists carry it, including both that the watchlist
    still watches -- which is exactly where a verdict is worth doubting.
    """
    return bool(recent) and recent_plays / recent >= BURST_RATE


# ---------------------------------------------------------------------------
# MATCH PLAUSIBILITY (the pools, on the READ side)
#
# sig_score is computed entirely from the REFERRER -- role weight x selectivity
# x how embedded that person is in the seed's catalogue -- and says nothing
# about whether that person was matched to the right Qobuz artist. So a shaky
# resolve inherits a strong referrer's weight, and the junk is not merely
# present but ranked first.
#
# Measured on the committed pools, 2026-10-18:
#
#     single_token_name  3,673 of 7,860 rows (47%)
#     Morgan               323 rows at score 1.00, the maximum
#     Henry Mancini        459 rows -- the Peter Gunn soundtracks, 1958-60,
#                              reached through a Spanish engineer who worked on
#                              Drexler records and not on Peter Gunn
#     Arcangel 309, Mama 291, Cooper 261, Francisco 244, Paulina 230
#
# A PENALTY rather than a drop, because the flag is not proof. An exact match on
# one common token is indistinguishable from a correct one at the layer that
# made it -- the name is all the evidence there is -- so "Morgan" may be a real
# collaborator. The row keeps its provenance and loses its place in the order,
# which is the same stance as COVERS_MILL_HINTS.
#
# 0.1 puts the worst of them (1.00) below the best clean row (0.80) without
# deleting anything, so a strong flagged match still outranks a weak clean one.
#
# Applied on READ, so the committed pools are not rewritten. Folding it into the
# stored score is the better fix and costs a full regeneration; this is what
# makes the list readable today.
# ---------------------------------------------------------------------------

MATCH_PENALTY: dict[str, float] = {"single_token_name": 0.1}


def match_confidence(flags) -> float:
    """How much to trust that this row's person was matched to the right artist.

    1.0 when nothing is suspect. Multiplicative, so two doubts compound rather
    than the worse one winning -- there is only one flag today, and a second
    would mean two independent reasons to disbelieve the same match.
    """
    confidence = 1.0
    for flag in flags or []:
        confidence *= MATCH_PENALTY.get(flag, 1.0)
    return confidence


def ranked_score(score: float, flags) -> float:
    """sig_score discounted by how plausible the match behind it is."""
    return score * match_confidence(flags)


# ---------------------------------------------------------------------------
# ALBUM PROVENANCE (stages/discover.py)
#
# Qobuz files a guest spot inside the GUEST's own discography, so artist/get on
# a seed returns records the seed did not make. Discovery walked all of them and
# credited everyone aboard as having worked on the seed's records, which is the
# relationship inverted: they did not make his record, he sang on theirs.
#
# Measured 2026-10-20 over cache/credits, no requests:
#
#     Jorge Drexler       15 of 62 albums are not his records -- and only 5 of
#                             the 15 say "feat." in the title, so the titles
#                             cannot be the test
#     Silvia Perez Cruz    3 of 44
#
# The test is who holds MainArtist across the album's tracks. A SHARE rather
# than "is the seed billed anywhere on it", because a various-artists
# compilation bills the seed on one track of twenty and is not his record
# either.
#
# 0.5, and the exact value is UNTESTED on purpose: across all 106 albums in the
# two corpora the seed holds MainArtist on every billed track or on none, never
# in between, so any floor in (0, 1] labels them identically. A compilation is
# the case that would tell two floors apart and there is not one yet. Half is
# the value that reads as "most of the record", which is the intent.
# ---------------------------------------------------------------------------

OWN_ALBUM_MAIN_SHARE = 0.5


def album_provenance(seed_billed: int, billed_tracks: int) -> str:
    """"own", "guest" or "unknown" for one album in the seed's discography.

    "unknown" is an absence of evidence, not a verdict of guest: no track on
    the album names a MainArtist, so the string holds nothing to decide with.
    Every one of the 500 cached tracks carries one today, which makes this a
    guard rather than a case -- and the reason it is not an exception is that a
    silent relabel of the whole album is the failure that matters here.
    """
    if billed_tracks <= 0:
        return "unknown"
    return "own" if seed_billed / billed_tracks >= OWN_ALBUM_MAIN_SHARE else "guest"


# ---------------------------------------------------------------------------
# POOL FILTERS (the three that were measured and never written down)
#
# 7,860 candidate releases, in one table, in an order that promotes the junk.
# todo.md's answer was filters before ranking, and named three. Re-measured
# 2026-10-20 over data/pool.json and data/pool_discogs.json, no requests:
#
#     all rows                                7,860
#     Qobuz-native (via.path is not discogs)  1,470
#     side credits (not the first artist)     1,998
#     musician or producer referral           2,778
#     all three                                 291   of which 220 are by
#                                                     artists never played
#
# Each one answers a different objection, and each was measured separately:
#
# REFERRAL CLASS. 73% of the Discogs pool's referrals come through MIXING:
# 5,347 engineering against 1,942 production, and no performance at all. A
# mastering or mixing credit is an industrial service -- ROLE_WEIGHTS has said
# so since this file was written -- so a pool ordered by role weight still
# CONTAINS mostly rows that role weight scores at 0.15.
#
# SIDE CREDITS. 5,862 of the 7,860 rows are a release where the referring
# person is the FIRST credited artist: their own record, not one they shaped.
# The thesis is "this person made their mark on somebody else's record", and
# that is the 1,998.
#
# SOURCE. The Discogs path is 81% of the rows and every junk row traced to it
# (the Henry Mancini and Morgan rows under MATCH_PENALTY). Dropping it is the
# single widest cut here, which is why it is not folded into the others.
#
# A WHERE clause, not a deletion: the pools are regenerated from an API and
# the rows carry their own provenance, so an excluded row stays queryable and
# a filter that turns out to be wrong costs a different query rather than a
# refetch. Same stance as MATCH_PENALTY applying on read.
# ---------------------------------------------------------------------------

# Referral classes worth keeping: somebody chosen for how they sound. Note what
# is absent -- "engineering", and the WEAK_CLASSES (writing, billing).
REFERRAL_CLASSES = {"performance", "production"}


def musical_referral(roles) -> bool:
    """Was this release reached through a musician or a producer?

    True if ANY referring role qualifies, not all of them: a person credited
    as producer AND engineer on the seed's records was still chosen for how
    they sound.

    815 rows do mix a kept class with a dropped one, every one of them on the
    Discogs path, so none survives the source filter and "any" and "all" return
    the same 291 today. The choice only starts to matter when the Discogs path
    is fixed rather than excluded.
    """
    return bool({role_class(role) for role in roles or []} & REFERRAL_CLASSES)


def shortlisted(source: str, via_is_first_artist: bool, roles, score=None) -> bool:
    """The filters together: a pool row worth a person's attention.

    `source` is the pool the row came from ("qobuz" or "discogs"), the same
    value `releases.source` carries in the store. `score` is the row's stored
    `sig_score`, and a zero one is dropped by `carries_signal` -- see the block
    above for why that is not one of the three taste filters.
    """
    return (source != "discogs"
            and not via_is_first_artist
            and musical_referral(roles)
            and carries_signal(score))


# ---------------------------------------------------------------------------
# ONE LIST, NOT ONE PRODUCER'S DISCOGRAPHY (the cap)
#
# The three filters in POOL FILTERS leave 291 rows, and 212 once unheard,
# streamable and since-2015 are asked for as well -- but they arrive through
# only 24 people, and the top of the order is whichever of them was reached
# through the strongest credit. Nine of the first rows were Juan Campodonico.
# A list like that tests one producer, not the graph.
#
# Measured 2026-10-20 over the 212:
#
#     cap   rows   distinct people in the top 20
#       1     24   20
#       2     38   12
#       3     52    8
#       5     80    7
#
# 2, which is where the top of the list stops being one person without
# flattening it to one row each. At 1 the strongest referral and the second
# strongest are indistinguishable, which throws away the thing the score is
# for; by 3 a single producer is a third of the first ten again.
#
# The key is via_name -- the person whose catalogue the release came out of.
# todo.md and store.md both said via_through, which is NULL on all 1,470
# Qobuz-path rows (it records which of the SEED's people referred, and only
# the Discogs path writes it), so capping on it would have put the entire
# shortlist in one group.
#
# A cap, not a diversity score: it is a rule about the list rather than about
# any row, so no row's score changes and nothing is reordered. The row that
# loses its place is still in the pool, and raising the cap brings it back.
# ---------------------------------------------------------------------------

MAX_PER_REFERRER = 2


def cap_per_referrer(rows, referrer, limit: int = MAX_PER_REFERRER) -> list:
    """The first `limit` rows per referrer, in the order given.

    Order in, order out: the caller has already decided what "best" means, and
    this only thins what they produced. `referrer` reads the key off a row, so
    this does not need to know the shape of one.
    """
    kept: list = []
    seen: dict = {}
    for row in rows:
        key = referrer(row)
        if seen.get(key, 0) >= limit:
            continue
        seen[key] = seen.get(key, 0) + 1
        kept.append(row)
    return kept


# ---------------------------------------------------------------------------
# A REFERRAL THAT CARRIES NOTHING (score 0)
#
# Measured on the regenerated Qobuz pool, 2026-10-20: 5 of its 50 referrers
# hold ZERO of the seed's own albums -- Chab, Susana San Jose, El David
# Aguilar, Ulises Hadjis, Cantamarta. They passed the `--min-albums 2` gate on
# two albums each, and both albums were records the seed GUESTED on, so they
# never worked on one of his. Once `embedded` is computed from own albums their
# score is 0.0, by the scoring's own arithmetic.
#
# They are not weak referrals, they are not referrals: the relationship the
# pool claims does not exist. The right place for them is discovery's
# `co_artists` block, which is where D14 puts an artist the seed made a record
# WITH.
#
# So this is a different test from the POOL FILTERS above, which are taste --
# an engineering referral is real and worth less. A score of 0 is the scoring
# saying there is no referral at all, and a list has no reason to hold it.
# ---------------------------------------------------------------------------


def carries_signal(score) -> bool:
    """Does this referral assert any relationship at all?

    Strictly greater than zero, and None is not zero: a missing score is an
    absence of evidence (a pool written before the score existed), not a
    verdict of worthless, so it passes rather than being silently dropped.
    """
    return True if score is None else score > 0


def seed_albums_of(stats) -> int:
    """How many of the SEED's own records this person worked on.

    The one place that reads discover.py's own/guest labelling, so the gate in
    resolve_qobuz.py and the score in signal_for cannot drift apart. Falls back
    to the unlabelled total for a discovery file written before D14, which is
    the old inflated number -- callers flag `unlabelled_albums` when they take
    it, rather than letting it pass for a measured one.
    """
    stats = stats or {}
    own = stats.get("own_albums")
    return (stats.get("albums") or 0) if own is None else own
