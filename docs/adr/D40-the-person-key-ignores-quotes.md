# D40: The person key removes every quote, and `load.py` re-mints rather than trusting a stored one

- **Status:** Accepted
- **Date:** 2026-10-24
- **Where it lives:** [`core/names.py`](../../core/names.py) (`QUOTES`,
  `normalise`), [`stages/load.py`](../../stages/load.py) (the two re-mints in
  `load_people`, and the four merges on primary key)

## Context

`normalise` strips accents with an NFKD pass and an ASCII encode. A
typographic apostrophe has no ASCII form, so it is **dropped**; a straight one
is ASCII, so it is **kept**. One name therefore minted two keys depending on
which file wrote it:

    "Oscar D’León"  ->  oscar dleon      data/favourites.json, data/profile.json
    "Oscar D'León"  ->  oscar d'leon     the ListenBrainz export, 238 listens

Nothing joined them, so his play history was invisible to every lookup keyed
on a name. Found while measuring
[D39](D39-seeds-are-picked-to-deepen-a-scene.md): Óscar D'León read as a "new
cluster" with the salsa scene sitting next to him, because he appeared to have
zero listening sessions.

`data/aliases.json` already works around this by hand — Jórunn Viðar's entry
reads *"two apostrophes standing in for one accent"* — which is evidence the
key, not the alias file, is the right place.

## Options

1. **A hand alias per affected artist.** What the corpus already does once.
   Rejected: there are four of them in the profile today and the next export
   brings more, and this is a property of the key function rather than of any
   artist.
2. **Fold every quote to ASCII `'`.** Makes the two apostrophe forms meet.
   Rejected on measurement: it moves 24 stored keys and keeps a decoration
   nothing wants — `MARK “SPIKE” STENT` becomes `mark 'spike' stent`, where
   the typographic spelling already produced `mark spike stent`.
3. **Remove every quote and apostrophe, typographic and ASCII.** Both forms
   meet, and the nickname decorations land where the curly spelling already
   put them.

## Decision

Option 3, with a second change it forces: **`load_people` re-mints every
person key from the name instead of trusting the `key` stored in a discovery
file.**

Without that the change would be worse than the bug. A discovery file's `key`
was minted by whichever `normalise` ran when `discover.py` wrote it, while
`credits` is minted fresh on every load — so after this change a stored key
and a fresh one disagree for every name holding a quote, and the person splits
in half with the credits on one side. That is exactly D25's subject, arriving
from the other direction.

Removal, not replacement with a space: `O’Quin` is one word, and a space would
make it two and collide with anything called "O Quin".

## Evidence

Measured 2026-10-24 over `data/*.json`, `cache/`, and all 190,196 listens.

**Recovered, each previously reading zero:**

| artist | listens |
|---|---|
| Óscar D'León | 238 |
| Mother's Cake | 205 |
| Adolescent's Orquesta | 188 |
| Guns N' Roses | 146 |

**Merged, where the corpus held one person under two spellings** — 8 pairs,
each of which would otherwise have wanted a hand entry: Me'Shell Ndegéocello /
Meshell Ndegeocello, Hector "El Father" / Héctor "El Father" / Hector El
Father, Bonnie 'Prince' Billy / Bonnie Prince Billy, Santana "The Golden Boy",
Jose "Leni" Prieto, Jesus "Chuitin" Sanchez, Prash "Engine Earz" Mistry,
Alexander Abreu Havana D'Primera.

**No key collided that should not have.** Checked across every name in
`co_artists`, `people` and `listens`: the only keys that met were those eight
pairs, and each is one person.

**166 stored keys moved**, all of them a nickname in quotes. 142 moved onto a
key the other spelling already held, which is the merge above; the rest are
names the corpus holds once.

**What the fix cost elsewhere.** Merging two spellings into one key makes two
rows share a primary key, which the schema forbids and the loader caught:
`person_seeds`, `co_artists`, `person_albums` and `co_artist_albums` now merge
on their key — counts summed, dates taken as min and max, roles unioned —
rather than appending. `people` already did this across seeds; these do it
within one file. After the rebuild, 1,385 of 1,385 `co_artist_albums` rows
still join to a credit, which is the check that nothing split.

**The visible result:** `./stages/seeds.py --next` now leads with Óscar
D'León, joining the Celia Cruz scene at 22.9× chance on bolero/salsa, where
before the fix he read as a new cluster.

## Consequences

- **Every derived file must be rebuilt**, and that is cheap by
  [D6](D6-store-is-derived.md): `./stages/load.py` is one command and fetches
  nothing. `cache/` is untouched — the key is computed on read, never stored
  there.
- **`data/aliases.json` has one entry this makes redundant** (Jórunn Viðar).
  Left in place: it is harmless, and D25's stance is that the file is
  hand-edited and not pruned by code.
- **The stored `key` in a discovery file is now decorative.** It is still
  written, and nothing reads it. Worth removing when `discover.py` is next
  touched, so a future reader does not trust it again.
- **A quote can no longer distinguish two artists.** If two real acts differ
  only by an apostrophe, they now collide, and nothing in the corpus does
  today. `data/aliases.json` cannot fix that case — it merges, never splits —
  so it would need a different mechanism.
- **This is the measurement
  [D35](D35-the-seeds-own-band-is-its-own-reason.md) asked for**, from the
  other direction: it wanted a punctuation-stripping key before replacing the
  `SEED_OWN_BANDS` hand list, and `"K.U.K.L."` against MusicBrainz's `"KUKL"`
  is the remaining case. Periods are not quotes, so that one is still open —
  but the shape of the answer is now in `normalise` to copy.
- **What would reopen it:** two artists in the corpus whose names differ only
  by a quote.
