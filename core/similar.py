"""ListenBrainz's own similar-artist list, which is the thing this project
has to beat.

`roadmap.md` has asked from the start whether a credit graph carries signal a
listening-similarity model does not. Nothing here answered it, because there
was no second list to compare against. This is that list: one request per
seed, cached, from the free API `radars/listenbrainz.py` already speaks to.

    similar("87c5dedd-...")  -> [("Radiohead", mbid, 6682), ("Portishead", ...)]

The algorithm string is part of the URL rather than a default, and it is
pinned: ListenBrainz exposes several and they return different lists, so a
comparison run against one algorithm today and another next month would be
measuring the wrong thing. `ALGORITHM` names the one the baseline was taken
with, and changing it invalidates every logged run that used it.

Cached per (mbid, algorithm) and effectively forever. Session-based similarity
drifts as listening data accumulates, so this is NOT a fact like a death date
-- but a baseline whose numbers move under it cannot be compared with, which
is the same reason `cache/` exists at all (D7).
"""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

from core.http import get
from core.paths import CACHE

CACHE_DIR = CACHE / "similar"

URL = "https://labs.api.listenbrainz.org/similar-artists/json"

# The algorithm the baseline is measured with. Session-based: artists that turn
# up in the same listening sessions, which is the closest thing ListenBrainz
# has to "people who play this also play that" and the fairest opponent for a
# credit graph. Pinned because the others return different lists.
ALGORITHM = ("session_based_days_7500_session_300_contribution_5"
             "_threshold_10_limit_100_filter_True_skip_30")

USER_AGENT = ("credits-recommendation/0.1 "
              "( https://github.com/lluis-diezantich/credits_recommendation )")


def cache_path(mbid: str, directory: Path | None = None) -> Path:
    """One file per (mbid, algorithm). The algorithm is in the NAME.

    So a run under a different algorithm cannot read a file written under this
    one -- a silent mix of two similarity models would be a comparison of
    nothing in particular.
    """
    short = ALGORITHM.split("_days_")[0]
    return (directory or CACHE_DIR) / f"{short}_{mbid}.json"


def parse(body: str) -> list[dict]:
    """The API's rows, trimmed to what a comparison needs.

    Score-ordered as it arrives, and kept that way: the order IS the
    recommendation, exactly as the ranked co-appearance list's order is.
    """
    try:
        rows = json.loads(body)
    except json.JSONDecodeError:
        return []
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        out.append({"name": row["name"], "mbid": row.get("artist_mbid"),
                    "score": row.get("score") or 0,
                    "type": row.get("type")})
    return out


def similar(mbid: str, refresh: bool = False,
            directory: Path | None = None) -> list[dict] | None:
    """One seed's similar artists, cached. None when it cannot be read.

    None rather than an empty list, and the distinction matters more here than
    usual: "ListenBrainz has no similar artists for this seed" is a result a
    comparison must be able to report, and "the request failed" is not.
    """
    path = cache_path(mbid, directory)
    if path.exists() and not refresh:
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass            # a corrupt cache entry is refetched, not fatal
    query = urllib.parse.urlencode({"artist_mbids": mbid,
                                    "algorithm": ALGORITHM})
    status, body, _ = get(f"{URL}?{query}", timeout=60,
                          user_agent=USER_AGENT, service="ListenBrainz labs",
                          fatal=False)
    if status != 200:
        return None
    rows = parse(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False) + "\n")
    return rows
