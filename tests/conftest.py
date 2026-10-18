"""Shared fixtures. The stubbing each test used to repeat, once.

Every test here is offline: `qobuz` and `listenbrainz` stub the network at the
seam, and anything that writes is pointed at tmp_path. Nothing reaches a real
host, and nothing can touch data/ -- the suite is run against the real store
in CI, where there are no credentials to spend and no state to corrupt.

The old tests set module attributes directly, which was safe only because
tests/run.py gave each file its own process. pytest shares one, so everything
goes through monkeypatch and is undone after each test.
"""

from __future__ import annotations

import datetime as dt
import json
import sys

import pytest


@pytest.fixture(autouse=True)
def no_real_month_store(monkeypatch, tmp_path):
    """Nothing may write core.listens' real month directories, patched or not.

    This file's own docstring promises "nothing can touch data/", and for
    core.listens that was briefly untrue. write_month resolves its directory
    PER CALL from the module globals, so a test that patched only one of the
    two names wrote fake months into the real cache/ and data/ and clobbered
    two months of real listening -- which then moved every band in the report.
    Redirecting both by default makes forgetting harmless; a test that wants a
    specific directory patches it afterwards and wins.
    """
    import core.listens as listens

    monkeypatch.setattr(listens, "SEEDED", tmp_path / "_seeded")
    monkeypatch.setattr(listens, "SNAPSHOTS", tmp_path / "_snapshots")
    monkeypatch.setattr(listens, "MONTHS", tmp_path / "_seeded")


@pytest.fixture
def album():
    """A Qobuz album row, in the shape artist/get returns.

    `artists` must contain the artist being asked about: the radar drops
    releases where the watched artist is only a guest, so a row crediting
    somebody else is silently filtered and the test looks broken.
    """
    def make(album_id, artist, title=None, tracks=10, date="2026-10-14",
             hires=True, streamable=True, artists=None):
        credited = artists or [(artist, f"artist-{artist}")]
        return {
            "id": album_id,
            "title": title or f"Album {album_id}",
            "tracks_count": tracks,
            "release_date_original": date,
            "hires": hires,
            "streamable": streamable,
            "artists": [{"id": i, "name": n} for i, n in credited],
        }
    return make


@pytest.fixture
def qobuz(monkeypatch):
    """radars.qobuz with its network, state and sleeping stubbed.

    Returns a handle: set `.discography` to {artist_id: [album, ...]} or to a
    callable for per-artist outcomes, then call `.run(args)`. `.saved` holds
    what would have been written to the state file, or None if nothing was.
    """
    import core.qobuz as client
    import core.radar as runner
    import radars.qobuz as radar

    class Handle:
        def __init__(self):
            self.discography: dict | None = None
            self.saved = None
            self.asked: list[int] = []

        def _get_json(self, url, headers=None, what=""):
            artist = int(url.split("artist_id=")[1].split("&")[0])
            self.asked.append(artist)
            pages = self.discography
            items = pages(artist) if callable(pages) else pages.get(artist, [])
            if isinstance(items, tuple):        # an explicit (None, "error")
                return items
            return {"name": f"artist-{artist}",
                    "albums_without_last_release": {"items": items}}, "ok"

        def run(self, args, watching=None, seen=()):
            import sys
            # Two seams, in two modules, because the radar is now a thin
            # source over a shared runner: core.qobuz walks the pages, and
            # core.radar owns the state file, the clock and the pacing.
            monkeypatch.setattr(client, "get_json", self._get_json)
            monkeypatch.setattr(radar, "store_cookies", lambda store: "c=1")
            monkeypatch.setattr(runner, "load_seen", lambda path: set(seen))
            monkeypatch.setattr(runner, "save_seen",
                                lambda path, s: setattr(self, "saved", s))
            monkeypatch.setattr(runner.time, "sleep", lambda s: None)
            if watching is not None:
                monkeypatch.setattr(radar, "WATCHED_ARTISTS", watching)
            monkeypatch.setattr(sys, "argv", ["qobuz.py", *args])
            return radar.main()

    return Handle()


@pytest.fixture
def favourites_file(monkeypatch, tmp_path):
    """stages.favourites pointed at an in-memory favourites list.

    Returns a handle whose `.entries` is what the stage reads and mutates in
    place, and whose `.saved` is what it would have written -- None when the
    stage chose not to save, which several tests assert.
    """
    import stages.favourites as stage

    class Handle:
        def __init__(self):
            self.entries: list[dict] = []
            self.saved = None
            self.FILE = tmp_path / "favourites.json"

        def install(self):
            handle = self

            class Stub:
                FILE = handle.FILE

                def load(self, *a, **k):
                    return handle.entries

                def save(self, artists, generated, *a, **k):
                    handle.saved = artists

            monkeypatch.setattr(stage, "favourites", Stub())
            return stage

        def answers(self, keys):
            """Feed --review one line per prompt."""
            lines = iter(list(keys))
            monkeypatch.setattr("builtins.input", lambda *a: next(lines))

    return Handle()


