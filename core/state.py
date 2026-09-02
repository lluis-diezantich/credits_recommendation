"""The *_seen.json contract the radars each re-invented.

Every radar keeps its own state file and subtracts it from the current feed, so
each run reports only what is new. load_seen was byte-identical in all three;
save_seen existed in two, and qobuz_releases.py inlined its own third version.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def load_seen(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text()))
    except (json.JSONDecodeError, OSError) as error:
        # A corrupt state file should not stop the radar; worst case you get
        # one duplicate report and a clean file afterwards.
        print(f"warning: ignoring unreadable {path.name} ({error})", file=sys.stderr)
        return set()


def save_seen(path: Path, seen: set[str]) -> None:
    path.write_text(json.dumps(sorted(seen), indent=0))
