# TODO

What is known to be missing, grouped by what kind of work it is. Moved out of
the README so the entry point stays an orientation rather than a backlog.

Not the same thing as [roadmap.md](docs/roadmap.md), which assesses this
project *as a recommender*, stage by stage, nor [docs/adr/](docs/adr/README.md),
which records what was decided and against which alternative. This file is work
items.

## Where this is going (revised 2026-10-20)

**Two pipelines now, and the cheap one is the good one.**
[adr/D22](docs/adr/D22-co-appearance-is-the-second-pipeline.md) has the
argument; it supersedes the "one pipeline for now" framing that stood here,
because one of that framing's two measurements turned out to be wrong.

| | per seed | what it buys |
|---|---|---|
| the discovery walk — **co-appearance** | ~50 requests, once, then cached | the 59% / 40% list, with a sentence each |
| resolve + pool — the **crew graph** | ~160 requests | the 13-16% list, filtered to 38 rows |

~~Growing the credit graph is expensive, so the thing to avoid is more
seeds.~~ True of the pool path, and it is still paused. False of the
co-appearance path, which is where the signal is: **more seeds is now the
point**, on that path only.

**The pool is still not trustworthy**, and that part of the old framing holds.
Nothing is built on top of it; the filters under Correctness make it readable,
not correct.

### The plan, in order

1. **~~Filter the junk out of the co-artist list.~~** Done 2026-10-22
   ([adr/D24](docs/adr/D24-a-record-nobody-holds.md)), and the thing it was
   named for was the small half of it. "Colors" and "Penelope Cruz" are two
   rows on a hand list; the 20 others were **one album**. *Army Of Me*, Björk's
   remix record, is 20 tracks by 20 remixers, so she holds none of it and D14
   labelled it a guest spot once per remixer — 20 of her 35 co-artists, and the
   same 20 in her crew graph. `album_provenance` now returns a fourth value
   when no artist holds half the billed tracks, which reuses
   `OWN_ALBUM_MAIN_SHARE` rather than adding a number: 1 album of 258 is under
   it, at 5%, and the next one up is at 91%.

   **121 co-appearances → 97, and 73 unheard artists shown → 51.** Filtered on
   read, so the rows stay queryable (D15).

   Residue: the hand list does not generalise — seed 5 arrives with its own
   channel or actor and nothing notices. If three more turn up, the rule to
   write is a session brand's name appearing in the album title.

2. **~~Probe two seeds outside the Iberian cluster.~~** Done 2026-10-20 with
   Little Simz and Björk, ~200 requests, and it paid for itself immediately —
   the full result is in
   [adr/D22](docs/adr/D22-co-appearance-is-the-second-pipeline.md). **The
   method generalizes and the counts do not.** Gorillaz, Sampha, Thom Yorke,
   Dirty Projectors, Shygirl, ANOHNI, Yves Tumor and alt-J are real, checkable
   collaborations no genre model would produce. But three identity defects that
   two Iberian seeds could never have shown now corrupt every count — see
   **Correctness** below. **All three are fixed** (D23, D25), and so is the
   compilation the probe turned up with them (D24). Nothing blocks step 3.

   **~~The rule for picking the next seeds.~~** Written 2026-10-22
   ([adr/D26](docs/adr/D26-seeds-by-rule.md)): `policy.seedable` is 17 of 24
   recent months, plus `core` or `emerging` with 500 lifetime plays, and
   `stages/seeds.py` applies it. `./stages/seeds.py --next 8` prints the
   commands.

   17 rather than 18 because 18 misses Sílvia Pérez Cruz by one month, and her
   walk is where the 40% already-played measurement comes from — the floor is
   validated by selecting all four seeds already walked. The plays floor is
   what lets `emerging` through at all, and it has to: **a `core`-only rule
   does not select Little Simz**, who is `emerging` on 21 lifetime months
   against `DEEP_FLOOR`'s 24 and is the seed that proved the method
   generalises.

   **Still to do: walk them.** 27 candidates, ~50 requests each, and
   `discover.py --artist a b c` takes them in one run now. Nathy Peluso and
   ROSALÍA are walked (6 seeds), which took intersections from 2 to 4; the next
   four guaranteed ones are Natalia Lafourcade, Residente, C. Tangana and
   Rubén Blades, and `seeds.py` orders them first on purpose, so step 3 gets a
   column with range after two or three walks instead of after eight. Each walk wants its alias report read once afterwards
   ([adr/D25](docs/adr/D25-one-person-one-key.md)) — ten minutes, and the
   counts are right before anything ranks them.

3. **~~Rank across seeds.~~** Built 2026-10-22
   ([adr/D29](docs/adr/D29-strategies-are-hypotheses-and-the-log-judges-them.md)):
   `stages/rank.py`, four named strategies in `policy.RANKING_STRATEGIES`, the
   ordering in `core/rank.py`.

   **None of the weights is measured, and that is the decision rather than a
   shortcut.** Nothing scores this list, so each strategy is one claim written
   so it can lose — `breadth` (corroboration across seeds, the default and the
   project's own thesis), `direction` (who chose whom), `depth` (one
   relationship over years), `taste` (weighted by how much you play the seed).
   `--compare breadth taste` shows that they genuinely disagree: **164 of 165
   candidates change rank**, Tabaré Cardozo moving 154th to 16th.

   `breadth` is lexicographic because its own test caught it lying: as a
   weighted sum with a seed constant of 10.0, eight records tied with one extra
   seed, and no honest constant exists because the record count has no ceiling.
   Strategies are functions rather than weight vectors for exactly that reason.

   **Still open and it needs requests: the ubiquity penalty has no input.**
   `selectivity()` wants `discogs_total_releases`; 8 people in the store have
   it and **none is a co-artist** (0 of 307). Our corpus only sees a person's
   appearances with our own seeds, so graph degree collapses into the seed
   count. A much-guested singer still behaves like Fred Kevorkian. 307 requests
   would fix it, and it is the strongest case for spending them.

   **The first thing it ranked top was wrong, twice over**, and both are fixed
   in [adr/D30](docs/adr/D30-a-remix-is-not-a-collaboration.md). Conrad Taylor
   led the list on "Berghain (Remix)": his two seeds were ONE record (ROSALÍA
   and Björk are both billed on it, so the album counted twice), and his only
   credit on it was `Re-Mixer` — he reworked a finished record and the sentence
   claimed he made two with them. `breadth` leads on `corroboration` now, the
   smaller of seeds and distinct albums, and a remix-only candidate is dropped
   on read. 165 candidates → 162, and the list leads with Conociendo Rusia on
   a real two seeds and two records.

   What the strategies read (two features were not on this list before):
   `seed_plays` — a co-appearance through Drexler at 6,988 plays is not the
   evidence one through an artist played 327 times is — and `corroboration`.
   Rank on
   `seed_records + their_records` and not on `albums`, which counts every
   sleeve two artists are printed on: it put Coldplay, Burna Boy, Elyanna and
   tINI at the top of the Little Simz list on the strength of one single stored
   five times (fixed by D23), and a remix compilation above a real record
   (fixed by D24). `stages/co_artists.py` and `docs/store.md` already order on
   the right number. The inputs are already stored: how many of your
   artists made a record with them, how many records each way, the direction
   (the seed guesting on THEIR album is the stronger claim — your artist chose
   to show up), the roles, recency. Plus a **ubiquity penalty**, because
   `selectivity()` exists for the person who appears everywhere and a
   much-guested singer behaves exactly like Fred Kevorkian.

   **Still not before step 2, re-measured 2026-10-22 with four seeds: 97 of 99
   co-artists connect to exactly ONE seed.** The two that do not are still Lau
   Noah and Salvador Sobral, both on Drexler and Pérez Cruz, both already
   played — Little Simz and Björk added no intersection at all, with each
   other or with the Iberian pair. The ranker's main input is constant, so
   there is nothing to weight. D26's walk order exists to fix exactly this.

