"""Verify a 500 no longer kills the run. No network, no file written."""
import io, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import core.qobuz as cq

slept = []
cq.time = type("t", (), {"sleep": staticmethod(lambda s: slept.append(s))})()

def fake_get(responses):
    seq = list(responses)
    calls = []
    def _get(url, headers=None, timeout=40):
        calls.append(url)
        return seq.pop(0) if seq else (200, "{}", None)
    return _get, calls

# 1. a 5xx that clears on the second attempt
cq.get, calls = fake_get([(500, "boom", None), (200, '{"name": "Jorge Drexler"}', None)])
slept.clear()
assert cq.get_json("u", what="artist/get 1") == ({"name": "Jorge Drexler"}, "ok")
assert len(calls) == 2 and slept == [0.8], (calls, slept)
print("1 ok: 5xx retried, second attempt succeeds")

# 2. a persistent 5xx gives up after RETRIES, with backoff, and does NOT raise
cq.get, calls = fake_get([(500, "boom", None)] * 3)
slept.clear()
assert cq.get_json("u", what="artist/get 1") == (None, "error")
assert len(calls) == cq.RETRIES == 3 and slept == [0.8, 1.6], (calls, slept)
print("2 ok: gives up after 3, no raise, no sleep after the last try")

# 3. 4xx is not retried; 404 is its own outcome
cq.get, calls = fake_get([(404, "", None)])
assert cq.get_json("u") == (None, "not_found") and len(calls) == 1
cq.get, calls = fake_get([(400, '{"message":"nope"}', None)])
assert cq.get_json("u") == (None, "error") and len(calls) == 1
print("3 ok: 404 not_found, 4xx error, neither retried")

# --- the radar -----------------------------------------------------------
import radars.qobuz as rq

def album(i, artist, tracks=10, date="2026-10-01"):
    # artists must carry the artist being asked about, or the radar's
    # primary-artist filter correctly drops it as a guest appearance.
    return {"id": i, "title": f"Album {i}", "tracks_count": tracks,
            "release_date_original": date,
            "artists": [{"id": artist, "name": f"A{artist}"}],
            "streamable": True}

# artist 2 fails on its first page; 1 and 3 are fine
PAGES = {1: ({"name": "One", "albums_without_last_release": {"items": [album(11, 1)]}}, "ok"),
         2: (None, "error"),
         3: ({"name": "Three", "albums_without_last_release": {"items": [album(33, 3)]}}, "ok")}
asked = []
def fake_get_json(url, headers=None, what="Qobuz"):
    artist = int(url.split("artist_id=")[1].split("&")[0])
    asked.append(artist)
    return PAGES[artist]
rq._get_json = fake_get_json

name, albums, ok = rq.artist_releases(2, "gb-en", "c=1")
assert (name, albums, ok) == ("?", [], False)
print("4 ok: a failed artist returns succeeded=False instead of raising")

asked.clear()   # case 4 above called it once directly
rq.WATCHED_ARTISTS = {1: "One", 2: "Two", 3: "Three"}
rq.store_cookies = lambda store: "c=1"
rq.load_seen = lambda: set()
saved = {}
rq._save_seen = lambda path, seen: saved.update(path=path, seen=seen)
rq.time = type("t", (), {"sleep": staticmethod(lambda s: None)})()

sys.argv = ["qobuz.py", "--days", "90"]
out, err = io.StringIO(), io.StringIO()
real_out, real_err = sys.stdout, sys.stderr
sys.stdout, sys.stderr = out, err
try:
    code = rq.main()
finally:
    sys.stdout, sys.stderr = real_out, real_err
text, warnings = out.getvalue(), err.getvalue()

assert code == 0, code
assert asked == [1, 2, 3], asked                       # kept going past the failure
assert "Scanned 2 releases from 2 of 3 artists" in text, text
assert "1 artist could not be fetched" in text, text
assert "Two (2) lookup failed, skipped" in warnings, warnings
assert "Album 11" in text and "Album 33" in text, text
assert saved["seen"] == {"11", "33"}, saved            # nothing recorded for the failure
print("5 ok: run completes, both good artists reported, state saved without the failed one")

assert "2" not in saved["seen"]
print("\nall 5 ok, no network, no file written")
