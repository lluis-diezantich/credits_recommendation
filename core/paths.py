"""Where things live.

Code sits in radars/ (and in stages/ on the `ranking` branch); everything they
read or write sits in data/ and cache/. Keeping generated JSON out of the code
directories is the whole reason this layout exists -- pool_discogs.json alone
is 4.5 MB.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CACHE = ROOT / "cache"

DATA.mkdir(exist_ok=True)
CACHE.mkdir(exist_ok=True)