@pytest.fixture
def today():
    return dt.date.today()


@pytest.fixture
def apple_release():
    """One iTunes `lookup` result row, in the shape Apple returns.

    `wrapperType` is "collection" because that is what fetch_artist_releases
    filters on -- results[0] is the artist itself and everything else is a
    release, so a row without it is invisible to the radar.
    """
    def make(collection_id, name, artist="Jorge Drexler", date="2026-10-14",
             tracks=10, wrapper="collection"):
        return {
            "wrapperType": wrapper,
            "collectionId": collection_id,
            "collectionName": name,
            "collectionType": "Album",      # literally this, even for a single
            "artistName": artist,
            "releaseDate": f"{date}T07:00:00Z",
            "trackCount": tracks,
        }
    return make


@pytest.fixture
def itunes(monkeypatch):
    """radars.itunes with Apple, state and sleeping stubbed.

    Set `.catalogue` to {artist_id: [row, ...]}, or to an int to make that
    artist's lookup return that HTTP status, or to a raw string for a body that
    is not JSON. `.saved` is what would have reached the state file.
    """
    import urllib.parse

    import core.radar as runner
    import radars.itunes as radar

    class Handle:
        def __init__(self):
            self.catalogue: dict | None = None
            self.saved = None
            self.asked: list[int] = []

        def _get(self, url, headers=None, timeout=30, user_agent=None, service=""):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            artist = int(query["id"][0])
            self.asked.append(artist)
            pages = self.catalogue
            items = pages(artist) if callable(pages) else (pages or {}).get(artist, [])
            if isinstance(items, int):             # an explicit HTTP status
                return items, "", {}
            if isinstance(items, str):             # a body that is not JSON
                return 200, items, {}
            assert isinstance(items, list), (
                "catalogue values are a list of rows, an int HTTP status, "
                "or a raw body string")
            # results[0] is the artist; the radar must skip it.
            rows = [{"wrapperType": "artist", "artistId": artist}, *items]
            return 200, json.dumps({"results": rows}), {}

        def run(self, args, watching=None, seen=()):
            monkeypatch.setattr(radar, "http_get", self._get)
            monkeypatch.setattr(runner, "load_seen", lambda path: set(seen))
            monkeypatch.setattr(runner, "save_seen",
                                lambda path, s: setattr(self, "saved", s))
            monkeypatch.setattr(runner.time, "sleep", lambda s: None)
            if watching is not None:
                monkeypatch.setattr(radar, "WATCHED_ARTISTS", watching)
            monkeypatch.setattr(sys, "argv", ["itunes.py", *args])
            return radar.main()

    return Handle()


@pytest.fixture
def feed_row():
    """One ListenBrainz fresh-releases row."""
    def make(mbid="rel-1", name="Album", date="2026-10-14", kind="Album",
             credit="Jorge Drexler", artist_mbids=("mbid-drexler",), **extra):
        row = {
            "release_mbid": mbid,
            "release_name": name,
            "release_date": date,
            "release_group_primary_type": kind,
            "artist_credit_name": credit,
            "artist_mbids": list(artist_mbids),
        }
        row.update(extra)
        return row
    return make


@pytest.fixture
def listenbrainz(monkeypatch):
    """radars.listenbrainz with the feed, state and sleeping stubbed.

    Set `.feed` to a list of rows, an int for an HTTP status, or a raw string
    for a body that is not JSON. `.urls` records what was requested, which is
    how the half-width window is asserted.
    """
    import core.radar as runner
    import radars.listenbrainz as radar

    class Handle:
        def __init__(self):
            self.feed: list | int | str = []
            self.saved = None
            self.urls: list[str] = []

        def _get(self, url, headers=None, timeout=60, user_agent=None, service=""):
            self.urls.append(url)
            if isinstance(self.feed, int):
                return self.feed, "", {}
            if isinstance(self.feed, str):
                return 200, self.feed, {}
            return 200, json.dumps({"payload": {"releases": self.feed}}), {}

        def run(self, args, watching=None, seen=()):
            monkeypatch.setattr(radar, "http_get", self._get)
            monkeypatch.setattr(runner, "load_seen", lambda path: set(seen))
            monkeypatch.setattr(runner, "save_seen",
                                lambda path, s: setattr(self, "saved", s))
            monkeypatch.setattr(runner.time, "sleep", lambda s: None)
            if watching is not None:
                monkeypatch.setattr(radar, "WATCHED_ARTISTS", watching)
            monkeypatch.setattr(sys, "argv", ["listenbrainz.py", *args])
            return radar.main()

    return Handle()
