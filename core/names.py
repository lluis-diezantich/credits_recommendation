"""Name keys.

One spelling, one behaviour. The project previously had `normalise` in three
files and `normalize` in two more -- but the second pair were release shapers,
not name keys, which is precisely the confusion this module ends.
"""
from __future__ import annotations

import re
import unicodedata

# Every quote and apostrophe, typographic or ASCII, REMOVED rather than folded
# to one form. The NFKD pass below drops a curly quote (it has no ASCII form)
# and keeps a straight one, which is the inconsistency this fixes: measured
# 2026-10-24, "Oscar D'Leon" keyed four different ways depending on which file
# wrote it, and his 238 listens never met his profile row.
#
# REMOVED, not folded to "'", for two reasons the corpus decided:
#
#   1. Folding would move 24 stored keys and keep a decoration nothing wants:
#      "MARK “SPIKE” STENT" becomes `mark 'spike' stent`. Removing gives
#      `mark spike stent`, which is what the curly form already produced.
#   2. Removing MERGES 8 pairs the corpus holds under two spellings --
#      Me'Shell Ndegéocello / Meshell Ndegeocello, Hector "El Father" /
#      Hector El Father, Bonnie 'Prince' Billy / Bonnie Prince Billy. Each is
#      one person, and each would otherwise need a hand entry in
#      data/aliases.json. One of them already has one.
#
# It moves 166 stored keys, all of them a nickname in quotes. `stages/load.py`
# re-mints every key from the name for that reason -- a stored key and a fresh
# one must not disagree, which is D25's whole subject.
QUOTES = re.compile("[’‘“”ʼ´'\"]")


def normalise(name: str) -> str:
    """Grouping key: accents and quotes stripped, case folded, space collapsed.

    This is what merges "Carles Campi Campon" with "Carles Campon",
    "Lucas Piedracueva" with "Lucas Piedra Cueva", and "Oscar D’Leon" with
    "Oscar D'Leon" -- see QUOTES above for why the last one is removal rather
    than folding.
    """
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join(QUOTES.sub("", folded).lower().split())


def strip_discogs_suffix(name: str) -> str:
    """Clean Discogs' two name decorations.

    "Mauro (5)"       - numeric suffix disambiguating same-named artists
    "Valeria Castro*" - trailing asterisk marking an Artist Name Variation

    Both would fail an exact match against Qobuz, so strip them.
    """
    # Asterisk first: "Foo (2)*" is an ANV of a disambiguated artist, so the
    # decorations stack and stripping the paren first would leave "Foo (2)".
    name = name.rstrip("*").strip()
    return re.sub(r"\s*\(\d+\)\s*$", "", name).strip()