4. **~~Keep the sentence through the ranking, and make it multi-seed.~~** Done
   2026-10-22 with step 3, because it turned out to be load-bearing rather than
   cosmetic: ranking across seeds puts multi-seed rows at the top by
   construction, and passing "2 artists you play" to `co_artist_sentence` as if
   it were a name produced *"billed on 2 of 2 artists you play's records"*. A
   ranker whose top rows have broken sentences has no product.

   `core.explain.cross_seed_sentence` now reads *"Conrad Taylor has made 2
   records with 2 artists you play — ROSALÍA and Björk — e.g. Berghain (Remix)
   (2026). Never played."* One seed delegates to the old function, so there is
   one sentence shape per claim rather than two that drift.

   Still thinner than the form this entry asked for: it names the seeds and the
   total, not the per-seed split ("2 of his, 1 of hers"). The counts are in the
   row beside it and `--json` carries them.

5. **~~Log what was shown.~~** Built 2026-10-22 alongside step 3, same ADR.
   `./stages/rank.py --log` appends the strategy, the date, the ranked names
   and the score the ordering used to `data/shown.json` — un-ignored and
   committed, the stance [adr/D11](docs/adr/D11-radar-state-in-ci.md) took for
   the radar. `--score` reads it back and asks, per strategy, how many of those
   names were played **after** the run that showed them.

   **It says nothing yet, and cannot.** It needs runs on file and a month of
   listening to arrive. The first number will be noise; the tenth will not.
   Until then every weight in step 3 is a hypothesis with an order.

   Still not answered by it: whether seed 9 earned its 50 requests. The log
   scores strategies, not seeds. A per-seed version is the same file with a
   different group-by, once there is anything in it.

6. **Delivery, half done.** `./stages/rank.py --markdown` is the issue body —
   the sentence leads, the score goes in a `<sub>` line, and the posting
   command prints on stderr so the body stays a body. Pair it with `--log`:
   posting IS the showing, so that is the run worth recording.

   **It cannot be a workflow, and that is a fact about the data rather than a
   gap.** The Friday radar posts from CI because its input
   (`data/favourites.json`) is committed and its source is a live API. This
   list is built from `data/discovery_*.json` and `data/music.db`, both
   gitignored, out of an 85 MB `cache/` that is also not committed — so a
   runner has nothing to read. Making it schedulable means committing ~3 MB of
   discovery files, which is a decision about what `data/` is for and not a
   side effect of wanting a cron. Local until then.

   **The people radar is still deliberately not built**: new releases BY the
   artists on this list, 68 `artist/get` per run, cheaper than the Friday job.
   It would turn 162 names chosen by an unscored ranker into a watchlist, so
   it waits for `--score` to separate the strategies.

**~~A similar-artist baseline.~~** Built 2026-10-22
([adr/D31](docs/adr/D31-the-baseline-is-the-opponent.md)) and it answers
`roadmap.md`'s founding question, or will: `stages/baseline.py`, one cached
request per seed to the ListenBrainz labs endpoint, and it logs into the SAME
`data/shown.json` as the strategies so `rank.py --score` reports both in one
table. Built as an opponent rather than as a report, because a hit rate is only
a comparison if both sides are scored the same way over the same window.

**One third of the guess is now measured, and it was right: the lists barely
overlap.**

| | |
|---|---|
| similar-artist list, unheard | 207 |
| co-appearance list, unheard | 162 |
| in both | **23** — 6.6% of the union |

The shared 23 are mostly contemporary Latin pop reachable both ways (Nicki
Nicole, Ozuna, Sech, Paloma Mami, The Weeknd). The similar list leads with
Röyksopp, Garbage, The Prodigy — plausible, well-known, mostly reachable from
Björk alone. Ours leads with Conociendo Rusia and Los Cojolites.

**The other two thirds — "similarity wins on hit rate, co-appearance wins on
keepers" — are not measured and cannot be yet.** Both sources log; `--score`
will say. The algorithm is pinned in `core.similar.ALGORITHM` and carried in
the cache filename, because ListenBrainz exposes several and a comparison
across two of them measures nothing.

**The ordering was wrong on the first read and is fixed.** ListenBrainz returns
a session co-occurrence COUNT that scales with global listening, not closeness:
Björk's top is 6,682 and Sílvia Pérez Cruz's is 24, a factor of 278, so merging
on the raw maximum ranked "artists ListenBrainz has data about" and put her best
neighbour below Björk's hundredth. Each seed is divided by its own ceiling now
(`affinity`, 0–1), the seed count is a tie-break only, and the raw number stays
beside it as provenance. An opponent weakened by a scale artefact would have
flattered our own list in `--score`.

Run 1 of `similar` in `data/shown.json` used the old order and is left as it
is: the log records what was shown.

## The product

The gap between "a credits database" and "recommends music".

- **~~Profile the watchlist, instead of trusting a play count.~~** Done, and
  documented in [profile.md](docs/profile.md): `core/listens.py`,
  `stages/profile.py` and three floors in `policy.py`, at 100% coverage.

  Two numbers, no ratio — lifetime active months and months in the last 24 —
  which puts 80 artists in `core`, 113 in `lapsed` and names 140 deep artists
  the ListenBrainz ranking never surfaced. Radiohead lands `lapsed` on 73
  lifetime months against 3 recent, confirmed by hand.

  **What is still open**, and it is the half that changes behaviour: nothing
  writes a verdict back into `data/favourites.json`, so the radar still watches
  whatever ListenBrainz ranked. Two things block a clean write, both measured:

  - `emerging` is 2,006 artists, because the currency test scales to a short
    history and three recent months out of three qualifies. Right as a verdict,
    useless as a list. It needs a floor nobody has set.
  - ~~a burst reads as decay.~~ Flagged rather than corrected: `policy.burst`
    marks a lapse whose few recent months were intense (Omar Rodríguez-López, 5
    months and 163 plays), and the "watched but lapsed" line says how many of
    its names are doubtful. Not promoted, because intensity is a third axis —
    every promotion rule tried also promoted Interpol, judged cooled by hand.

  It also has two answers to "how many artists do I watch". 93 entries are
  un-muted but the radar watches **91**, because `favourites.ids_for` keys on
  `qobuz_id` and two pairs share one: `j milo`/`Milo j`, and `Rita Indiana`/
  `Rita Indiana y Los Misterios`. Harmless today — the collapse is silent and
  correct — but a profile that reports per-artist numbers has to pick which
  grain it means, and duplicate spellings are the first thing it should surface.

  The numbers that used to be in this entry came from `listenbrainz_sample.zip`,
  1% of the export, because `load.py` took `sorted(glob)[-1]` and "sample" sorts
  after the real export — so a 2,000-listen sample had been shadowing 190,196 of
  them, and `data/music.db` was built from it. Fixed: one picker,
  `core.listens.newest_export`, chooses by **size**, and both stages use it. The
  store now holds the 190,196 rows store.md always claimed.

  The tracks-against-plays rule in the old text did not survive the full file
  either — every artist sits between 0.50 and 1.0 tracks per play, so it
  discriminates nothing.

