# D4: A threshold arrives with evidence from the full export, or not at all

- **Status:** Accepted
- **Date:** 2026-10-18
- **Where it lives:** the comments beside `MIN_WRITING_SHARE`, `M24_FLOOR` and
  `EMERGING_PLAYS` in [`policy.py`](../../policy.py);
  `core.listens.newest_export`

## Context

These thresholds decide what a person sees, and there is exactly one ground
truth available: the owner's own ListenBrainz export. Two failures made the rule
explicit rather than assumed.

`stages/load.py` picked its export with `sorted(glob)[-1]`, and
`listenbrainz_sample.zip` sorts after the real file — so a 2,000-listen sample,
1% of the data, shadowed 190,196 listens for months. Every number measured in
that period was wrong by about 95x, and `data/music.db` was built from it.

Separately, `docs/store.md` claimed 190,196 listens while the store actually
held 2,000, and nothing verified either figure.

## Options

1. **Pick the newest export by filename**: what was there, and what broke.
2. **Pick by size**, in one function both stages call: the real export is always
   the largest, and a sample cannot shadow it.

## Decision

Option 2 — `core.listens.newest_export` — plus the standing rule: a number in
`policy.py` names the artists it was measured against, in the comment beside it,
and a doc that states a number nothing verifies is expected to drift.

## Evidence

The full export holds 190,196 listens against the sample's 2,000. Radiohead
lands `lapsed` on 73 lifetime active months against 3 recent, confirmed by hand.
The tracks-against-plays rule that used to be in `todo.md` did not survive the
full file: every artist sits between 0.50 and 1.0 tracks per play, so it
discriminates nothing — a rule that only looked predictive on 1% of the data.

## Consequences

- Any number in this repo can be checked, which is why ADRs carry an Evidence
  section at all.
- Thresholds calibrated on one listener do not transfer. Accepted: there is one
  listener.
- `data/listens_months/` is committed so the snapshots survive a laptop and the
  calibration can be redone ([D11](D11-radar-state-in-ci.md)).
