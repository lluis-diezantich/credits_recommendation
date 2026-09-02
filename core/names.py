"""Name keys.

One spelling, one behaviour. The project previously had `normalise` in three
files and `normalize` in two more -- but the second pair were release shapers,
not name keys, which is precisely the confusion this module ends.
"""
from __future__ import annotations

import re
import unicodedata


def normalise(name: str) -> str:
    """Grouping key: accents stripped, case folded, whitespace collapsed.

    This is what merges "Carles Campi Campon" with "Carles Campon" and
    "Lucas Piedracueva" with "Lucas Piedra Cueva".
    """
    stripped = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join(stripped.lower().split())


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