- **~~Filter artists who will never release again.~~** Done:
  `./stages/favourites.py --check-active` asks MusicBrainz `life-span.ended`
  per watched artist and stamps `ended` in, which `favourites.ids_for` skips
  alongside `watch: false`. Six of 93 were found — four dead, two split — so
  the Friday radar had been spending six of its 91 requests on artists who
  cannot produce a row. [favourites.md](docs/favourites.md) has them.

  MusicBrainz rather than the release dates, because the obvious test fails on
  exactly these artists: a dead one keeps putting out compilations. What is
  still open is the living artist who never formally stopped and has quietly
  finished — only the release dates can see that, and the radar currently
  fetches every one and then discards it into a bare id list.

- **~~Co-appearance beats the crew graph, and the data is already cached.~~**
  Done 2026-10-20, and it was the right order to do it in — see
  [adr/D14](docs/adr/D14-co-appearance-is-its-own-output.md), which carries the
  full method. `discover.py` labels each album `own` or `guest` from who holds
  `MainArtist`, stamps `own_albums`/`guest_albums` into every person's stats,
  and emits the artists the seed is billed alongside as a `co_artists` block.
  `policy.album_provenance` holds the rule, `core.credits.main_artists` reads
  the billing, and `tests/test_discover.py` is the first coverage that file has
  had (0% → 23%).

  Re-measured over `cache/credits` on 2026-10-20, no requests. 15 of Drexler's
  62 albums and 3 of Pérez Cruz's 44 are not the seed's records, and only 5 of
  those 15 say "feat.", so the titles could never have been the test.

  | | Drexler | Pérez Cruz |
  |---|---|---|
  | MainArtist of a guest album | 10/15 (67%) | 0/3 |
  | co-MainArtist on an own album | 13/23 (57%) | 12/28 (43%) |
  | either — co-appearance | 22/37 (59%) | 12/30 (40%) |
  | the crew graph, all credited people | 36/278 (13%) | 45/287 (16%) |

  Two corrections to the entry this replaces. The baseline is 13-16%, not 7%,
  keyed on the 7,357 distinct `listens.artist_key` in the store — still a 3-4x
  gap, not 6x. And there is a **second direction** it did not count: guests
  billed on the seed's OWN records, 23 and 28 more names at a comparable rate.
  `album_billing` returns both, since both answer "who has this artist made a
  record with".

  Caveat unchanged and still worth keeping: partly circular, since a guest spot
  also exposed you to that record.

  What is still open, and none of it is expensive:

  - ~~**`resolve_qobuz.signal_for` still counts guest albums**~~ Fixed
    2026-10-20: both resolvers prefer the discovery file's `own_albums` and
    flag `unlabelled_albums` where the file predates the labelling, rather than
    falling back silently to the inflated count. **Pending the run** — see "one
    regeneration, three debts" below.
  - ~~**`load.py` has no column** for `provenance`, `own_albums` or
    `co_artists`.~~ Done 2026-10-20
    ([adr/D20](docs/adr/D20-the-funnel-is-queryable.md)): `seeds`,
    `co_artists` and `co_artist_albums` tables, `releases.seed_qobuz_id`,
    `person_albums.provenance`, and both halves of the funnel as queries in
    [store.md](docs/store.md). `co_artists` is still read by nothing that
    recommends — it is now one join away rather than absent.
  - **~~The co-artist list inherits the name problem.~~** Filtered 2026-10-22
    ([adr/D24](docs/adr/D24-a-record-nobody-holds.md)): `policy.NOT_ARTISTS`
    names "Colors", "Penelope Cruz" and Björk's own two bands, with a reason
    each, and `stages/co_artists.py` drops them on read and says on stderr that
    it did. A hand list, because each one is genuinely billed on a track the
    seed is genuinely on — that is every piece of evidence this project
    collects about them.

    **MusicBrainz could do the two bands and cannot be used yet.** It states
    both as `member of band`, on the request `core.musicbrainz` already makes,
    so the data is free — but `normalise` keeps the periods in "K.U.K.L." and
    MusicBrainz files the band as "KUKL". A name key that strips punctuation
    touches every match in the project and wants its own measurement.
  - **`top_role` is order-dependent on a tie.** Found while verifying this
    change was behaviour-preserving, and it predates it: `Counter.most_common(1)`
    breaks a tie by insertion order, so the role depends on the order Qobuz
    returned the discography. `luis eduardo aute` has three roles at 1 each and
    `juan falu` four at 13. A rebuild on a different day can flip it, which
    means the field is not a fact about the person. Pick a tie-break.
  - **~~"Sidonie feat. Dani Martín" is a role.~~** Fixed 2026-10-22:
    `core.credits.split_billing` breaks a token on every joiner Qobuz uses —
    `&`, `feat.`, `feat`, `featuring` — and the positive-evidence rule is
    unchanged, so every side still has to head a segment of the same string.
    6 more tokens and 7 occurrences over the whole cache, all artist names.
    "Sidonie feat. Dani Martín" itself stays a role, correctly: the string
    never names Dani Martín on his own.
  - **~~An artist's name in a role slot, spelled differently.~~** Fixed
    2026-10-22, found by reading the printed list rather than by a test.
    `core.credits.parse_performers` already dropped a packed co-artist name
    that also heads a segment of the same string, but it compared the raw
    tokens, and Qobuz spells one artist two ways inside one string:

        Conrad Taylor, ..., Re-Mixer - Rosalia, MainArtist, ... -
        Conrad Taylor, ROSALÍA, Björk & Yves Tumor, AssociatedPerformer

    So "ROSALÍA" was a role, and reached the page as *"credited on 1 track
    (re-mixer, rosalía, björk & yves tumor)"* — which is the one thing
    [adr/D21](docs/adr/D21-explanations-name-what-the-person-did.md) promised
    an explanation would never say. `names_a_co_artist` now folds both sides
    with `normalise` and splits a token on `&`, since "Björk & Yves Tumor" is
    two heads in one token and no head at all.

    Measured over all of `cache/credits` and `cache/search`: **18 distinct
    tokens, 29 occurrences, every one an artist name** — no instrument, no
    genuine role. It also catches the three the old docstring called
    uncatchable ("Angeles Toledano", "Ruben Blades", "Americo Young"); they
    were never role-slot-only, they head segments spelled with the accents the
    role slot drops. Those tokens were scoring 0.8 as unknown instruments and
    `role_class` was filing them under `performance`.
  - **~~"Liniers" is billed on a Drexler live record.~~** Caught by rule
    2026-10-22 ([adr/D27](docs/adr/D27-the-class-fallback-gets-rules.md)) —
    `policy.billed_as_musician`, 1 of 132 co-artists, and he is off
    `NOT_ARTISTS` again.

    **Worth keeping for the order it happened in.** The rule was tried first
    against `MUSICAL_ROLES` and measured down: it cut Rosie Lowe (Vocalist),
    Yuna (Vocalist), PJ Sin Suela (Rap) and Tosca as well, 5 real features to
    catch 1 illustrator. So he went on the hand list and that was called the
    honest answer. Then "I still see Recording Engineer" turned up the actual
    cause one layer down — the class fallback, filing `Designer` under
    `performance` along with 34 other tokens. **The hand list was standing in
    for a defect somewhere else, and a rule only looks wrong while the data it
    reads is wrong.**
  - **~~The role-class fallback was silent.~~** Fixed 2026-10-22
    ([adr/D27](docs/adr/D27-the-class-fallback-gets-rules.md)): `role_class`
    fell back to `performance` and `role_weight` to 0.8 for anything the table
    does not name, so **35 of the store's 273 role tokens** — `2nd Engineer`,
    `Mix Engineer`, `SoundEngineer`, `CoMixer`, `Art Director`, `Photographer`,
    `Designer` — were performance credits at instrument weight. 577 of 22,019
    rows, 2.6%. `Assistant Mixing Engineer` scored 0.8 against the listed
    `assistant engineer`'s 0.2.

    Marker rules now catch the families, a new `non-musical` class holds the
    sleeve credits, and the instrument fallback is untouched — `Berimbau`,
    `Theremin`, `Vocalist`, `Rap` all still class `performance` at 0.8. Two
    exact table entries exist only to beat a marker (`chorusmaster`,
    `concertmaster`), which ends the old invariant that `performance` was never
    a table value.

    **Still open, and it needs requests: the pool's copy is stale.**
    `releases.via_referral_classes` is a string the resolvers wrote, so the 477
    Qobuz-path rows classed `performance` keep whatever they were given, and
    some pass D15's referral filter only because of this defect. Recomputing
    means re-running `resolve_qobuz.py`. The crew pipeline is paused, so this
    is a known stale column rather than a fixed one.

    **`MUSICAL_ROLES` looked like the same gap one layer down, and measuring
    it said leave it alone.** 2026-10-22, over the ten-seed corpus:

    - the gap is real but **latent: 0 of 2,772 people change verdict**.
      `is_musical` is `any()` over a person's whole role list, and a real
      person holding `Vocalist` almost always holds something the allowlist
      does know.
    - the tail is not three tokens, it is **255** (5,831 credits rows) —
      `Congas`, `Banjo`, `Vibraphone`, `Spanish Guitar`. Adding three would be
      arbitrary; adding 255 rebuilds the allowlist `core/credits.py` measured
      against in the first place.
    - replacing it with `role_class` has two forms and neither is free:
      `!= non-musical` keeps a `FeaturedArtist`-only person who is today
      dropped, and `not in {non-musical, billing}` **drops 165 people**, all
      billing-only.
    - and the comment above `MUSICAL_ROLES` already rejected merging the two
      vocabularies, because `discovery_*.json` and `watchlist.json` carry the
      coarser classes and unifying would change data already written. It calls
      that "a decision to make on purpose, not a side effect of tidying".

    So: not changed. The latent gap is recorded here instead, and the thing
    that would make it worth fixing is a person whose ONLY credit is one of
    the missing tokens. There is none yet.
  - **"WE PRAY" is three album ids on three dates, and that is correct.**
    Checked 2026-10-22 rather than fixed. The single is `k3qvjdv4dc7yb`
    (2024-08-23), `dyo5uicjiqi4a` (2025-02-13) and `j5jjsjkkq0aaa`
    (2025-04-17); all three bill Little Simz, and the later two add Jasleen
    Royal and Twice respectively — Coldplay shipped regional variants with
    different features. `fold_editions` folds inside one person's album list,
    so each co-artist keeps the earliest edition THEY are on, which is why one
    single is dated 2024 for Burna Boy and 2025 for Twice.

    Each count is right and each date is right for its person. What is wrong
    is only that the list prints "WE PRAY" three times and reads as three
    records. Left alone: making the date seed-wide would tell Twice they
    appear on a 2024 record they are not on.

