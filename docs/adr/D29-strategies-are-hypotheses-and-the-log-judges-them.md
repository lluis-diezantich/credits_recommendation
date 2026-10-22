# D29: Ranking is several named strategies, none of them measured, and a committed log is what will settle it

- **Status:** Accepted
- **Date:** 2026-10-22
- **Where it lives:** `policy.RANKING_STRATEGIES` and the four `rank_*`
  functions; `core/rank.py`; `stages/rank.py`; `data/shown.json` (un-ignored);
  `core.explain.cross_seed_sentence`.

## Context

todo.md step 3. Ten seeds are walked and the column a cross-seed ranker needs
finally has range: **20 of 287 co-artists connect to more than one seed**, one
of them to three, where four seeds ago it was 2 of 99.

The inputs are all stored. What is not available, and will not be soon, is any
basis for the weights. `roadmap.md` has said from the start that nothing scores
this list, and `policy.py`'s own first rule — D4, a threshold arrives with
evidence or not at all — cannot be satisfied by a ranking nobody has tested.

Two further facts shaped the design:

- **The ubiquity penalty has no input.** `selectivity()` needs
  `discogs_total_releases`. Measured 2026-10-22: 8 people in the store have it
  and **none is a co-artist** (0 of 307). Our corpus only sees a person's
  appearances with our own seeds, so "degree in the graph" collapses into the
  seed count already being used. A much-guested singer is the failure mode
  todo.md names and nothing free distinguishes them.
- **One feature was missing from todo.md's list**: how much the seed itself is
  played. A co-appearance through Jorge Drexler, whom the export has 6,988
  times, is not the evidence a co-appearance through an artist played 327 times
  is, and a ranking that ignores it treats them alike.

## Options

1. **One blended score**, weights tuned by eye. One number to defend, and
   nothing to compare it against — the usual end of which is that the weights
   never change because nothing says they are wrong.
2. **Named weight sets**, one linear scorer. Strategies as pure data, trivially
   comparable. But a rule that is not a weighted sum cannot be written, and
   "seed count first, everything else as a tie-break" is the project's own
   thesis.
3. **Named strategy functions in a registry**, each free to be linear or not.
4. Any of the above **plus a committed log** of what each run showed, so the
   weights can eventually be judged rather than argued about.

## Decision

**Option 3 and the log (4).**

`RANKING_STRATEGIES` maps a name to a pure function from a feature row to a
score. Four strategies, each one claim, written so the claim can lose:

| | the claim |
| --- | --- |
| `breadth` | corroboration across seeds beats repetition within one (D22). The default, because it is the project's own thesis and so has the most to lose |
| `direction` | who chose whom. Your artist appearing on somebody else's record is a deliberate act; a guest on theirs was chosen by them or a label |
| `depth` | one relationship, many records, over years |
| `taste` | every co-appearance weighted by how much you play the seed it came through |

**Functions rather than weight sets, and the first strategy proved why.**
`breadth` was written as a weighted sum with `SEED_BREADTH = 10.0`, and a test
of its own claim failed: eight records tied with one extra seed. There is no
honest constant, because the record count has no ceiling. It returns a tuple
now — seed count, then everything else — and `core.rank.ranked` takes a float or
a tuple. A dict of numbers could have held neither shape.

**The weights are hypotheses and the file says so.** The block above them in
`policy.py` states it, this ADR states it, and `--score` is the thing that will
end it.

## Evidence

**None for the weights, which is the decision.** D4's rule is evidence or
nothing; the honest form of nothing is to say so and to ship the instrument.
`stages/rank.py --log` appends what a run showed — strategy, date, the ranked
names and the score the ordering actually used — to `data/shown.json`, which is
un-ignored and committed, the stance D11 took for the radar. `--score` reads it
back and asks, per strategy, how many of the names it showed have been played
**since the run that showed them**. The date in each entry is what makes that
possible; without it the log would score itself on listening that predated the
claim.

What IS measured is that the strategies disagree, which is the only thing that
makes having four of them worth the code. Over the 165 unheard candidates,
`breadth` against `taste`:

| | |
| --- | --- |
| candidates that change rank | **164 of 165** |
| furthest move | Tabaré Cardozo, 154th to 16th |

`--compare A B` prints that, because comparing two orders by eye does not scale
past ten rows.

## Consequences

**`core.explain.cross_seed_sentence` had to exist.** Ranking across seeds puts
multi-seed rows at the top by construction, and passing "2 artists you play" to
`co_artist_sentence` as though it were a name produced *"billed on 2 of 2
artists you play's records"*. That was todo.md step 4 and it turned out to be
load-bearing rather than cosmetic: a ranker whose top rows have broken
sentences has no product. One seed still delegates to the old function, so
there is one sentence shape per claim rather than two that drift.

`stages/rank.py` applies the same two read-side filters `co_artists.py` does —
D24's `NOT_ARTISTS` and D27's `billed_as_musician`. Not optional: "Penelope
Cruz" now reads as a genuine two-seed intersection in the raw table, on "313"
with both Pérez Cruz and Residente, and a ranker without the filter would put
her near the top of the list.

What this does not do:

- **It does not penalise ubiquity**, and cannot until a release count per
  person exists. That needs a request each — 307 for the current corpus — and
  it is the strongest argument for spending them.
- **It does not rank the seeds.** A candidate reached through ten seeds you
  barely play would outrank one through Drexler under `breadth`. `taste` exists
  as the counter-claim, which is the point of having both.
- **`--score` says nothing yet.** It needs runs on file and a month of
  listening to arrive. The first number it gives will be noise; the tenth will
  not.

What would reopen it: the first `--score` output with enough runs to separate
the strategies. If one of them wins clearly, the others become a comment in
this file rather than code — and if none does, the features are wrong rather
than the weights.
