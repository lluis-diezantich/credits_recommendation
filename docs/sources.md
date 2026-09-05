# Additional sources of music discovery signals

A running list. One row per source, grouped by the mechanism it feeds, because a
source is only worth adding if it feeds a mechanism `README.md` does not already
have.

Three sources are structured enough to build on directly, and are worth more
than everything below them combined. Two carry identifiers; the third carries
only names, but is the only thing that has ever reached the bottom of the long
tail. The rest is prose needing an extraction step, or a manual once-a-year job.
Notes beginning **tested** were reached live on the date given — every other row
is unverified.

## Primary — structured and proven

| mechanism | source | notes |
|---|---|---|
| radio rotation | KEXP `api.kexp.org/v2/` — `El Sonido` is program id 2 | tested 2026-09-04: keyless, live. Up to 4 MB ids per play (`track_id`, `recording_id`, `release_id`, `release_group_id`) plus `artist_ids` and `label_ids`, and a DJ `comment` (123/167 populated) that often carries a Bandcamp link. Gotchas: `?program=` and `?show=` are silently ignored — page `/shows/`, match `program_name` client-side, then pull `/plays/?airdate_after=…&airdate_before=…` and filter on `play["show"]`. Specialty shows are metadata-poor: El Sonido had 0/45 labels, 0/45 `track_id`, 35/45 with any MB id |
| radio rotation | NTS Radio `nts.live/api/v2/` | tested 2026-09-04: keyless. Episode tracklists carry `isrc_id` (64/139), `deezer_track_id` (58/139), `musicbrainz_track_id` (33/139), `acr_id` (67/139) — **a Deezer id beside an ISRC in one object is the crosswalk, no name matching needed**. Shows are tagged `location_long`, `genres`, `moods`. Caveat: London-centric — 60 shows paged, zero in Latin America or Iberia (London 20, NY 8, LA 7, Lisbon 2) |
| curator playlists | Songmess podcast — `feeds.soundcloud.com/users/soundcloud:users:58483165/sounds.rss` | tested 2026-09-05: keyless, 500 items in feed, 672 episodes, latest 2026-07-21. Episode `<description>` carries the full playlist as `Artist - "Title"`, so it parses without NLP. One artist or label per episode, plus guest-critic playlists (Javier Rodríguez-Camacho, Doble R). **The only source that reached weed420** (170 Deezer fans, no MusicBrainz entry, empty Deezer `/related`): Ep. 551 on 2024-04-23, ~28 months before it surfaced by other means, then Ep. 622 and Ep. 655. Trade-off: no identifiers at all, names only. The feed caps at 500 items so early episodes fall off — archive it if the back catalogue matters |

## Secondary — reachable, but no identifiers

| mechanism | source | notes |
|---|---|---|
| catalogue + ISRC | Bandcamp `bandcamp.com/tag/<place>`, location discover, `bcsearch_public_api` autocomplete | tested 2026-09-04: catalogue holds the music its editorial ignores. Present: Bandalos Chinos, Silvestre y La Naranja, Joan Colomo, Antònia Font. Absent: Jorge Drexler, Disco Bahía — the catalogue is self-released and small-label only |
| scene documentation | Bandcamp Daily `Scene Report`, `Album of the Day`, `Essential Releases`, `Label Profile`, `Big Ups` | tested 2026-09-04: `daily.bandcamp.com/feed`, no auth, ~2-3 posts/day. `<category>` is a structured RSS field so routing needs no NLP; `Album of the Day` titles parse as `Artist, "Album"`. Zero Spanish-language items in 37 — the editorial does not cover Latin indie |
| per-country charts | Last.fm `geo.getTopArtists` | free key, returns MBIDs. `country=` Argentina / Uruguay / Mexico / Chile turns a chart endpoint into a scene tool. Not tested live - no key obtained |
| genre / scene taxonomy | Every Noise at Once | tested 2026-09-04: still serving (2.5MB static page). Best scene vocabulary there is, but built on Spotify data and its maintainer left Spotify in 2023 — taxonomy excellent, freshness suspect |
| richer genre than `genre` | Discogs `styles` and user lists | credentials already in the project. `styles` is finer-grained than the `genre` string currently copied, at no new auth cost |
| editorial prose | Indie Hoy (AR), Mondo Sonoro (ES), Enderrock (CAT), Remezcla, Sounds and Colours, The Quietus | tested 2026-09-04: all six RSS, all 200. Most are WordPress, so `/wp-json/wp/v2/posts` gives a paginated JSON API with categories and tags rather than a 10-item RSS window (confirmed on ibero909.fm). Enderrock is the only source here touching the ~5,300 Catalan-language plays in the top 25. All of it is prose — park until the crosswalk exists |
| item-item similarity | Reddit — r/ifyoulikeblank, r/MusicRecommendations, r/listentothis, r/MusicaEnEspanol, r/argentina, r/RepublicadeChile | needs an OAuth app: unauthenticated `.json` is 403 and PullPush is unusable. `[IIL] X [WEWIL]?` titles are semi-structured and therefore parseable. Where the Latin scene actually gets discussed - r/argentina and r/RepublicadeChile carried Bandalos Chinos, Silvestre y La Naranja and Disco Bahía. Entirely unverified |

## Manual — no API, but cheap and high-value

| mechanism | source | notes |
|---|---|---|
| shared bills | Vive Latino, Ceremonia, Corona Capital (MX), Estéreo Picnic (CO), Fauna Primavera (CL), Primavera Sound Buenos Aires / São Paulo, Cosquín Rock, Montevideo Rock; Primavera Sound, Sónar, Vida, Canet Rock (Barcelona) | no API exists anywhere, and layouts change yearly so a scraper would rot. ~100 names once a year per festival - copy-paste beats scraping. Two acts on one lineup is a human-curated, geographically anchored scene edge |
| shared bills | setlist.fm API | tested 2026-09-04: 403 without a key; free key on request. Tour-level rather than festival-level; support acts are the high-signal part |
| scene canon (archive) | Club Fonograma | closed around 2015, so an archive rather than a feed - but it defined the indie-latino canon of 2008-2015, the scene Disco Bahía descends from. A one-time seed list, worth more than most live sources here |

## Tried, no access — do not re-propose

| source | why |
|---|---|
| Ibero 90.9, Radiónica, Reactor 105, Emisora del Sur, Rock&Pop, iCat, RNE Radio 3 | no playlist API surface found 2026-09-04. Ibero's WordPress REST serves articles not plays and `/playlist/` is a JS shell; `api.rtve.es` 404s on every guessed path; iCat did not resolve. Station play logs are rare and Anglophone |
| NPR `Alt.Latino` | feed is `feeds.npr.org/128334429/rss.xml`, but dormant — newest item Aug 2023, and episodes carry no tracklist, only prose |
| AOTY (albumoftheyear.org) | 403, anti-bot |
| Pitchfork RSS | old review feed 404s after the Condé Nast restructure; findable but not where it was |
| RateYourMusic | best genre taxonomy anywhere, no API, blocks scrapers hard |
| PullPush (Reddit archive) | 429'd for 20 straight probes over an hour and never recovered. Fine for a handful of spot-checks, not an ingest path |
| BBC 6 Music | `/programmes/*.json` answers but returns programme metadata, not playlists |