- **The credits pool itself has four defects, all measured 2026-10-18.**

  | | |
  |---|---|
  | 75% of rows are the person's OWN release | 5,862 primary vs 1,998 side credits. The thesis is "they shaped it" |
  | 73% of referrals come through MIXING | 5,347 mixed-by vs 1,678 producer, in the discogs pool |
  | the two pools' scores are not comparable | pool.json has no selectivity and caps at 0.80; pool_discogs reaches 1.00. Ranking them together lets the source decide the top |
  | name collisions are not only single-token | "Alex Cooper", "Sexy Sadie", "Solid Ice" all escape the flag and return electronic pop |

  **The Discogs path is the broken half**: 81% of the rows, 84% of them
  engineering-referred, and every junk row traced to it.

  ~~Those filters are free and none is written down in code yet.~~ Written down
  2026-10-20 — `policy.shortlisted`, `via_referral_classes` and
  `via_is_first_artist` in the store, the query in
  [store.md](docs/store.md), the decision in
  [adr/D15](docs/adr/D15-filters-before-ranking.md). Applied on read, so no row
  is deleted and a wrong filter costs a different WHERE clause.

  **The 148 in this entry was wrong, or its definition was.** Re-measured over
  the same two pool files, which have not been regenerated since: the three
  filters together keep **291 rows**, 220 of them by artists never played.
  Eight compositions were tried and none produced 148; the closest were 291 for
  the stated set and 161 for production-referred only. The genres this entry
  reported for its top (Bolero, Classical) are not in the 291 either, so the
  difference is the definition rather than the data. 291 is what the predicate
  yields and is now the number in `policy.py`, `docs/store.md` and D15.

  Two corrections that came out of writing it down:

  - **The Qobuz path re-matches names too.** This entry said it "takes people
    from Qobuz's own credits with no name re-matched", and `resolve_qobuz.py`
    resolves each name through autosuggest exactly as the Discogs path does.
    426 of the 1,470 Qobuz-native rows carry `single_token_name`, and 72 of the
    291 shortlisted rows do — "Mauro" alone contributes 42. Filtering reduces
    the name problem; it does not escape it.
  - **Excluding the Discogs path is not fixing it.** One clause drops 6,390
    rows, so the thesis now rests on 1,470 from a 59-person fan-out. Fixing
    `build_pool`'s matching is what brings them back.

- **Seeds are cheap once the Discogs path is dropped.** This entry used to say
  growing the graph was expensive; that was measured on the full chain. Sílvia
  Pérez Cruz cost **45 requests** (44 albums + 1 discography) and added 149
  people. `data/discovery_656411.json` exists locally and is gitignored like
  the rest of `data/*.json`, so it is regenerable rather than kept — one
  `./stages/discover.py --artist 656411` rebuilds it, and `cache/credits` makes
  that nearly free. Four more seeds is under a month of the Friday radar's own
  traffic.

  But **graph intersection is thinner than roadmap.md assumes**. Two artists
  from the same scene share 8 of 157 people, 4 after dropping technical roles.
  So "keep people in 3+ graphs" as a hard filter will probably starve. Worse,
  the people most likely to appear in every graph are the industrial services —
  Fred Kevorkian masters 1,070 records and is in both — so an intersection count
  must be multiplied by `selectivity()`, never used raw. A weighted gradient
  needs 4-5 seeds before it has any range.

