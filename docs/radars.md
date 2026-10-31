# Radars

A radar answers one question — *what came out that I have not been told about?*
— against one source, and reports it the same way whatever the source is.

Four of the five are thin sources over a shared run in `core/radar.py`. Adding
another id-based source is a class with two methods and a fifteen-line workflow
caller. This file is what you need to write one.

> `docs/architecture.md` planned a rename, `radars/` → `sources/`. That doc is
> on the `ranking` branch now (D41) and the rename has not happened; with the
> radars being all that main runs, it is less likely to.

## The split

| | |
|---|---|
| `core/radar.py` | the run: seen-diff, date window, within-run dedup, broken-run guard, `--all`, `--dry-run`, `--json`, `--run-log`, the state write, the exit code |
| `radars/<source>.py` | where the ids come from, how to fetch, how to turn one of the source's rows into a `Release`, and its own vocabulary for warnings |

The split is drawn where it is because of what went wrong before it existed.
Four scripts had grown the same `main()` by copy, and they drifted on the parts
that matter rather than the parts that do not: `radars/qobuz.py` learned that
nothing from anybody is a *broken* run rather than a quiet week, and
`radars/itunes.py` never did — so an Apple outage reported "Nothing new." and
looked correct, every week. Only `qobuz` grew `--json`, so only `qobuz` could
be formatted by `report.py` and posted as an issue.

So the gain is not line count. It is that a lesson learned in one radar is from
now on learned by all of them.

## The contract

Two methods are required. Everything else has a default that is the behaviour
the three migrated radars already had.

```python
class ItunesRadar(Radar):
    name = "itunes"                    # also names data/<name>_seen.json
    pause = 0.5                        # seconds between calls
    default_days = 90

    def watching(self) -> dict:        # {id: label}; empty exits with a message
        return WATCHED_ARTISTS

    def batches(self, args, watching) -> Iterator[Batch]:
        for artist_id, label in watching.items():
            rows = fetch(artist_id)    # yield one Batch per call
            yield Batch(releases=[normalize(r, label) for r in rows], label=label)
```

Then:

```python
def main() -> int:
    radar = ItunesRadar()
    args = parser(radar, "Report new releases ... via iTunes.").parse_args()
    return execute(radar, args)
```

`parser()` and `execute()` are separate so a radar can own a mode that exits
before any fetch — `radars/qobuz.py --find` is an artist-id lookup and should
not have to pretend to be a run to read its arguments.

## What you can override, and when you would

| | |
|---|---|
| `keep_types` | release kinds worth reporting. `None` keeps everything |
| `state_file` | only to keep an existing filename. `listenbrainz` overrides it to `seen.json`, because that radar predates the convention and renaming it would re-report its whole window once |
| `record_scanned` | `True` records every id seen, so the date cutoff cannot let an old release resurface the week it falls out of the window. `False` for a feed — see below |
| `guard_empty_run` | `False` for a feed — see below |
| `add_arguments` | source-specific flags, e.g. `--store` |
| `window` / `cutoff` | when `--days` does not mean "lookback". `listenbrainz` returns `""` from `cutoff`, because its `--days` is a half-width the server already applied, and filtering again would halve the window |
| `badges` | the small print after a title. Qobuz has hi-res and streamability; Apple has neither |
| `summary` / `broken_run_message` | vocabulary. A per-artist source should say "artists" and name what came back empty; a feed source would be lying if it did. The runner decides *whether* a run is broken, the source says it in its own words |
| `report_extra` | extra keys for the JSON report, e.g. `{"store": args.store}` |

## Release

One record, so sources are comparable and `report.py` serves all of them.

```python
Release(id=..., date=..., kind=..., artist=..., title=..., source=...,
        tracks=0, hires=None, streamable=None, url=None, because=None)
```

Three things to know. `kind` is written as `type` on the wire — `type` shadows a
builtin and is a poor attribute name, but `report.py` and every report already
written key on `"type"`, and renaming a field in files on disk to tidy an
attribute is not a trade worth making. `Release.row()` is the only place that
knows.

And the optional fields are genuinely optional rather than defaulted to
something false. Qobuz knows whether a release is hi-res; Apple does not.
`None` is left out of the row entirely, because `false` would claim it is not.

