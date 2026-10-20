# D2: `core/` is pure and offline; `stages/` and `radars/` do the network and the printing

- **Status:** Accepted
- **Date:** 2026-09-02 (hardened 2026-10-16 when the suite moved in)
- **Where it lives:** [`core/`](../../core), [`stages/`](../../stages),
  [`radars/`](../../radars), argued in [`../architecture.md`](../architecture.md)

## Context

The decisions in this project were written where they were first needed: wedged
between a fetch and a print inside a long `main()`. Nothing in that shape can be
tested without a network stub, so none of it was tested — `stages/discover.py`
and `stages/resolve_qobuz.py` were still at 0% coverage on 2026-10-18 for
exactly this reason.

## Options

1. **Test the orchestration**, stubbing HTTP per test and asserting on printed
   output: covers the real code path, and every test carries a stub.
2. **Extract each decision into a pure function** and test that, leaving
   `main()` as plumbing: the decisions become cheap to test, the orchestration
   stays uncovered.

## Decision

Option 2, with the split made physical: `core/` is pure and offline and imports
no policy, `stages/` and `radars/` hold the network calls and the printing.

## Evidence

`stages/writing.py` and `stages/resolve_discogs.py` are the worked examples:
`classify_rows`, `flag_album_wide_credits`, `fold_songs`, `pages_needed`,
`gate_verdict`, `select_targets`, `signal_of`, `known_totals`, `role_census`.
110 decision tests followed, and the refactor was verified behaviour-preserving
— `writing.py` reproduces the committed `writing_jorge-drexler.json` byte for
byte from `cache/` alone.

## Consequences

- Coverage reads honestly: a stage's uncovered lines are its orchestration, by
  construction, not its judgement.
- A decision that cannot be extracted is a signal the decision is not yet clear.
- The orchestration genuinely is untested, and `build_pool()` is where that will
  first hurt — recorded in [../../todo.md](../../todo.md) rather than fixed,
  because stubbing Discogs plus the filesystem buys much less than the decision
  tests did.