- **One regeneration, three debts — the Qobuz half is done.** The code
  for all three landed 2026-10-20
  ([adr/D17](docs/adr/D17-fold-plausibility-into-the-score.md)): the match
  penalty folded into `sig_score`, `person_seed_albums` counting only the
  seed's own albums, and both catalogue sizes kept instead of dropped. Nothing
  in `data/` reflects any of it, so `sig_match_confidence` is NULL on all 7,860
  rows and `docs/store.md` still discounts conditionally on that.

  The run, in this order — the order matters, because a discovery file written
  before the own/guest labelling makes every row `unlabelled_albums` and the
  second half of D17 does nothing:

      ./stages/discover.py --artist 41620          # 1 request, albums cached
      ./stages/discover.py --artist 656411         # 1 request
      ./stages/resolve_qobuz.py                    # ~59 artist/get
      ./stages/resolve_discogs.py                  # 128-person fan-out, needs
                                                   #   DISCOGS_TOKEN, cached
      ./stages/load.py                             # free, rebuilds the store

  **Run 2026-10-20, except the Discogs line** — no token yet, so 6,390 of the
  7,886 rows still carry the old scores and the `sig_match_confidence IS NULL`
  branch in `docs/store.md` stays until they are rebuilt. The Qobuz half came
  out clean: 1,496 releases from 57 artists, no row flagged
  `unlabelled_albums`.

  Two results, both recorded in
  [adr/D17](docs/adr/D17-fold-plausibility-into-the-score.md):

  - **Five referrers were pure artefacts of the guest-spot leak.** 10 of 50
    lost albums and five went to zero own albums — Chab, Susana San José, El
    David Aguilar, Ulises Hadjis, Çantamarta — so they now score 0.0. They
    never worked on a Drexler record; they are people he was billed alongside,
    which is what `co_artists` is for. ~~**Open question this raises:** a
    referrer at score 0 still contributes every row of their discography to the
    pool.~~ Decided and done
    ([adr/D18](docs/adr/D18-drop-score-zero-referrals.md)): dropped on read by
    `policy.carries_signal`, and `--min-albums` now counts the seed's own
    albums so the resolver stops spending a lookup and a discography on them —
    110 people instead of 122, 12 of the 57 fetched artists. The 175 rows stay
    in the pool until the next regeneration, which is what the read filter is
    for.
  - **Catalogue size does not discriminate**, so that hypothesis is refused for
    the Qobuz path: flagged people hold 4-309 albums, unflagged hold 1-483.
    Caetano Veloso holds 483 and is correct; "Calequi" holds 4 and is flagged.
    The test the argument actually wanted is a *comparison* of the matched
    catalogue against the credit count, and only the Discogs path has both
    numbers. Still blocked on the token, not on the idea.

- **A radar for people, not artists.** The thesis, and the one thing this cannot
  do: alert on records made by *people* you follow. The pools hold 7,860
  candidate releases and nothing consumes them. One `album/get` per fresh
  release, cached.

  Costed since: **68 `artist/get` per run** for the 68 people in the graph
  carrying a Qobuz id, against the 91 the Friday radar already makes. Cheap.
  Blocked on the pool being trustworthy, not on the budget — see Correctness.
  It also lags by construction, because credits are often registered days
  after a release.

- **A ranker.** 7,860 candidates, each with an explainable `via.signal.score`,
  and no order.

  Do not build this yet. `sig_score` currently ranks the name collisions
  FIRST: "Morgan" carries 323 releases at a score of 1.0, the maximum. Ordering
  a list whose top is wrong makes the wrongness more prominent, not less.
  Filtering comes first.

  Filtering is now done ([adr/D15](docs/adr/D15-filters-before-ranking.md)), and
  ~~the next decision is a cap per referrer~~ that is done too
  ([adr/D16](docs/adr/D16-cap-the-list-per-referrer.md)): `MAX_PER_REFERRER = 2`,
  which takes the 212 shortlisted rows to 38 across all 24 referrers and puts 12
  distinct people in the top 20, where uncapped the first rows were nine Juan
  Campodónico records.

  Note the key: **`via_name`, not `via_through`.** This file and `store.md` both
  said `via_through`, which is NULL on all 1,470 Qobuz-path rows — only the
  Discogs path writes it — so capping on it would have put the whole shortlist in
  one group. A test pins it.

  What a ranker would still have to add on top, and why it is still not next: the
  cap hides the concentration rather than fixing it. 24 referrers for 212 rows is
  the real number, and what widens it is more seeds or the Discogs path repaired
  instead of excluded.
- **Album identity.** `core/radar.Release` now normalises what the radars
  report, but it is a *reporting* record keyed on each store's own id: two
  editions of one album are still two rows, and nothing reconciles a Qobuz id
  with an MBID. The pools are untouched by it. See
  [architecture.md](docs/architecture.md).
- **Record what you played.** The weekly issue is already a dated log of what
  was *shown*; the other half is missing, and without it the evaluation in
  [roadmap.md](docs/roadmap.md) has nothing to score.
- **Unify the role-class vocabularies.** `discover.py` folds engineering into
  `production`, `resolve_discogs.py` splits it out. Both live in `policy.py`;
  unifying them rewrites `classes` in existing data.

## Correctness

Where the code can be wrong without anything noticing.

