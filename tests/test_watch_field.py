"""Does watch:false survive a resolve run, and does it hide the artist?"""
import io, sys, tempfile
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import stages.favourites as fav
from core import favourites as core_fav

saved = {}
class Stub:
    FILE = Path(tempfile.mkdtemp()) / "mute_out.json"
    def __init__(self, entries): self.entries = entries
    def load(self, *a, **k): return self.entries
    def save(self, artists, generated, *a, **k): saved["artists"] = artists
fav.favourites = Stub([
    {"name": "Bobby Cruz", "qobuz_id": 55, "qobuz_match": "exact", "watch": False},
    {"name": "Jorge Drexler", "qobuz_id": 41620, "qobuz_match": "exact"},
])
# Bobby Cruz is STILL in the ListenBrainz top lists next month:
fav.collect = lambda user, periods, count: {
    "bobby cruz": {"name": "Bobby Cruz", "mbid": "m-bc", "plays": 41, "ranks": {"year": 90}},
    "jorge drexler": {"name": "Jorge Drexler", "mbid": "m-jd", "plays": 6447, "ranks": {"all_time": 1}},
}
fav.search_artists = lambda n, s: (_ for _ in ()).throw(AssertionError("should not re-resolve"))
fav.track_counts = lambda: {}

sys.argv = ["favourites.py", "--user", "x"]
out = io.StringIO(); real, sys.stdout = sys.stdout, out
try:
    code = fav.main()
finally:
    sys.stdout = real
assert code == 0

by_name = {a["name"]: a for a in saved["artists"]}
assert by_name["Bobby Cruz"]["watch"] is False, by_name["Bobby Cruz"]
assert by_name["Bobby Cruz"]["plays"] == 41        # stats still refreshed
assert "watch" not in by_name["Jorge Drexler"]
print("1 ok: watch:false survives a run that re-sees the artist in the top lists")

import json, tempfile
# A fresh dir each run: the first assertion depends on the file NOT existing,
# so leaving it behind made the test pass once and fail forever after.
probe = Path(tempfile.mkdtemp()) / "muted.json"
assert core_fav.ids_for("qobuz_id", {0: "fallback"}, probe) == {0: "fallback"}
probe.write_text(json.dumps({"artists": saved["artists"]}))
ids = core_fav.ids_for("qobuz_id", {0: "fallback"}, probe)
assert ids == {41620: "Jorge Drexler"}, ids
print("2 ok: the radar never sees a muted artist")

pending = [e for e in saved["artists"]
           if e.get("watch", True) and e.get("qobuz_match") not in ("exact", "manual")]
assert pending == []
print("3 ok: --review does not ask about it again either")
print("\nall 3 ok")
