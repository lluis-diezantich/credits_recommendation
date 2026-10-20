# D1: Every contestable number lives in `policy.py`, at the root

- **Status:** Accepted
- **Date:** 2026-09-02 (reaffirmed 2026-10-17 when it was covered by tests)
- **Where it lives:** [`policy.py`](../../policy.py), and the invariant in
  [`CLAUDE.md`](../../CLAUDE.md)

## Context

The role-weight table existed twice, once in each resolver. The two never
disagreed on a shared key — they disagreed by *omission*, and a missing key
falls through to `INSTRUMENT_WEIGHT` (0.8), the weight for an unrecognised
instrument credit. Nine spellings diverged that way, always upward, always for
the credits that deserve the least weight: `mastered by` was 0.15 in one file
and 0.8 in the other, `written-by` 0.30 against 0.8.

## Options

1. **A shared module imported by both resolvers**, next to the code that uses
   it: the import graph decides where a number goes, so a threshold ends up
   wherever it was first needed.
2. **One file at the root, outside the package**, holding every judgement call,
   which `core/` is forbidden to import.

## Decision

Option 2. `policy.py` holds every number a person could argue with, at the top
level where it cannot be mistaken for plumbing. `core/` takes a threshold as an
argument instead of importing it.

## Evidence

Nine divergent role spellings across the two resolvers, all biased upward
(`policy.py`'s own docstring lists them). Not a threshold, so no measurement:
the argument is structural.

## Consequences

- A threshold buried in the module that consumes it is now a bug by definition,
  which is what makes "where does this number live" answerable without reading
  the call graph.
- `policy.py` is a long file of unrelated constants, organised by comment block
  rather than by module. Accepted: the alternative is the one that failed.
- Every value in it carries the artists it was measured against ([D4](D4-measured-against-real-listening.md)).
- It is at 100% coverage as of 2026-10-17, so the three disagreeing role
  vocabularies are pinned against each other and unifying them fails a test
  rather than silently rewriting a column of stored data.