- **Three identity defects, found by the 2026-10-20 probe.** All free to fix,
  all invisible until a seed outside the Iberian cluster was walked, and
  together they corrupt every co-appearance and crew count. Numbers and the
  per-seed table are in
  [adr/D22](docs/adr/D22-co-appearance-is-the-second-pipeline.md). **All three
  are fixed** — two by D23, the collaborator aliases by D25.

  A fourth was found while filtering the list on 2026-10-22 and is fixed in the
  same place: **a record nobody holds read as 20 guest spots**
  ([adr/D24](docs/adr/D24-a-record-nobody-holds.md)). It belongs with these
  because it is the same kind of error — a count asserting a relationship that
  is not there — and it was the largest of the four by volume.

  - **~~The seed is credited under a legal name.~~** Fixed 2026-10-20
    ([adr/D23](docs/adr/D23-ask-musicbrainz-who-the-seed-is.md)): MusicBrainz
    is asked which names the seed is credited under — aliases, sort-name and
    the far side of an `is person` relationship — one cached request per seed,
    with the mbid off `favourites.json`. Björk's own graph now tops at Nellee
    Hooper instead of herself.

    Both cheaper tests were measured and failed, which is why this went to an
    external source: a share threshold puts Little Simz's legal name at 45%
    against a real producer at 42%, and NEITHER legal name holds `MainArtist`
    — both are filed as Composer, exactly like Sjón and Inflo.

    **Residue:** "Simbiatu Abisola Abiola Ajikawo" (5 albums) and "Simbi
    Ajikawo" (4) are in no MusicBrainz field, so 9 of her 29 self-credits
    survive. `discover.py` prints a CHECK line when the top person holds half
    the catalogue, which catches a Björk-sized residue and not a 5-album one.
    The real fix is an edit at MusicBrainz.

  - **~~One person splits across names, and it hits the best collaborators.~~**
    Fixed 2026-10-22 ([adr/D25](docs/adr/D25-one-person-one-key.md)). Sjón was
    four people at ranks 4, 6, 8 and 68; he is now **30 albums at rank 1** of
    Björk's graph. Arca is 15 at rank 4, Inflo **14 at rank 1** of Little
    Simz's, Carles Campi Campón 22 over two seeds. 851 people across the four
    files, down from 892.

    `data/aliases.json` is hand-edited, like `favourites.json` and for the same
    reason, and `core.aliases.person_key` is now the only way a person key is
    minted. Both cheaper sources were measured and failed: of the top 12 people
    across all four seeds, **1 of 48 has an MBID anywhere on disk**, so asking
    MusicBrainz would mean a fuzzy search by name at a request each — and the
    free signal that looked sufficient (a performing name and a legal name
    co-credited on one track in complementary roles) holds for Arca and Inflo
    and fails outright for Sjón, who is never co-credited with himself.

    **It does not generalise, and the report is what makes that cheap.**
    `discover.py` ends a walk by printing the pairs it did NOT merge —
    `subset`, `spelling`, and `bare` for a single surname like "Massey" or
    "Glennie", which is right often enough to read and wrong often enough that
    nothing may act on it. 19 of the 48 candidates are in that class and are
    deliberately left alone. Two are a person and the band named after them
    ("Calequi y Las Panteras", "Javier Colina Trío") and are not reported at
    all, because merging them would delete a billable act.

    Still invisible: a split with no shared spelling. Nothing relates "NELLEE
    HOOPER" to "N. Hills" in Björk's graph, and nothing will until somebody
    confirms it by hand.

    Two correctness fixes the merge forced, both in D25: a track's credits are
    collapsed by person **before** anything is counted (Inflo holds Producer
    and his legal name Composer on 37 of the same tracks, so the merge would
    otherwise have double-counted every one of them), and `watchlist.json`
    stopped being a second source for `person_albums`, whose primary key rested
    on a derived file agreeing with the one it was derived from.

  - **~~Editions inflate every count.~~** Fixed for co-appearance 2026-10-20
    (`discover.fold_editions`, same ADR): folded on `normalise(title)`, since
    Qobuz returns no release-group id here. Coldplay, Burna Boy, Elyanna and
    tINI went from 5 co-appearances each to 1, and Obongjayar correctly kept 2.

    Two things this does not do. It merges genuine reissues — "Granada" is in
    the Pérez Cruz corpus at 15 tracks and 21 — which is right for counting who
    made records together and wrong for anything needing a track list. And the
    pools are untouched: `releases` still holds one row per edition, which is
    the "Album identity" entry below.

  A fourth, subtler: `policy.album_provenance` assumes one `MainArtist` per
  record, so "WE PRAY" reads as Little Simz's OWN record because she is billed
  on it. True in a cantautor catalogue, false in a features culture, and it
  means `own` stops meaning "the seed's record" on exactly the records where
  several artists share a billing.

- **~~One seed's numbers overwrote another's in `people`.~~** Fixed 2026-10-20
  ([adr/D19](docs/adr/D19-person-seed-is-the-grain.md)). `load_people` called
  `row.update()` per `discovery_*.json`, so the last file won: Fred Kevorkian's
  13 Drexler albums became the 1 from a Pérez Cruz record. 14 of 551 people are
  in both files and all 14 carried the wrong seed's numbers.

  A grain mismatch rather than a merge bug — "albums" is a fact about a
  (person, seed) pair and was stored one row per person. `person_seeds` now
  holds it at that grain, `people.albums`/`own_albums`/`tracks` are summed with
  `people.seeds` saying over how many, and `watchlist.json` stays first-wins
  because it is derived from a discovery file and would double its own seed.

  Nothing scored from that column, which is why no score moved. That was luck:
  `signal_for` reads the discovery file directly. The table is fixed before
  anything starts ranking from the store.

- **Nearly half the candidate pool is name collisions, and the score promotes
  them.** The most important open defect, and the reason nothing credits-based
  should be built yet. Measured 2026-10-17 on the committed pools:

  | | |
  |---|---|
  | `single_token_name` flagged | **3,673 of 7,860 rows (47%)** |
  | top 6 contributors | 1,887 rows (24% of the pool) |

  | via | rows | score | how it got in |
  |---|---|---|---|
  | Henry Mancini | 459 | 0.105 | via José María Rosillo |
  | Morgan | 323 | **1.00** | via Carles Campi Campón |
  | Arcángel | 309 | 0.18 | via Bori Alarcón |
  | Mama | 291 | 0.105 | via José María Rosillo |
  | Cooper | 261 | 0.21 | via José María Rosillo |
  | Francisco | 244 | 0.18 | via Bori Alarcón |

  Henry Mancini is the clearest: the releases reached through him are the
  *Peter Gunn* soundtracks, 1958-60. Rosillo is a Spanish engineer who worked
  on Drexler records and did not work on Peter Gunn. The others — "Morgan",
  "Mama", "Cooper", "Francisco" — are generic single tokens.

  The mechanism is `build_pool` in `stages/resolve_discogs.py`: it takes a
  collaborator NAME off a Discogs credit row and exact-matches it in Qobuz.
  "Cooper" exact-matches a real Qobuz artist — just not the right one — and
  that artist's whole discography enters the pool. `find_artist` refuses fuzzy
  matches precisely to avoid this, but an exact match on one common token is
  indistinguishable from a correct one at that layer: the name is all the
  evidence there is.

  Worse than the volume is the SCORE. "Morgan" sits at 1.0, the maximum,
  because the referring person is a selective producer and the signal is
  computed from the REFERRER, never from how plausible the match itself is.
  So the junk is not merely present, it is ranked first.

  What would fix it, in rough order of how much it buys:

  - drop or heavily penalise `single_token_name` — 47% of rows, and the flag
    already exists and is already stored. One judgement call in `policy.py`.
  - require more than a bare exact match for a single-token name: an album
    count, an overlap with the referrer's own catalogue, or a genre that is not
    a mid-century film score.
  - ~~fold match plausibility into `sig_score`, so a shaky resolve cannot
    inherit a strong referrer's weight.~~ Done in the resolvers 2026-10-20
    ([adr/D17](docs/adr/D17-fold-plausibility-into-the-score.md)), together
    with the two other debts that needed the same regeneration. **Pending the
    run** — see "one regeneration, three debts" below.

  All free — no requests. This is the "filters instead of ranking" row in
  [roadmap.md](docs/roadmap.md), and it reads as a nice-to-have there; the
  numbers above make it the prerequisite. The stance taken so far — penalise on
  read, do not drop — is [adr/D13](docs/adr/D13-match-plausibility-on-read.md),
  which also names what folding it into `sig_score` would cost.

- **~~`policy.py` and `core/credits.py` are untested.~~** Done: both at 100%,
  94 cases in `tests/test_policy.py` and `tests/test_credits.py`. The three
  disagreeing role vocabularies are now pinned against each other, so unifying
  them fails a test rather than quietly rewriting a column of existing data.

