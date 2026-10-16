"""A release credited to two watched artists is reported once."""
import io, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import radars.qobuz as rq

def album(aid, artists, title, tracks=1, date="2026-10-09", hires=True):
    return {"id": aid, "title": title, "tracks_count": tracks,
            "release_date_original": date, "hires": hires, "streamable": True,
            "artists": [{"id": i, "name": n} for i, n in artists]}

SHARED = album(900, [(1, "La Plazuela"), (2, "Yerai Cortés")], "Te Odio")
DISCOG = {
    # both watched artists return the SAME shared release, plus one of their own
    1: [SHARED, album(901, [(1, "La Plazuela")], "Solo Mia")],
    2: [SHARED, album(902, [(2, "Yerai Cortés")], "Suyo")],
    # two editions of one album: different ids, so NOT the same release
    3: [album(903, [(3, "CHUWI")], "Libertad", 13),
        album(904, [(3, "CHUWI")], "Libertad", 13, hires=False)],
}
rq._get_json = lambda url, headers=None, what="": (
    {"name": "x", "albums_without_last_release":
        {"items": DISCOG[int(url.split("artist_id=")[1].split("&")[0])]}}, "ok")
rq.WATCHED_ARTISTS = {1: "La Plazuela", 2: "Yerai Cortés", 3: "CHUWI"}
rq.store_cookies = lambda store: "c=1"
rq.load_seen = lambda: set()
saved = {}
rq._save_seen = lambda path, seen: saved.update(seen=seen)
rq.time = type("t", (), {"sleep": staticmethod(lambda s: None)})()

sys.argv = ["qobuz.py", "--days", "0"]
out = io.StringIO(); real, sys.stdout = sys.stdout, out
try:
    code = rq.main()
finally:
    sys.stdout = real
text = out.getvalue()

assert code == 0, code
assert text.count("Te Odio") == 1, text
print("1 ok: the shared release appears once, not twice")
assert "(1 were credited to more than one artist you watch" in text, text
print("2 ok: the fold is reported rather than silent")
assert text.count("Libertad") == 2, text
print("3 ok: two distinct ids for one album are still two rows (cause 2, untouched)")
assert "5 new releases" in text, text
print("4 ok: 5 reported from 6 fetched rows")
assert saved["seen"] == {"900", "901", "902", "903", "904"}, saved
print("5 ok: every id scanned is still recorded as seen, including the shared one")
print("\nall 5 ok")
