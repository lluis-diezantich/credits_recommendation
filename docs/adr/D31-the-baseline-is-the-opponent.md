# D31: The similar-artist baseline is built as an opponent, scored by the same log

- **Status:** Accepted
- **Date:** 2026-10-22
- **Where it lives:** `core/similar.py`, `core/shown.py`,
  `stages/baseline.py`; `stages/rank.py --score` reads both sources.

## Context

`roadmap.md` has asked from the first commit whether a credit graph carries
signal a listening-similarity model does not. Nothing in the repo answered it,
because there was no second list — every measurement so far compares the
co-appearance list against *already-played rate*, which says the signal is real
and says nothing about whether it beats the free alternative.

[D29](D29-strategies-are-hypotheses-and-the-log-judges-them.md) built the
instrument for exactly this kind of question: a committed log of what a list
claimed, scored later against listening that arrived after the claim. It was
built for four ranking strategies. A baseline is the fifth thing to put through
it.

## Options

1. **Compare by eye.** Print both lists, read them. Free, and it answers
   nothing — the premise is about hit rate over months, not about which list
   looks better on a Tuesday.
2. **A separate baseline report with its own scoring.** Clear separation, and
   two scoring implementations that will diverge: a hit rate is only a
   comparison if both sides are measured the same way, over the same window,
   from the same record.
3. **Make the baseline a SOURCE in the existing shown-log**, scored by the
   same `--score` as the strategies.

## Decision

**Option 3.** `stages/baseline.py --log` writes into the same
`data/shown.json` as `stages/rank.py --log`, under the source name `similar`,
in a format `core/shown.py` now owns for both. `rank.py --score` reports a hit
rate per source, so "breadth" and "similar" appear in one table and are
comparable by construction.

`core/shown.py` is the extraction that made it possible: the log format and the
hit-rate arithmetic moved out of `stages/rank.py`, which had been the only
writer. `hit_rate` takes a `played_after(person_key, date)` callable so the
arithmetic stays plumbing and the SQL stays in the stage.

**The algorithm is pinned.** ListenBrainz exposes several similarity
algorithms and they return different lists, so `core.similar.ALGORITHM` names
the one the baseline is taken with and the cache filename carries it — a run
under a different model cannot read this one's files. A comparison run against
one algorithm today and another next month would be measuring the wrong thing.

The session-based algorithm was chosen as the fairest opponent: artists that
appear in the same listening sessions is the closest ListenBrainz has to
"people who play this also play that", which is the claim a credit graph is
trying to beat.

## Evidence

One request per seed, cached. Ten seeds, 100 similar artists each, measured
2026-10-22:

| | |
| --- | --- |
| similar-artist list, unheard | **207** |
| co-appearance list, unheard | **162** |
| in both | **23** — 6.6% of the union |

**The lists barely overlap, which was the guess on record in `todo.md` and is
now measured.** The 23 shared names are mostly contemporary Latin pop reached
both ways: Nicki Nicole, Ozuna, Sech, Paloma Mami, The Weeknd, Blood Orange.

The rest of that guess — "similarity wins on hit rate, co-appearance wins on
keepers you would never have found" — is **not** measured and cannot be yet.
Both sources now log, and `--score` will say. That is the whole point of
building the baseline as an opponent rather than as a report.

What the two lists look like is itself informative: the similar list leads with
Röyksopp, Garbage, The Prodigy, Massive Attack — plausible, well-known, and
mostly reachable from Björk alone. The co-appearance list leads with Conociendo
Rusia and Los Cojolites. Whether "plausible and well-known" beats "obscure and
checkable" is exactly the open question.

## Consequences

**`roadmap.md`'s founding question now has an instrument pointed at it.** It
needs runs and months, like everything else `--score` touches.

**Already-played is matched on two keys.** ListenBrainz answers in MBIDs and
`listens` carries one only where its own mapping found one, so an artist is
dropped as heard if either the MBID or `normalise(name)` matches. Matching on
one would have let through anybody whose name is spelled differently in the two
sources.

What this does not do:

- **It is not a recommendation pipeline.** No sentence, no explanation, no
  provenance — a similarity score is not evidence anybody can check, which is
  the asymmetry the whole project rests on. If the baseline wins on hit rate,
  that asymmetry is what is left to argue about.
- **It ranks on affinity, not on ListenBrainz's number.** That started as the
  raw maximum and was wrong, which the output showed within a minute of being
  read. The score is a session co-occurrence COUNT and scales with how much
  the seed is listened to globally, not with how close the neighbour is:

  | seed | top score | median |
  | --- | --- | --- |
  | Björk | 6,682 | 2,076 |
  | ROSALÍA | 1,645 | 398 |
  | Jorge Drexler | 364 | 83 |
  | Sílvia Pérez Cruz | **24** | 12 |

  A factor of 278 end to end, so a raw maximum ranked "artists ListenBrainz
  has a lot of data about" and called it similarity — Pérez Cruz's best
  neighbour scored below Björk's hundredth. Each seed's scores are divided by
  that seed's own ceiling now, which puts every seed's first suggestion at 1.0
  and keeps the distribution behind it: a neighbour three times clear of the
  next is a stronger claim than a flat run, and a rank would have discarded
  that. The raw number is kept beside the affinity as provenance only.

  **This mattered for fairness, not tidiness.** An opponent weakened by a
  scale artefact would have flattered the co-appearance list in `--score`,
  which is the one number this whole ADR exists to produce.

- **The seed count is only a tie-break.** Deliberate restraint: ListenBrainz
  has no cross-seed notion, and rewarding breadth here would be designing the
  opponent rather than using it. The co-appearance list is the one making the
  breadth claim, and it has to make it against a baseline that does not.

- **Run 1 of `similar` in `data/shown.json` used the raw-maximum order** and
  is left alone. The log records what was shown, and it was shown that way; an
  append-only record of claims that gets edited the first time it is
  inconvenient is worth nothing. One early run is noise that ten will drown.
- **It cannot be run per strategy.** The baseline has one order, so comparing
  it against four strategies means four hit rates against one. That is fine for
  the question asked and worth remembering before reading the table.

What would reopen it: ListenBrainz changing or retiring the labs endpoint, or a
`--score` result close enough that the algorithm choice matters. The second is
the interesting one — if `similar` and `breadth` finish within a few points,
the next question is whether a different similarity algorithm would have won,
and the pinned name is what makes that answerable.
