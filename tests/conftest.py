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

import pytest


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
            monkeypatch.setattr(radar, "_get_json", self._get_json)
            monkeypatch.setattr(radar, "store_cookies", lambda store: "c=1")
            monkeypatch.setattr(radar, "load_seen", lambda: set(seen))
            monkeypatch.setattr(radar, "_save_seen",
                                lambda path, s: setattr(self, "saved", s))
            monkeypatch.setattr(radar.time, "sleep", lambda s: None)
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