`because` is why the row is in the report, when that is not simply "they
released it". Only `radars/qobuz.py`'s credit pass sets it, with the watched
name and the roles Qobuz credits them with, and `report.py` puts those rows in
their own table — "Miguel Atwood-Ferguson - Ananta" in an issue about artists
you follow is a stranger otherwise (D42). Leave it alone unless your source
finds releases some way OTHER than by walking a watched artist's catalogue.

## Batch, and why a failure is not an absence

```python
Batch(releases=[...], ok=True, label="", warning="", scanned=None)
```

`ok=False` is a failed fetch. An empty `releases` with `ok=True` is a call that
succeeded and found nothing. Those must not collapse into "no rows", because
the difference is the whole basis of the broken-run guard: a service answering
200 with an empty discography for everyone is the dangerous outage, since every
call "succeeds" and the report says "Nothing new." with the warnings folded
into a block nobody opens.

`scanned` is for feed sources: it is the rows the call *looked at*, when that
differs from the records it produced. `listenbrainz` reads a few thousand rows
and keeps the handful crediting someone you watch, so `"scanned 3"` would
describe the intersection rather than the work. `radars/qobuz.py`'s credit pass
sets it for the same reason, and that pass is also why a batch is **one
artist** rather than one call: the runner counts a batch as a call and reports
`fetched` of `watching` as artists, so a second batch per artist made a
128-artist run say "from 256 of 128 artists" (D42).

## Feed sources are different

`listenbrainz` asks once for a window; the other two ask per artist and read a
catalogue. Two settings say so, and both are about not lying:

- `record_scanned = False` — recording a release that matched nobody would hide
  it for good if you later started watching that artist.
- `guard_empty_run = False` — a feed answering with zero rows is a legitimate
  quiet window, and nothing distinguishes it from an outage.

## The third shape: a source whose QUESTION changes

`radars/labels.py` (D44) reads a catalogue like `qobuz` does, but it sets
`record_scanned = False` like the feed does, and the pair is neither of the two
cases above. The reason is not the source, it is the question: what it scans is
a label's catalogue, and what it ASKS is whether the credits name anybody in
`data/producers.json` — a list that grows. Recording a release that credited
nobody would hide it for good the day you add the producer it credits, which is
`listenbrainz`'s argument reaching a catalogue source by a different route.

`guard_empty_run` stays `True`, unlike the feed, because a label catalogue
always returns rows: nothing from any of two hundred labels is an outage, and
it is the date filter that empties the report rather than the fetch.

So the two settings are about the question and the source separately, and a new
radar should decide them separately rather than copying either pair wholesale.

## Scheduling one

`.github/workflows/radar.yml` runs any radar: it installs, runs, formats with
`report.py`, opens an issue, and uploads the report, warnings and run log for
90 days. A radar's own caller owns only its cron and its flags.

```yaml
jobs:
  itunes:
    uses: ./.github/workflows/radar.yml
    with:
      radar: radars/itunes.py
      title: "releases: apple"
      days: "10"
```

`stateless: true` is the default, and it is a workaround: a runner has no disk
between runs, so the radar runs `--all` and the date window does the filtering
instead. The cost is that a release can appear in two consecutive issues when
`days` exceeds seven — cheap and visible, unlike an `actions/cache` eviction
silently resetting the radar to "everything is new". Flip it once the state
file has somewhere durable to live.

## Testing one

The suite is offline: every call is stubbed at the seam and nothing can touch
`data/`. The `qobuz` fixture in `tests/conftest.py` is the pattern — set
`.discography` to `{artist_id: [album, ...]}` or to a callable for per-artist
outcomes, call `.run(args)`, and read `.saved` for what would have been
written. It patches two modules, because a radar is now a thin source over a
shared runner: `core.qobuz` walks the pages, and `core.radar` owns the state
file, the clock and the pacing.

`tests/test_radar_core.py` covers the shared parts directly rather than through
a source — `verdict()` is every radar's idea of "is this news?", and
`Release.row()` is everything `report.py` formats.

## The one that does not fit

`radars/remezcla.py` is not here and should not be. It pages a blog by curator,
has no artist ids at all, and emits picks plus a pile of rows whose title
survives only inside a video embed. The three things `core/radar.py` factors
out are the three things it does not have.

An abstraction that fits three sources of four is doing its job. Forcing the
fourth one in is how these go bad.
