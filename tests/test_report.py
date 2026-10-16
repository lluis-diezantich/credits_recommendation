"""Radar -> JSON -> markdown, end to end, no network."""
import io, json, subprocess, sys, tempfile
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import radars.qobuz as rq

def album(aid, artists, title, tracks, date, hires=True, streamable=True):
    return {"id": aid, "title": title, "tracks_count": tracks, "hires": hires,
            "release_date_original": date, "streamable": streamable,
            "artists": [{"id": i, "name": n} for i, n in artists]}

SHARED = album(902, [(1, "CHUWI"), (2, "Silvana Estrada")], "Fantasmeo", 1, "2026-10-13")
DISCOG = {
    1: [album(901, [(1, "CHUWI")], "Libertad", 13, "2026-10-14"), SHARED],
    2: [SHARED, album(903, [(2, "Silvana Estrada")], "Todo Baila | live", 1, "2026-10-15")],
    3: [album(905, [(3, "Newen Afrobeat")], "La Fuerza", 1, "2099-10-30", streamable=False)],
}
rq._get_json = lambda url, h=None, what="": (
    {"name": "x", "albums_without_last_release":
        {"items": DISCOG[int(url.split("artist_id=")[1].split("&")[0])]}}, "ok")
rq.WATCHED_ARTISTS = {1: "CHUWI", 2: "Silvana Estrada", 3: "Newen Afrobeat"}
rq.store_cookies = lambda s: "c=1"
rq.load_seen = lambda: set()
rq._save_seen = lambda p, s: (_ for _ in ()).throw(AssertionError("--all must not save"))
rq.time = type("t", (), {"sleep": staticmethod(lambda s: None)})()

tmp = Path(tempfile.mkdtemp())
out_json = tmp / "releases.json"
sys.argv = ["qobuz.py", "--all", "--days", "0", "--json", str(out_json)]
buf, err = io.StringIO(), io.StringIO()
ro, re_ = sys.stdout, sys.stderr
sys.stdout, sys.stderr = buf, err
try:
    code = rq.main()
finally:
    sys.stdout, sys.stderr = ro, re_
assert code == 0, code

report = json.loads(out_json.read_text())
assert report["source"] == "qobuz" and report["shared"] == 1
assert len(report["releases"]) == 4, report["releases"]
assert [r["upcoming"] for r in report["releases"]] == [False, False, False, True]
print("1 ok: radar wrote JSON — 4 releases, 1 shared fold, upcoming stamped")

# the plain stdout report is unchanged by --json
assert "4 new releases" in buf.getvalue() and "Scanned 5 releases" in buf.getvalue()
print("2 ok: human output still printed alongside the file")

warn = tmp / "warnings.txt"
warn.write_text("warning: Oscar D'León (12371666) returned no releases\n")
body = subprocess.run([sys.executable, "-I", str(REPO / "radars/report.py"),
                       str(out_json), "--warnings", str(warn)],
                      capture_output=True, text=True, cwd=tmp)
assert body.returncode == 0, body.stderr
md = body.stdout
print("=" * 72); print(md.rstrip()); print("=" * 72)
assert md.startswith("**4 new releases**")
assert "*(upcoming)*" in md and "not streamable" in md
assert r"Todo Baila \| live" in md, "pipe must be escaped"
assert "<details><summary>warnings</summary>" in md and "Oscar" in md
assert "credited to more than one artist" in md
print("\n3 ok: markdown renders from the file alone, warnings folded in")

# a report with none of the optional fields still formats
import importlib.util
spec = importlib.util.spec_from_file_location("rep", REPO / "radars/report.py")
rep = importlib.util.module_from_spec(spec); spec.loader.exec_module(rep)
bare = rep.to_markdown({"releases": [{"date": "2026-01-01", "title": "X", "artist": "Y"}],
                        "watching": 1, "fetched": 1})
assert "| 2026-01-01 | ? | Y | X |" in bare, bare
assert rep.to_markdown({"releases": [], "watching": 5, "fetched": 5}).count("Nothing new") == 1
print("4 ok: missing optional fields and an empty week both format")