- **Two files are still at zero coverage.** Overall 34% → 67%. Done:
  `core/discogs.py`, `radars/itunes.py` and `radars/listenbrainz.py` at 100%,
  `stages/load.py` 99%, `stages/writing.py` 55%,
  `stages/resolve_discogs.py` 28%.

  Still at 0%: **`stages/discover.py`** (121 statements) and
  **`stages/resolve_qobuz.py`** (112). They are the same shape as the two below
  — one long `main()` with the decisions wedged between a fetch and a print —
  so they want the same treatment: extract, then test. `discover.py` is the
  more valuable of the two, being the stage the whole credit graph comes out
  of. `radars/remezcla.py` is at 41% and is the other soft spot.

  The last two needed their decisions extracted before they could be tested at
  all, which is done: `classify_rows`, `flag_album_wide_credits`, `fold_songs`
  and `pages_needed` in `writing.py`; `gate_verdict`, `select_targets`,
  `signal_of`, `known_totals` and `role_census` in `resolve_discogs.py`. All
  pure, all tested, and the refactor is verified behaviour-preserving —
  `writing.py` reproduces the committed `writing_jorge-drexler.json` byte for
  byte from `cache/` alone, and both of `resolve_discogs.py`'s offline modes
  print identical output.

  What is still uncovered in those two is the orchestration: `main()`,
  `build_pool()` and the fetch-and-print middle of `run_one()`. That is now
  what those functions ARE, the decisions having moved out. Covering them means
  stubbing Discogs plus the filesystem and asserting on printed output, which
  buys much less than the 110 decision tests did — worth doing when
  `build_pool` next changes, not before.

- **`collapse()` never merges two titles of the same length.** Found while
  testing it. The fuzzy pass skips any candidate that is not *strictly* longer
  (`len(other) <= len(target)`), so equal-length spellings never meet however
  similar they are. `writing.py`'s own docstring offers "orcuridad" as a caught
  typo and it is exactly this case: 24 characters against 24, similarity 0.958
  against a 0.92 floor, no merge.

  Not a one-line fix, which is why it is recorded rather than done: choosing a
  canonical form between two equal-length keys is a new decision (first seen?
  alphabetical? most frequent?), and the longest-wins rule exists so the fuller
  title survives. A test states the current behaviour so the choice is
  deliberate when it is made.

- **~~No indexes in `data/music.db`.~~** Done: 30 of them, created after the
  bulk load so the rebuild stays under a second. Every join and filter in
  [store.md](docs/store.md) now uses one instead of scanning the table. It was
  45 until the primary keys went on and subsumed 15 — see that entry below.

- **~~The loader inserted duplicate rows.~~** Fixed. `load_people` assembles
  six junction tables by appending from several files, and only three went
  through a dedup; all six now go through one `deduped()` helper.
  `person_roles` 923 → 722, `person_albums` 777 → 563, and all six are now
  distinct on the full tuple.

  `dict.fromkeys`, not the obvious `sorted(set(...))`, and that is not a style
  choice — sorting these tuples *raises*. They carry `None` wherever a source
  file omits a column (an album with no date, an edge with no release count,
  and `n`, which is `None` for `watchlist.json`'s bare-list role form and an
  int everywhere else), and Python will not compare `None` with `str` or `int`.
  The fix that looks right turns a silently duplicated row into a failed build.

- **~~No primary keys in `data/music.db`.~~** Done: 15 of the 21 tables carry
  one, and the build got *faster* — 0.77s to 0.23s — because a key is itself a
  unique index, so 15 single-column indexes it now subsumes were dropped (45
  indexes to 30).

  `Loader.insert` turns a violation into a message naming the table and the
  offending row, because sqlite's own wording names the constraint and not the
  row, and a 216k-row build is not a place to go looking.

  Six tables have no key, each for a stated reason rather than by omission:

  | | |
  |---|---|
  | `person_roles` | needs a merge decision, not a constraint: 722 rows against 612 distinct `(person_key, role)`, because the same role arrives with a count from one file and `NULL` from another. Ruling that a count beats an absence is source precedence |
  | `song_performers` | `album_title` is NULL *by design* — `load_songs` iterates `perf["albums"] or [None]`. Today's corpus has an album for every performer, which is not the same as the column being non-null |
  | `tracks`, `credits` | still genuinely duplicated (910/906 and 11,926/9,516). The duplicates are inside the cached pages, so deduping means deciding which cached copy wins — a question about the corpus |
  | `listens`, `meta` | no natural key. `listens` is an append-only log and `listened_at` is nullable |

  Two caveats worth keeping, both now in tests:

  - SQLite will not say this: in a rowid table a PK column may still be NULL,
    and NULLs count as distinct. Each key protects rows whose key columns are
    all present — all of them today — and silently protects nothing on a row
    where a source file omitted a field. This is also where the engines
    diverge: DuckDB follows the standard and refuses NULL in a key, so a
    `song_performers` key would build under sqlite and fail under duckdb.
  - ~~`person_albums (person_key, album_id)` rests on an empirical fact, not a
    structural one.~~ **It broke, on the sixth seed.** Fixed 2026-10-22
    ([adr/D28](docs/adr/D28-an-album-is-per-person-seed.md)): the key is
    `(seed_qobuz_id, person_key, album_id)` now, because `provenance` is a fact
    about (album, SEED) — "Oral (Olof Dreijer Remix)" is Björk's own record and
    a guest spot for ROSALÍA, and Noah Goldstein and Sega Bodega are credited
    on it in both walks. 2 pairs disagreed and `provenance` was the only field
    that did, in both. D19's grain argument reaching the one table it missed.

    Worth remembering how it surfaced: the build stopped, which was the right
    failure, but `load.py` unlinks the store before building, so **the previous
    store was already gone** and nothing was queryable until the key was fixed.
    A loud failure that takes the last good artefact with it is louder than
    intended.

- **~~Two hand-rolled retry loops are left.~~** Done: both deleted.
  `stages/writing.py` goes through `core.qobuz.get_json` now, so the adapter's
  jitter and `Retry-After` apply, and the "5xx after 3 tries" warning went
  with the loop that produced it.
- **~~A weaker copy of the autosuggest is left.~~** Done, and it was hiding a
  real defect. `qobuz_find_artist` is replaced by `core.qobuz.find_artist`,
  which reports `ambiguous`, keeps `error` apart from `not_found`, and tries
  **every** spelling — which matters more than it sounds: those names come
  straight out of Discogs credit rows, so `"Valeria Castro*"` and `"Mauro (5)"`
  were being matched verbatim and failing. `search_artists` keeps its lossy
  shape for the two interactive callers. `stages/resolve_qobuz.py:140` still
  has the old blindness — a one-line change whenever that stage next matters.

## Infrastructure

- **~~Nowhere durable to keep state.~~** Done. `core/radar.py` takes
  `--state PATH`, and `radar.yml` derives `data/ci/<radar>_seen.json`, runs
  against it, and commits it back — so the Friday radar is stateful and the git
  history of that file is a dated log of what was actually reported, which is
  the impression data [roadmap.md](docs/roadmap.md) needs before anything can
  be evaluated. `stateless: true` remains for a backfill.

  Four things that are load-bearing rather than incidental, recorded so nobody
  "tidies" them:

  - **`data/ci/`, not `data/<radar>_seen.json`.** The reason that file is
    gitignored still holds: a runner's "already reported" must not arrive on a
    laptop and silence the radar there. `.gitignore` un-ignores this directory
    alone.
  - **The record step runs AFTER the issue is opened.** If the issue fails and
    the ids are already recorded, that week's releases are marked seen and
    appear in no issue at all. Losing state costs one duplicate; losing the
    issue costs the week.
  - **The caller needs `contents: write` too.** A called workflow can never
    hold more permission than its caller grants, so leaving
    `releases-known-artists.yml` at `read` makes only the push 403 while every
    other step succeeds — the quietest possible way to lose the state.
  - **`concurrency` is queued, not cancelled.** Two runs racing means the
    loser's push is rejected; a cancelled radar run is a missed week.

  Expect the first stateful commit to be large (~136 KB): `record_scanned` is
  True for Qobuz, so a run records every id it *scanned*, not just what it
  reported — which is what stops an old release resurfacing the week it falls
  out of the date window. Later commits are small.

