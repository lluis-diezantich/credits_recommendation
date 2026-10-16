#!/usr/bin/env python3
"""A radar for the Remezcla weekly curator roundups.

Every other radar here watches artists. This one watches *critics*: the weekly
"New Songs to Listen to This Week" column, where 13 writers each pick two
records and sign the blurb. Thirteen independent beats, one request per issue.

Why it is not in the "prose, park it" pile with the rest of the editorial in
docs/sources.md: the roundups are not prose. Each pick is its own
`<section class="story__item">` with the artist in `story__item-title` and the
curator's name at the end of the blurb, so the whole series parses with two
regexes and no NLP. The same selector held across all 300 issues, 2019-2026.

Two things to know before trusting the output:

  * The series lives in the `re_guides` post type, NOT `posts`. The obvious
    /wp-json/wp/v2/posts endpoint returns roughly one roundup per 800 rows,
    which reads like the column barely exists.
  * Blurbs are unsigned before 2021. The picks are still real, the attribution
    is not, so --backfill reports them under an empty curator rather than
    guessing.

Names only, no identifiers -- the same trade-off as the Songmess feed, and for
the same reason: a human wrote the row. Crosswalking to MBIDs is the caller's
problem, and an expensive one (~75% hit rate, ~15% wrong-entity on naive name
matching, and Puerto Rican urbano is missing almost entirely).

No API key and no auth. The HTML is read with BeautifulSoup: selecting
`section.story__item` and taking its text is what a parser is for, and the
regexes that did it before could not tell `</section>` inside a comment or a
nested section from the real end of one. What stays regex is the text parsing
proper -- splitting "Artist - Track", finding the byline dash, stripping the
layout number -- because that is prose, not markup.

    ./radars/remezcla.py                      # picks new since last run
    ./radars/remezcla.py --curator "Cheky"    # one beat only
    ./radars/remezcla.py --all                # everything in the window
    ./radars/remezcla.py --backfill           # whole archive -> data/
    ./radars/remezcla.py --stats              # who writes what, from the cache

--backfill records state as well as writing the files, so the first weekly run
after one is deliberately quiet.
    ./radars/remezcla.py --dry-run            # report, record nothing
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
from pathlib import Path

# Run directly (./radars/remezcla.py) or as a module (python -m radars.remezcla).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bs4 import BeautifulSoup

from core.http import get
from core.names import normalise
from core.paths import CACHE, DATA
from core.state import load_seen as _load_seen
from core.state import save_seen as _save_seen

STATE_FILE = DATA / "remezcla_seen.json"
PICKS_FILE = DATA / "remezcla_picks.json"
UNTITLED_FILE = DATA / "remezcla_untitled.json"
ISSUE_CACHE = CACHE / "remezcla"

SITE = "https://remezcla.com"
# re_guides is the Lists post type. re_features and posts hold the reviews and
# news, which ARE prose - this radar deliberately reads neither.
INDEX = SITE + "/wp-json/wp/v2/re_guides"
USER_AGENT = "remezcla-radar/1.0 (personal use)"

# The column has been renamed twice and the archive carries all three spellings.
SERIES_TITLES = (
    "new songs to listen to this week",   # 2022-2026, the current name
    "songs you need to hear this week",    # 2019-2021, "Nuevo Noise: N Songs..."
    "in this week's new music",            # 2021, "<Artist> ... & More In ..."
    "in new music friday",
)

# Pages of 100 to read when not backfilling. The column is weekly, so one page
# covers about two years of it once the other Lists are filtered out.
DEFAULT_PAGES = 2
BACKFILL_PAGES = 14

# datePublished lives in the page's JSON-LD, so this one stays a regex: it is
# reading embedded JSON, not markup.
DATE_RE = re.compile(r'"datePublished":"(\d{4}-\d{2}-\d{2})')
# The byline is the last dash-introduced name in the blurb. Hyphens are not
# accepted as the dash: they appear inside artist names, en/em dashes do not.
BYLINE_RE = re.compile(
    r'[–—]\s*([A-ZÁÉÍÓÚÑÜ][\wÁ-ž.\-]*'
    r'(?:\s+[A-ZÁÉÍÓÚÑÜ][\wÁ-ž.\-]*){0,3})\s*$'
)
# Artist and track are separated by an en/em dash, or by a hyphen when the
# track title opens with a quote ("Bemquere- "Sua Voz e Casa"").
SPLIT_RE = re.compile(r'\s*[–—]\s*|(?<=\S)\s*-\s*(?=[“"\'])')

# Bylines are typed by hand and drift: "Alan Bae", "Juan J. Arroy", bare
# surnames. Matching on the surname folds those back without inventing people
# -- Alan Baez and Alan Lopez are two writers and must stay two.
KNOWN_CURATORS = (
    "Richard Villegas", "Marcos Hassan", "Cheky", "Jeanette Hernandez",
    "Juan J. Arroyo", "Nayeli Portillo", "Jeanette Diaz", "Alan Baez",
    "Júlia Henn", "Chelsea Quezada", "La Morra Lisa", "Felipe Maia",
    "Natasha Melina Argudo", "Brenda Barrientos", "Rosy Alvarez",
    "Caitlin Donohue", "Sofia Viera", "Holly Alvarado", "Joel Moya",
    "Jhoni Jackson", "Alex Ocho", "Gabriel Leão", "Alan Lopez",
    "Alexis Hodoyán-Gastélum", "Amanda Alcantara",
)


def load_seen() -> set[str]:
    return _load_seen(STATE_FILE)


def save_seen(seen: set[str]) -> None:
    _save_seen(STATE_FILE, seen)


def canonical_curator(raw: str) -> str:
    """Fold a hand-typed byline onto a known writer, or return it unchanged."""
    # A trailing full stop ("- Marcos Hassan.") is punctuation, not a name.
    key = normalise(raw).rstrip(".,;:").strip()
    for known in KNOWN_CURATORS:
        if key == normalise(known):
            return known
    surname = key.split()[-1] if key.split() else ""
    matches = [k for k in KNOWN_CURATORS if normalise(k).split()[-1] == surname]
    if len(matches) == 1:
        return matches[0]
    # A truncated byline ("Alan Bae", "Júlia Hen") prefixes exactly one writer.
    matches = [k for k in KNOWN_CURATORS if normalise(k).startswith(key)]
    return matches[0] if len(matches) == 1 else raw.strip()


def is_series(title: str) -> bool:
    # Curly apostrophes: the 2021 issues are titled "This Week’s New Music",
    # and matching on a straight quote silently misses all 15 of them.
    lowered = title.lower().replace("’", "'").replace("‘", "'")
    return any(spelling in lowered for spelling in SERIES_TITLES)


def issue_index(pages: int) -> list[tuple[str, str]]:
    """(url, publish date) for every issue of the column, newest first."""
    issues: list[tuple[str, str]] = []
    for page in range(1, pages + 1):
        url = f"{INDEX}?per_page=100&page={page}&_fields=title,link,date"
        status, body, _ = get(url, user_agent=USER_AGENT, service="Remezcla")
        if status != 200:
            # Paging past the end is a 400, which is how we learn where the end is.
            break
        try:
            rows = json.loads(body)
        except json.JSONDecodeError:
            sys.exit(f"Remezcla returned a response that was not JSON for page {page}")
        if not rows:
            break
        for row in rows:
            title = html.unescape(re.sub(r"<[^>]+>", "", row["title"]["rendered"]))
            if is_series(title):
                issues.append((row["link"], row["date"][:10]))
    return issues


def issue_html(url: str) -> str:
    """Fetch one issue, cached forever -- a published issue never changes."""
    ISSUE_CACHE.mkdir(parents=True, exist_ok=True)
    path = ISSUE_CACHE / (hashlib.md5(url.encode()).hexdigest() + ".html")
    if path.exists() and path.stat().st_size > 10_000:
        return path.read_text(encoding="utf-8", errors="replace")
    status, body, _ = get(url, user_agent=USER_AGENT, service="Remezcla")
    if status != 200:
        return ""
    path.write_text(body, encoding="utf-8")
    time.sleep(0.5)
    return body


def parse_issue(page: str, url: str, fallback_date: str) -> tuple[list[dict], list[dict]]:
    """(one row per pick, one row per item whose title element was empty).

    The 2021 template sometimes ships an EMPTY `story__item-title`, leaving the
    artist only inside the YouTube embed's `title` attribute ("The Marias -
    Little By Little (Official Audio)"). Parsing that back is guesswork, so
    those items are kept apart rather than guessed at: the curator, date and
    embed hint go to UNTITLED_FILE so the row survives for a later, deliberate
    resolution pass. Measured loss: 52-72% of items in 2019-2020, 38% in 2021,
    then a steady 10-16% through 2022-2025 and 0.6% in 2026. The recent ones
    are real picks, not layout noise -- Calle24 and Cachirula both land here.
    """
    date_match = DATE_RE.search(page)
    date = date_match.group(1) if date_match else fallback_date
    picks = []
    untitled: list[dict] = []
    soup = BeautifulSoup(page, "html.parser")
    for section in soup.find_all("section", class_="story__item"):
        title_element = section.find(class_="story__item-title")
        # get_text() with no separator, to match the markup it replaces: a
        # title split across tags ("<h3>A<em>B</em></h3>") is one name.
        title = title_element.get_text().strip() if title_element else ""
        # The trailing item number ("Boza - "En La Luna" \n15") is layout, not name.
        title = re.sub(r"\s*\d{1,2}\s*$", "", title).strip()
        blurb_all = section.get_text(" ").strip()
        if not title:
            byline_only = BYLINE_RE.search(blurb_all)
            embed = section.find(attrs={"title": True})
            hint = embed["title"] if embed and 5 <= len(embed["title"]) <= 90 else ""
            # "Spotify Embed: X" gives the track and no artist; a YouTube title
            # gives both but reversed and shouted. Neither is parsed here.
            untitled.append({
                "date": date,
                "curator": canonical_curator(byline_only.group(1)) if byline_only else "",
                "embed_hint": hint,
                "issue": url,
            })
            continue
        parts = SPLIT_RE.split(title, maxsplit=1)
        artist = parts[0].strip()
        # Quotes are removed rather than stripped: 'X" (feat. Y)' leaves one
        # behind mid-string, and no track title here depends on an inner quote.
        track = re.sub(r'["“”]', "", parts[1]).strip() if len(parts) > 1 else ""
        byline = BYLINE_RE.search(blurb_all)
        picks.append({
            "date": date,
            # Empty before 2021: the column did not sign individual blurbs yet.
            "curator": canonical_curator(byline.group(1)) if byline else "",
            "artist": artist,
            "track": track,
            "issue": url,
        })
    return picks, untitled


def key_of(pick: dict) -> str:
    return f"{pick['date']}|{normalise(pick['artist'])}|{normalise(pick['track'])}"


def describe(pick: dict) -> str:
    curator = pick["curator"] or "(unsigned)"
    track = f' - "{pick["track"]}"' if pick["track"] else ""
    return f"{pick['date']}  {curator:<22} {pick['artist']}{track}"


def collect(pages: int) -> tuple[list[tuple[str, str]], list[dict], list[dict]]:
    issues = issue_index(pages)
    picks: list[dict] = []
    untitled: list[dict] = []
    for url, date in issues:
        page = issue_html(url)
        if page:
            found, skipped = parse_issue(page, url, date)
            picks += found
            untitled += skipped
    return issues, picks, untitled


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report new picks from the Remezcla weekly roundups.")
    parser.add_argument("--pages", type=int, default=DEFAULT_PAGES,
                        help=f"index pages of 100 Lists to scan (default: {DEFAULT_PAGES})")
    parser.add_argument("--backfill", action="store_true",
                        help=f"scan the whole archive ({BACKFILL_PAGES} pages) "
                             f"and write {PICKS_FILE.name}")
    parser.add_argument("--curator", metavar="NAME",
                        help="report only this writer's picks (substring, case-insensitive)")
    parser.add_argument("--all", action="store_true",
                        help="report everything scanned, including already-seen picks")
    parser.add_argument("--stats", action="store_true",
                        help="per-curator counts and date ranges instead of a report")
    parser.add_argument("--dry-run", action="store_true",
                        help="report without recording anything to the state file")
    args = parser.parse_args()

    pages = BACKFILL_PAGES if args.backfill else args.pages
    issues, picks, untitled = collect(pages)
    print(f"Scanned {len(issues)} issues, {len(picks)} picks.")
    if untitled:
        print(f"Set aside {len(untitled)} items with an empty title element "
              f"(real picks, name not in the markup - see --backfill output).")

    if args.backfill:
        PICKS_FILE.write_text(json.dumps(picks, ensure_ascii=False, indent=1))
        signed = sum(1 for p in picks if p["curator"])
        print(f"Wrote {len(picks)} picks ({signed} signed) to {PICKS_FILE}.")
        UNTITLED_FILE.write_text(json.dumps(untitled, ensure_ascii=False, indent=1))
        print(f"Wrote {len(untitled)} unresolved items to {UNTITLED_FILE}.")

    if args.stats:
        seen_curators: dict[str, list[str]] = {}
        for pick in picks:
            seen_curators.setdefault(pick["curator"] or "(unsigned)", []).append(pick["date"])
        print()
        for curator, dates in sorted(seen_curators.items(), key=lambda kv: -len(kv[1])):
            print(f"  {len(dates):>5}  {curator:<24} {min(dates)} .. {max(dates)}")
        return 0

    if args.curator:
        wanted = args.curator.lower()
        picks = [p for p in picks if wanted in p["curator"].lower()]

    seen = set() if args.all else load_seen()
    fresh = [p for p in picks if key_of(p) not in seen]

    if not fresh:
        print("Nothing new.")
        return 0

    print()
    for pick in sorted(fresh, key=lambda p: (p["date"], p["curator"])):
        print(f"  {describe(pick)}")
    print()
    print(f"{len(fresh)} new pick{'s' if len(fresh) != 1 else ''}.")

    if not args.dry_run and not args.all:
        save_seen(seen | {key_of(p) for p in fresh})

    return 0


if __name__ == "__main__":
    sys.exit(main())
