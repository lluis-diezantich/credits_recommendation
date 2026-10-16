"""Exercise --review with no network and no touching data/favourites.json."""
import io, sys, tempfile, types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import stages.favourites as fav

CANDS = {
    "Javier Colina": [
        {"id": 111, "name": "Javier Colina", "albumsCount": 9},
        {"id": 222, "name": "Javier Colina", "albumsCount": 40},
    ],
    "Rosalia": [{"id": 333, "name": "ROSALÍA", "albumsCount": 7}],
    "Nobody At All": [],
}
calls = []
fav.search_artists = lambda name, store: (calls.append(name), CANDS.get(name, []))[1]

TMP = Path(tempfile.mkdtemp())

class Stub:
    FILE = TMP / "out.json"
    def __init__(self, entries): self.entries, self.saved = entries, None
    def load(self, *a, **k): return self.entries
    def save(self, artists, generated, *a, **k): self.saved = artists

def run(entries, keys, dry_run=False):
    stub = Stub(entries)
    fav.favourites = stub
    sys.stdin = io.StringIO("".join(k + "\n" for k in keys))
    out = io.StringIO()
    real, sys.stdout = sys.stdout, out
    try:
        code = fav.review("gb-en", dry_run)
    finally:
        sys.stdout = real
    return code, stub.saved, out.getvalue()

# 1. pick by number, re-search, mute
entries = [
    {"name": "Javier Colina", "qobuz_id": 111, "qobuz_match": "ambiguous", "plays": 300},
    {"name": "Nobody At All", "qobuz_id": None, "qobuz_match": "not_found", "plays": 80},
    {"name": "Unwanted", "qobuz_id": None, "qobuz_match": "no_exact_match", "plays": 5},
    {"name": "Fine", "qobuz_id": 9, "qobuz_match": "exact"},
    {"name": "Already", "qobuz_id": 8, "qobuz_match": "manual"},
    {"name": "Hushed", "qobuz_id": None, "qobuz_match": "not_found", "watch": False},
]
code, saved, text = run(entries, ["2", "/Rosalia", "1", "m"])
assert code == 0, code
assert "3 artists to review" in text, text
assert entries[0]["qobuz_id"] == 222 and entries[0]["qobuz_match"] == "manual"
assert entries[1]["qobuz_id"] == 333 and entries[1]["qobuz_match"] == "manual"
assert entries[2]["watch"] is False
assert entries[3]["qobuz_id"] == 9 and entries[4]["qobuz_id"] == 8   # untouched
assert "watch" not in entries[3]
assert saved is entries
assert "1 picked" not in text and "2 picked, 1 muted, 0 left open." in text, text
assert calls == ["Javier Colina", "Nobody At All", "Rosalia", "Unwanted"], calls
print("1 ok: pick / re-search / mute, exact+manual+muted all skipped")

# 2. the * marks the id already held
code, saved, text = run(
    [{"name": "Javier Colina", "qobuz_id": 222, "qobuz_match": "ambiguous"}], ["s"])
assert "*2." in text and " 1." in text, text
assert "0 picked, 0 muted, 1 left open." in text
print("2 ok: current id marked, skip leaves it alone")

# 3. q stops early and still saves what was decided
rows = [{"name": "Javier Colina", "qobuz_id": None, "qobuz_match": "not_found"},
        {"name": "Rosalia", "qobuz_id": None, "qobuz_match": "not_found"}]
code, saved, text = run(rows, ["1", "q"])
assert rows[0]["qobuz_id"] == 111 and rows[1]["qobuz_id"] is None
assert "stopped at 2 of 2" in text and saved is rows
print("3 ok: q saves the decisions made so far")

# 4. bad input re-prompts rather than crashing or guessing
code, saved, text = run(
    [{"name": "Javier Colina", "qobuz_id": None, "qobuz_match": "not_found"}], ["7", "x", "1"])
assert text.count("? expected") == 2, text
print("4 ok: out-of-range and junk re-prompt")

# 5. --dry-run writes nothing
rows = [{"name": "Rosalia", "qobuz_id": None, "qobuz_match": "not_found"}]
code, saved, text = run(rows, ["1"], dry_run=True)
assert saved is None and "nothing written" in text and rows[0]["qobuz_id"] == 333
print("5 ok: dry-run decides but does not save")

# 6. nothing to review
code, saved, text = run([{"name": "Fine", "qobuz_id": 1, "qobuz_match": "exact"}], [])
assert code == 0 and saved is None and "nothing to review" in text
print("6 ok: clean file says so and writes nothing")

assert not Stub.FILE.exists(), "test must not write any file"
print("\nall 6 ok, no network, no file written")

# --- #<id> ---------------------------------------------------------------
NAMES = {41620: ("Jorge Drexler", "ok"), 999: (None, "not_found")}
seen_cookies = []
fav.store_cookies = lambda store: (seen_cookies.append(store), "c=1")[1]
fav.artist_name = lambda i, store, cookies: NAMES.get(i, (None, "error"))

# 7. a confirmed id is accepted and the name echoed
rows = [{"name": "Nobody At All", "qobuz_id": None, "qobuz_match": "not_found"}]
code, saved, text = run(rows, ["#41620"])
assert rows[0]["qobuz_id"] == 41620 and rows[0]["qobuz_match"] == "manual"
assert "set 41620  Jorge Drexler" in text, text
assert seen_cookies == ["gb-en"], seen_cookies
print("7 ok: #<id> confirmed, name echoed, cookies fetched once")

# 8. unknown id, junk id and a failed lookup all re-prompt without setting
rows = [{"name": "Nobody At All", "qobuz_id": None, "qobuz_match": "not_found"}]
code, saved, text = run(rows, ["#999", "#abc", "#7", "s"])
assert "no artist 999" in text and "#<id> wants a number" in text
assert "could not confirm 7" in text, text
assert rows[0]["qobuz_id"] is None and rows[0]["qobuz_match"] == "not_found"
assert "0 picked, 0 muted, 1 left open." in text
print("8 ok: bad ids never written")

# 9. cookies are not fetched when no #<id> is used
seen_cookies.clear()
code, saved, text = run(
    [{"name": "Javier Colina", "qobuz_id": None, "qobuz_match": "not_found"}], ["1"])
assert seen_cookies == [], seen_cookies
print("9 ok: no #<id>, no cookie request")

# 10. a storefront failure mid-review loses nothing
def boom(store): raise SystemExit("could not load the zz-zz storefront (HTTP 404)")
fav.store_cookies = boom
rows = [{"name": "Javier Colina", "qobuz_id": None, "qobuz_match": "not_found"}]
code, saved, text = run(rows, ["#41620", "1"])
assert "could not load the zz-zz storefront" in text, text
assert rows[0]["qobuz_id"] == 111, rows          # fell back to picking, kept working
assert saved is rows
print("10 ok: store_cookies exiting does not kill the session")

print("\nall 10 ok")
