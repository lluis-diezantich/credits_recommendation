# D35: The seed's own band is dropped for its own stated reason, not as "not an artist"

- **Status:** Accepted
- **Date:** 2026-10-24
- **Where it lives:** [`policy.py`](../../policy.py) (`NOT_ARTISTS`,
  `SEED_OWN_BANDS`, `billed_as_artist`, `why_not_a_co_artist`),
  reported by [`stages/rank.py`](../../stages/rank.py) and
  [`stages/co_artists.py`](../../stages/co_artists.py)

Supersedes the hand-list half of
[D24](D24-a-record-nobody-holds.md) only. D24's compilation rule stands
unchanged.

## Context

D24 put four normalised keys in one `policy.NOT_ARTISTS` set: `colors` (the *A
COLORS SHOW* channel), `penelope cruz` (an actor reading on a track),
`k.u.k.l.` and `the sugarcubes` (Björk's own former bands). One set, one
reason printed for all four.

The second pair is not an instance of the first. Both are real bands with
discographies — the Sugarcubes are Björk's first band — and they are dropped
because they are *the seed under another name*, so "Björk made a record with
the Sugarcubes" is a tautology rather than a recommendation. D24's own comment
said exactly this; the reported reason did not.

So `./stages/rank.py` printed **`4 dropped as not an artist: Colors,
K.U.K.L., Penelope Cruz, The Sugarcubes`**, which states something false about
two of the four, in the same line as something true about the other two. It
was read off a run and queried immediately, which is the evidence that the
line is read.

This is the defect `why_not_a_co_artist`'s docstring already names one layer
up — "one place, so the reasons cannot be reported as each other", written
after calling Gesaffelstein "not an artist". The same mistake had been made
one list lower down, inside the first reason.

## Options

1. **Leave it and fix the comment.** Free. Keeps a filter whose output lies
   about two of its rows, in the one place a person reads it.
2. **Derive it from MusicBrainz `member of band`.** The relationship is
   already on the artist document `core/musicbrainz.py` fetches, so no new
   request. It does not work as the key: `normalise()` keeps the periods in
   `"K.U.K.L."` and MusicBrainz files the band as `"KUKL"`, so the two keys
   never meet. Fixing that means a name key that strips punctuation, which
   folds other names too and is its own measurement.
3. **Split the set, keep one filter.** `SEED_OWN_BANDS` beside
   `NOT_ARTISTS`; `billed_as_artist` reads both, because the consequence is
   identical and no caller wants them apart; `why_not_a_co_artist` returns a
   fourth reason. Hand-maintained, like the list it comes out of.

## Decision

Option 3. The drop was always right and only the reported reason was wrong, so
the change is to the reason and not to the filter — nothing enters or leaves
the candidate list because of this ADR.

Option 2 stays the eventual answer and is now blocked on one thing rather than
on a judgement: a punctuation-stripping name key, measured. The comment on
`SEED_OWN_BANDS` says so, so the next reader finds the cheap derivation before
extending the hand list.

## Evidence

Not a measurement — a false statement in a report, found by reading
`./stages/rank.py --compare breadth taste` on 2026-10-24.

The size is worth stating because it bounds what the fix can buy: 2 of 380
candidates, and **0 rank changes**. Run after the split, the four drop lines
read `7 … a remix only`, `2 … not an artist`, `1 … nothing musical`,
`2 … the seed under another name`, and the ranked list is identical.

Both hand lists stay checkable against a walked corpus, which is D24's stance
and unchanged: ten seeds walked, four keys, no name added on speculation.

## Consequences

- **A reader can act on the drop line.** "Not an artist" invites a correction;
  "the seed under another name" is self-evidently right and needs no reply.
  The line's whole purpose is to be audited by a person, and one of its two
  halves could not be.
- **Two hand lists where there was one**, and a name could go on the wrong
  one. The test asserts both memberships for that reason, and the sets are
  disjoint by inspection rather than by code.
- **It does not generalise.** Seed 11's own former band arrives unnoticed,
  exactly as before. Option 2 is what fixes that for every seed at once, and
  the punctuation-key measurement it needs is in
  [../../todo.md](../../todo.md).
- **What would reopen it:** a third seed with a renamed band, which makes the
  hand list the wrong shape and the name key worth measuring; or any caller
  that wants `billed_as_artist` to answer differently for the two lists,
  which would mean the consequence is not identical after all and the single
  filter was wrong.
