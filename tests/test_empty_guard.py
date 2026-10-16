"""The guard must fire on an empty catalogue, and NOT on a genuinely quiet week."""
import io, sys, tempfile
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import radars.qobuz as rq

def album(aid, artist, date):
    return {"id": aid, "title": f"A{aid}", "tracks_count": 10, "hires": True,
            "release_date_original": date, "streamable": True,
            "artists": [{"id": artist, "name": f"n{artist}"}]}

rq.WATCHED_ARTISTS = {1: "One", 2: "Two", 3: "Three"}
rq.store_cookies = lambda s: "c=1"
rq.load_seen = lambda: set()
rq._save_seen = lambda p, s: None
rq.time = type("t", (), {"sleep": staticmethod(lambda s: None)})()

def run(pages, argv):
    rq._get_json = lambda url, h=None, what="": pages(
        int(url.split("artist_id=")[1].split("&")[0]))
    sys.argv = ["qobuz.py"] + argv
    out, err = io.StringIO(), io.StringIO()
    ro, re_ = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        code = rq.main()
    finally:
        sys.stdout, sys.stderr = ro, re_
    return code, out.getvalue(), err.getvalue()

ok = lambda items: ({"name": "x", "albums_without_last_release": {"items": items}}, "ok")

# 1. everyone answers 200 with an empty discography -> broken
code, out, err = run(lambda a: ok([]), ["--all", "--days", "10"])
assert code == 1, code
assert "nothing came back from any of 3 artists (0 failed, 3 returned an empty" in err, err
print("1 ok: all-empty is a broken run")

# 2. a genuinely quiet week: catalogue exists, the DATE FILTER empties it
code, out, err = run(lambda a: ok([album(a * 10, a, "1998-01-01")]), ["--all", "--days", "10"])
assert code == 0, (code, err)
assert "Nothing new." in out, out
print("2 ok: old catalogue + date filter is still a normal quiet week, exit 0")

# 3. mixed causes still trip it
def mixed(a):
    return (None, "error") if a == 1 else ok([])
code, out, err = run(mixed, ["--all", "--days", "10"])
assert code == 1 and "(1 failed, 2 returned an empty" in err, err
print("3 ok: failures and empties count together")

# 4. one real result is enough to make it a good run
def one_good(a):
    return ok([album(99, a, "2026-10-15")]) if a == 2 else ok([])
code, out, err = run(one_good, ["--all", "--days", "3650"])
assert code == 0 and "1 new release" in out, (code, out)
print("4 ok: a single live artist keeps the run healthy")

# 5. the JSON is not written for a broken run
tmp = Path(tempfile.mkdtemp()) / "r.json"
code, out, err = run(lambda a: ok([]), ["--all", "--days", "10", "--json", str(tmp)])
assert code == 1 and not tmp.exists(), (code, tmp.exists())
print("5 ok: a broken run writes no report for the formatter to publish")
print("\nall 5 ok")
