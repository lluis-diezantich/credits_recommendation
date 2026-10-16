"""--mute / --unmute, with no network and no touching the real file."""
import io, json, sys, tempfile
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import stages.favourites as fav
from core import favourites as core_fav

TMP = Path(tempfile.mkdtemp())


def run(entries, argv):
    saved = {}
    class Stub:
        FILE = TMP / "never_written.json"
        def load(self, *a, **k): return entries
        def save(self, artists, generated, *a, **k): saved["artists"] = artists
    fav.favourites = Stub()
    sys.argv = ["favourites.py"] + argv
    out, err = io.StringIO(), io.StringIO()
    ro, re_ = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        code = fav.main()
    finally:
        sys.stdout, sys.stderr = ro, re_
    return code, saved.get("artists"), out.getvalue(), err.getvalue()

rows = lambda: [
    {"name": "Bobby Cruz", "qobuz_id": 55, "qobuz_match": "exact", "tracks": 1},
    {"name": "Jorge Drexler", "qobuz_id": 41620, "qobuz_match": "exact", "tracks": 152},
    {"name": "Feli Colina", "qobuz_id": 77, "qobuz_match": "exact", "watch": False},
]

# 1. mute one, accent/case-insensitively
r = rows()
code, saved, out, err = run(r, ["--mute", "bobby  CRUZ"])
assert code == 0 and r[0]["watch"] is False and saved is r
assert "Bobby Cruz: muted" in out and "1 changed" in out, out
print("1 ok: muted, name matching folds case and spacing")

# 2. already muted says so and writes nothing
r = rows()
code, saved, out, err = run(r, ["--mute", "Feli Colina"])
assert saved is None and "already muted" in out and "nothing changed" in out
print("2 ok: already muted is a no-op")

# 3. unmute removes the key rather than writing watch:true
r = rows()
code, saved, out, err = run(r, ["--unmute", "Feli Colina"])
assert "watch" not in r[2], r[2]
assert "Feli Colina: watched" in out
print("3 ok: unmute deletes the key")

# 4. several at once, and a typo gets a suggestion without stopping the rest
r = rows()
code, saved, out, err = run(r, ["--mute", "Bobby Cruz", "Drexler", "Nobody Here"])
assert r[0]["watch"] is False
assert "did you mean Jorge Drexler?" in err, err
assert "not found: Nobody Here" in err and "did you mean" not in err.split("Nobody Here")[1]
assert "1 changed" in out
print("4 ok: partial match hints, unknown name skipped, the rest still applied")

# 5. --dry-run decides but writes nothing
r = rows()
code, saved, out, err = run(r, ["--mute", "Bobby Cruz", "--dry-run"])
assert saved is None and "nothing written" in out and r[0]["watch"] is False
print("5 ok: dry-run")

# 6. both flags at once is rejected, and no --user is needed
try:
    run(rows(), ["--mute", "A", "--unmute", "B"])
    raise AssertionError("should have exited")
except SystemExit as e:
    assert e.code == 2, e.code
print("6 ok: --mute with --unmute is an error; neither needs --user")

# 7. the note is written into the file, and load() still ignores it
noted = TMP / "noted.json"
core_fav.save(rows(), "now", noted)
blob = json.loads(noted.read_text())
assert "watch" in blob["note"] and blob["note"].startswith("hand-edits are kept")
assert len(core_fav.load(noted)) == 3
print("7 ok: note written, load unaffected")

assert not (TMP / "never_written.json").exists()
print("\nall 7 ok")