- **Nothing ever calls the real APIs except the Friday job.** The suite stubs
  every network call at the seam, which is correct — it is why the tests are
  offline, fast and free. The cost is that a *source* changing shape is
  invisible: Qobuz renaming a field, Apple dropping `releaseDate`, Discogs
  changing its pagination. Every test still passes, and the first anyone knows
  is a Friday issue that is empty or wrong.

  A canary closes it: one scheduled job that calls each source for real,
  asserts the handful of fields the radars actually read, and opens an issue
  when one is missing. `--dry-run` already exists on all three radars, so this
  is a caller plus a small assertion script, not new machinery. Under an hour,
  and it protects the only part of this that runs unattended.

  Deliberately separate from `tests.yml`: a canary fails when a third party
  changes something, which is news but not a broken commit, and wiring it into
  the commit checks would make every push red for a reason nobody pushed.

## Build and CI

~~Each of these is under an hour, and each is something a reviewer would
expect.~~ The original six are done. Two more have since become worth having,
both still under an hour.

- **The `ruff-format` pre-commit hook can never pass.** It runs with `--diff`,
  which exits non-zero whenever a diff exists, and `policy.py`'s aligned columns
  are deliberate — so it fails on the committed `policy.py`, on main, with no
  changes at all. The hook was installed into `.git/hooks` on 2026-10-18 and
  blocked the first commit that hit it. Either exclude `policy.py` and
  `stages/load.py`, or drop the hook and let `ruff check` gate alone.

- **No vulnerability scanning.** `dependabot.yml` bumps versions; it does not
  know which of them are vulnerable. `pip-audit` against the two lockfiles is
  one step and answers a different question.

- **No required status check on `main`.** There is no branch protection at all
  (the API returns 404). `tests.yml` says advisory-on-purpose, and at 76 tests
  that was reasonable; at 493 with `ruff` and `ty` gating as well, requiring
  the check on pull requests costs nothing and stops a red merge.

  Separately, and this is the sharper lesson: a `todo.md` conflict between two
  merged PRs was resolved in favour of the older text, silently reverting a
  correction. Branch protection would not have caught that. What would: either
  stop editing `todo.md` in every branch, or give it a union merge driver in
  `.gitattributes` so both sides survive a conflict instead of one winning.

- **~~No type checker.~~** `ty`, in the dev extra and a `tests.yml` step,
  configured in `pyproject.toml` so `ty check` means the same on a laptop.
  Clean now, and it found two real things on its first run: `radars/qobuz.py`
  overrode `add_arguments(self, ap)` against a base taking `parser`, so a
  keyword call broke on that one subclass, and `radars/remezcla.py` called
  `find(attrs=...)` in a form bs4's own overloads reject. Both fixed. The only
  rule suppressed in source is `unresolved-import`, for the optional `duckdb`
  that `stages/load.py` already guards with `try/except ImportError`.
- **~~No lockfile.~~** Two, hashed and universal, resolved for the 3.11 floor
  so one file serves the whole matrix: `requirements.lock` for the radar's
  runtime and `requirements-dev.lock` for CI. Installed with
  `--require-hashes`, then the project with `--no-deps` so the lock stays
  authoritative. A test-only package can no longer break the Friday job,
  because it is not in that job's environment at all.
- **~~No `pre-commit`.~~** `.pre-commit-config.yaml`, pinned to a rev.
  `ruff-format` is `--diff` only, never a rewrite: the aligned columns in
  `policy.py` and the comment-per-value `SCHEMA` in `load.py` are deliberate.
  `pytest` and `ty` stay out of it — both read the whole project, and a hook
  that runs the suite is a hook people pass `--no-verify` to, which costs the
  lint checks as well.
- **~~Actions float on major tags.~~** All three pinned to SHAs in both
  workflows, with `.github/dependabot.yml` bumping actions and pip weekly on
  Monday — grouped so a lint bump never blocks a security bump to `requests`.
- **~~No coverage measurement.~~** `pytest --cov`, into the job summary rather
  than a service, and no `fail_under` — the useful signal is per-file, and a
  global percentage averages `load.py` together with `policy.py` until neither
  means anything. It paid for itself immediately: see the zero-coverage entry
  under Correctness.
- **~~Only one Python version is tested.~~** 3.11, 3.12 and 3.13, with
  `fail-fast: false`. The floor is a tested fact now.

## Smaller things

- **Resolve Apple ids.** Every `itunes_id` in `favourites.json` is null, so
  `radars/itunes.py` falls back to its built-in list of one artist. It has
  everything else it needs since `core/radar.py` — `--json`, the broken-run
  guard — so scheduling it is a fifteen-line caller against `radar.yml`. The
  ids are the only thing missing.
- **Decide the storefront.** `gb-en` is the default and the watchlist leans
  Latin and Iberian; `--store es-es` is a different catalogue, not a different
  view of one.
- **Cross-check coverage.** `./radars/listenbrainz.py --days 20 --dry-run` reads
  a second source for the same 89 artists; anything it names that Qobuz missed
  is a gap nothing else would reveal.
- **"Who else recorded this song" is thinner than it sounds.**
  [roadmap.md](docs/roadmap.md) lists it as working exactly, today, and the
  lookup does work — but only **26 of 257 songs (10%)** have two or more other
  non-mill recordings. One song has 19 performers and one has 16; the long tail
  has one each. Worth building as a lookup, not as a feature anyone would
  notice. Measured 2026-10-17.
- **`--review` cannot re-ask about a row that resolved `exact`.** A wrong id
  that looked confident can only be fixed by editing the JSON.
- **~~`README.md` says `65 cases`.~~** It says 551, which is what it is. Worth
  a glance whenever a batch of tests lands — it has been wrong twice now.

## Not yet, on purpose

Recorded so the deferral is a decision rather than an oversight.

| | until |
|---|---|
| an orchestrator — Dagster, Prefect, Airflow | pipeline #3 exists. Two scripts and a `Makefile` do not need a scheduler with a UI |
| Postgres | the ranker needs feedback state — dismissed, played, rated. That state is what defines the schema, so building it first means guessing |
| backing up `cache/` | it is needed. Decided 2026-10-17: the 84 MB is `cache/remezcla`, raw HTML of a blog that is still online and re-scrapable, and the part that carries real weight is 650 KB across `cache/credits` (63 albums) and `cache/search` (10 pages) — refetchable in under a minute of requests. The exposure is a re-run, not a lost corpus, so it is cheaper to refetch when relevant than to maintain a sync. The one thing a refetch cannot recover is a credit Qobuz has since edited or removed; `writing.py`'s cache is what makes its output reproducible, so if that output ever needs to be defended rather than regenerated, copy the 650 KB first |
| object storage, `UPath`, R2 | `cache/` outgrows a laptop, which at 85 MB it has not |
| `pipelines/<name>/` layout | `stages/` becomes a junk drawer. With the credits chain paused, it will not soon |
| a source registry, structured logging | the second and third radar are actually scheduled |
