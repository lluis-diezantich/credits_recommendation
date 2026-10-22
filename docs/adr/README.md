# Decisions (ADRs)

One file per decision that shapes what this project recommends or how the repo
is laid out. IDs `D1`, `D2`, … are stable, and the code refers to them.

Why these exist alongside the other docs: `README.md` says what the layout IS,
`docs/architecture.md` argues for it, `CLAUDE.md` lists the traps, and
`todo.md` tracks what is left. None of them is a record of *what was decided,
when, against which alternative*. D1-D13 are backfilled from the code and the
history on 2026-10-20; D14 was written as the change was made, which is the
intended way round from here.

## How to add or change one

1. Copy [template.md](template.md) to `D<next>-<short-name>.md`.
2. Add a row to the index below.
3. Never rewrite an accepted decision. Write a new one, and mark the old one
   `Superseded by DN` — the reason it was decided the other way is the point of
   keeping it.
4. A number in an ADR is a measurement with a date on it, the same rule
   `policy.py` follows. If it was not measured, the Evidence section says so.

## Index

| ID | Decision | Status |
| --- | --- | --- |
| [D1](D1-policy-at-the-root.md) | Every contestable number lives in `policy.py`, at the root | Accepted |
| [D2](D2-pure-core-dirty-edges.md) | `core/` is pure and offline; `stages/` and `radars/` do the network and the printing | Accepted |
| [D3](D3-offline-tests.md) | Tests stub the network at the seam, and never call a real API | Accepted |
| [D4](D4-measured-against-real-listening.md) | A threshold arrives with evidence from the full export, or not at all | Accepted |
| [D5](D5-flag-rather-than-reclassify.md) | When two signals disagree about one artist, flag it rather than reclassify | Accepted |
| [D6](D6-store-is-derived.md) | `data/music.db` is derived, disposable and rebuilt from JSON | Accepted |
| [D7](D7-cache-is-the-corpus.md) | `cache/` is the source of truth for what an API said, and is not backed up | Accepted |
| [D8](D8-one-pipeline-for-now.md) | The Friday known-artist radar is the whole product for now | Superseded by D22 (seeds only) |
| [D9](D9-taste-in-active-months.md) | Taste is measured in active months, not play counts | Accepted |
| [D10](D10-ask-musicbrainz-who-stopped.md) | Ask MusicBrainz who has stopped, rather than guessing from release dates | Accepted |
| [D11](D11-radar-state-in-ci.md) | Radar state lives in `data/ci/`, committed by the workflow after the issue opens | Accepted |
| [D12](D12-hashed-locks-advisory-format.md) | CI installs from hashed lockfiles; `ruff format` is advisory | Accepted |
| [D13](D13-match-plausibility-on-read.md) | A shaky name match is penalised on read, not dropped | Accepted |
| [D14](D14-co-appearance-is-its-own-output.md) | An album in the seed's discography is labelled own or guest, and co-appearance is its own output | Accepted |
| [D15](D15-filters-before-ranking.md) | The pool is filtered on read by three stored facts, before anything ranks it | Accepted |
| [D16](D16-cap-the-list-per-referrer.md) | The shortlist keeps at most two rows per referrer | Accepted |
| [D17](D17-fold-plausibility-into-the-score.md) | The resolvers fold match plausibility and own-album counts into the stored score | Accepted |
| [D18](D18-drop-score-zero-referrals.md) | A referral scoring zero is dropped, and the resolver stops fetching one | Accepted |
| [D19](D19-person-seed-is-the-grain.md) | Albums and tracks are per (person, seed), and `people` sums them | Accepted |
| [D20](D20-the-funnel-is-queryable.md) | Everything the funnel is made of reaches the store, keyed by seed | Accepted |
| [D21](D21-explanations-name-what-the-person-did.md) | An explanation names what the person did, and every clause is a row | Accepted |
| [D22](D22-co-appearance-is-the-second-pipeline.md) | Co-appearance becomes the second pipeline, and more seeds is now the point | Accepted |
| [D23](D23-ask-musicbrainz-who-the-seed-is.md) | Ask MusicBrainz which names the seed is credited under, and fold editions by title | Accepted |
| [D24](D24-a-record-nobody-holds.md) | A record no artist holds is a compilation, not a collaboration; and a hand list for billings that are not artists | Accepted |
| [D25](D25-one-person-one-key.md) | One person, one key, from a hand-edited alias file fed by a report rather than a name lookup | Accepted |
