# D27: The role-class fallback gets rules, sleeve credits get a class, and a hand entry becomes a rule

- **Status:** Accepted
- **Date:** 2026-10-22
- **Where it lives:** `policy.role_class`, `role_weight`,
  `ENGINEERING_MARKERS`, `NON_MUSICAL_MARKERS`, `NON_MUSICAL_KEYS`,
  `billed_as_musician`; the read-side filter in `stages/co_artists.py`.

## Context

`role_class` fell back to `"performance"` for any token the `ROLE_CLASS` table
does not name, and `role_weight` fell back to `INSTRUMENT_WEIGHT` (0.8). The
reasoning was sound as far as it went — the remainder of a credits vocabulary
really is instruments, and `core/credits.py` had measured why an allowlist is
not the answer: 65 of 124 role tokens in one corpus appear in no table in
`policy.py` and nearly all are genuine (Spanish Guitar, Berimbau, Wurlitzer,
Theremin).

What it missed is that the families the table **does** name arrive in spellings
it does not. Measured 2026-10-22 over the store's 273 distinct role tokens:

| | |
| --- | --- |
| classed `performance` while belonging to a named family | **35 tokens** |
| credits rows carrying one | **577 of 22,019 (2.6%)** |

`2nd Engineer`, `Mix Engineer`, `Assistant Mixing Engineer`, `SoundEngineer`,
`VocalEngineer`, `StringEngineer`, `CoMixer`, `Engineer & Mixer`,
`RemixingEngineer`, `Recorder`, `SoundRecordist` — and the sleeve credits
`Art Director`, `Photographer`, `CoverArt`, `CoverDesign`, `Designer`,
`Studio`.

Because `performance` is in both `NAMEABLE_CLASSES` and `REFERRAL_CLASSES`,
they leaked two ways. Three co-artist explanations named one: Conrad Taylor
(`Re-Mixer`), Liniers (`Designer`) and Alba Molina
(`AssistantRecordingEngineer`). `Assistant Mixing Engineer` was also scoring
**0.8** — four times the listed `assistant engineer` at 0.2, and above
`mixing engineer` at 0.5.

This is the silent fallback the top of `policy.py` says the file exists to end.

## Options

1. **Extend `ROLE_CLASS` with the 35 tokens.** Smallest change, each one
   stated. But the next seed brings new spellings of the same families, which
   is exactly how these 35 arrived.
2. **Marker rules for the recognisable families**, keeping the instrument
   fallback for everything else.
3. **The same, plus changing the fallback itself** to an `unknown` class that
   is neither nameable nor a referral, so nothing can ever leak silently.
4. **File art and photo credits under `engineering`** rather than giving them
   a class, since both are services that say nothing about how a record
   sounds.

## Decision

**Option 2, with a new `non-musical` class** — so not option 4.

`role_class` now tries the table, then `NON_MUSICAL_MARKERS` /
`NON_MUSICAL_KEYS`, then `ENGINEERING_MARKERS`, then falls back to
`performance`. The markers are matched against `role_key` output, so
punctuation and case are already gone and `Engineer & Mixer`, `2nd Engineer`
and `SoundEngineer` all reduce to a string containing `engineer`.

`role_weight`'s fallback is class-aware for the same reason: an unlisted
engineering spelling is some variety of assistant, so
`UNLISTED_ENGINEERING_WEIGHT` is 0.2, matching the listed `assistant engineer`;
`NON_MUSICAL_WEIGHT` is 0.1, below `mastering engineer`'s 0.15, which holds the
weakest-signal title among roles that touch the sound at all.

Option 3 was rejected: it reclassifies genuine instruments out of
`performance` and loses the 0.8 the `ROLE_WEIGHTS` table intends for them,
which is the allowlist objection pointing the other way.

Option 4 was rejected because `engineering` would then mean two things, and a
rule cannot tell a sleeve designer from a mastering engineer — which the next
section is entirely about.

**Two exact table entries exist only to beat a marker.** `chorusmaster` and
`concertmaster` are `performance`: they are musicians, and `master` would
otherwise file them with the mastering engineers. Qobuz uses "Chorus Master"
for the singers in a chorus as well as whoever directs them — Carla Morrison
and three others hold it on one Pérez Cruz track. `artist` is `billing`:
"Workout Music, Artist" on a running-mix compilation is a billing line with no
person behind it, not somebody who drew the sleeve. This ends the older
invariant that `performance` was never a table value, only a fallback; with
markers in between, the table is now the only way to say "a musician, despite
looking like an engineer".

## Evidence

Every token's class diffed before and after, over the store:

| | |
| --- | --- |
| `performance` → `engineering` | 27 tokens, 302 rows |
| `performance` → `non-musical` | 8 tokens, 263 rows |
| anything else | 0 |

The three leaked explanation clauses are gone, and the instruments are
untouched: `Berimbau`, `Theremin`, `Wurlitzer`, `Spanish Guitar`, `Timpani`,
`Vocalist`, `Rap` and `StudioMusician` all still class `performance` at 0.8.

**And the rule D24 measured down now works.** `billed_as_musician` asks
whether a co-artist holds anything musical on the records they share, ignoring
the billing. Measured over 132 co-artists:

| | |
| --- | --- |
| billing only, nothing beyond it | 57 — passes, an absence of evidence |
| holds something musical | 74 |
| holds **only** sleeve credits | **1** — Liniers |

So `"liniers"` comes off `NOT_ARTISTS`, which is back to the four names that
genuinely need a human: two channels/actors and two of Björk's own bands.

The order of that story is the point, and it is recorded in the comment above
`NOT_ARTISTS`: the rule was tried against `MUSICAL_ROLES` and cut 5 real
features (Rosie Lowe, Yuna, PJ Sin Suela, Tosca) to catch 1 illustrator; the
hand entry was called the honest answer; then the class fallback turned out to
be the real cause. **A hand list was standing in for a defect one layer down,
and a rule only looks wrong while the data it reads is wrong.**

## Consequences

The filter is deliberately narrow: only `non-musical` fails it. A remixer
passes, because D21's rule that engineering is not worth NAMING in a sentence
is a different question from whether the person touched the record — Conrad
Taylor remixing a Björk track is a real artist to go and hear.

What this does not do:

- **The pool is not recomputed.** `releases.via_referral_classes` is a string
  the resolvers wrote, so the 477 Qobuz-path rows classed `performance` still
  carry whatever they were given. Some of them pass D15's referral filter only
  because of this defect. Recomputing means re-running `resolve_qobuz.py`,
  which costs requests, and the crew pipeline is paused — so this is a known
  stale column rather than a fixed one. It is in `todo.md`.
- **`MUSICAL_ROLES` is still an allowlist** and still missing `vocalist`,
  `rap` and `backgroundvocalist`. `discover.py` uses it to drop non-musical
  people from the crew graph, so that gate has the same gap this ADR just
  closed one layer up. Worth folding into `role_class` next.
- **The markers will over-reach eventually.** Two already needed exact
  entries to beat them. The guard is that the table wins, so the fix for the
  next one is one line.

What would reopen it: a token that is genuinely an instrument and contains one
of the markers. "Mixing bowl" is not an instrument; a "Master Drum" would be.
