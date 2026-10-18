"""core/listens.py: months per artist, from two sources that disagree in shape.

The examples are the real ones from the 2026-05 export, because each is a case
that was got wrong once:

  "j milo"                 the credit LINE for a Milo j & Trueno track. Using
                           it as the artist name invents an artist and loses
                           two real ones -- mbid_mapping.artists has both.
  "Jorge Drexler" twice    the stats API splits an artist whenever a listen
                           went unmapped, so one month holds him with an mbid
                           (218 plays) and without one (38). 59 of 130 such
                           rows folded back.
  "Maria José Llergo"      same artist as "María José Llergo", different row,
                           because the accent differs.
  Mogwai                   58 lifetime months, 3 of the last 24. Plays cannot
                           tell him from a current taste; months can.
"""

from __future__ import annotations

import json
import zipfile

import core.listens as mod


def listen(stamp, artists=None, credit_line="Someone", mapped=True):
    """One export listen. `artists` is [(mbid, name)], as mbid_mapping carries."""
    meta = {"artist_name": credit_line}
    if mapped:
        pairs = artists or [("mbid-1", credit_line)]
        meta["mbid_mapping"] = {
            "artist_mbids": [m for m, _ in pairs],
            "artists": [{"artist_mbid": m, "artist_credit_name": n} for m, n in pairs],
        }
    return json.dumps({"listened_at": stamp, "track_metadata": meta})


def export(tmp_path, rows):
    """A zip in the export's own layout: listens/<year>/<month>.jsonl."""
    path = tmp_path / "listenbrainz_test.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("user.json", "{}")
        for name, lines in rows.items():
            zf.writestr(f"listens/{name}.jsonl", "\n".join(lines) + "\n")
    return path


def month(rows):
    """Shorthand for the per-month row list the profile reads."""
    return [{"mbid": m, "name": n, "plays": p} for m, n, p in rows]


# ---- index --------------------------------------------------------------


def test_month_arithmetic_crosses_a_year_boundary():
    assert mod.index("2026-01") - mod.index("2025-12") == 1
    assert mod.index("2026-05") - mod.index("2024-05") == 24


# ---- read_export --------------------------------------------------------


def test_a_collaboration_counts_for_every_credited_artist(tmp_path):
    """The "j milo" case: one listen, two artists, neither named by the line."""
    path = export(tmp_path, {"2026/5": [
        listen(1777000000, [("mb-milo", "Milo j"), ("mb-trueno", "Trueno")],
               credit_line="j milo")]})
    months = mod.read_export(path)
    rows = {r["name"]: r for r in months["2026-04"]}
    assert set(rows) == {"Milo j", "Trueno"}
    assert rows["Milo j"]["mbid"] == "mb-milo"
    assert rows["Milo j"]["plays"] == 1
    assert "j milo" not in rows


def test_a_listen_with_no_mapping_falls_back_to_the_credit_line(tmp_path):
    """7.4% of listens carry no mbid_mapping at all; they are not dropped."""
    path = export(tmp_path, {"2026/5": [
        listen(1777000000, credit_line="Rita Payes", mapped=False)]})
    rows = mod.read_export(path)["2026-04"]
    assert rows == [{"mbid": None, "name": "Rita Payes", "plays": 1}]


def test_listens_group_by_the_month_they_happened_not_the_file_they_are_in(tmp_path):
    """The file name is not authoritative -- the timestamp is."""
    path = export(tmp_path, {"2026/5": [listen(1777000000), listen(1764000000)]})
    months = mod.read_export(path)
    assert sorted(months) == ["2025-11", "2026-04"]


def test_a_listen_with_no_timestamp_is_skipped(tmp_path):
    path = tmp_path / "z.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("listens/2026/5.jsonl",
                    json.dumps({"track_metadata": {"artist_name": "X"}}) + "\n")
    assert mod.read_export(path) == {}


def test_unreadable_lines_and_non_listen_files_are_ignored(tmp_path):
    path = tmp_path / "z.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("user.json", '{"not": "a listen"}')
        zf.writestr("listens/2026/5.jsonl", "{broken\n\n" + listen(1777000000) + "\n")
    assert len(mod.read_export(path)["2026-04"]) == 1


def test_the_name_kept_is_the_spelling_with_the_most_plays(tmp_path):
    """"María" over "Maria" when it carries more listens, not whichever came first."""
    path = export(tmp_path, {"2026/5": [
        listen(1777000000, [("mb-l", "Maria Jose Llergo")]),
        listen(1777000001, [("mb-l", "María José Llergo")]),
        listen(1777000002, [("mb-l", "María José Llergo")]),
    ]})
    rows = mod.read_export(path)["2026-04"]
    assert rows == [{"mbid": "mb-l", "name": "María José Llergo", "plays": 3}]


# ---- from_stats ---------------------------------------------------------


def test_the_month_is_the_window_asked_for_not_the_day_it_ran():
    """`range=month` is a calendar month; its to_ts is the EXCLUSIVE end, so
    2026-09-01 -> 2026-10-01 is September and must not be labelled October."""
    payload = {"payload": {"from_ts": 1788220800, "to_ts": 1790812800,
                           "artists": [{"artist_mbid": "mb-1", "artist_name": "A",
                                        "listen_count": 7}]}}
    assert mod.from_stats(payload) == ("2026-09", [{"mbid": "mb-1", "name": "A",
                                                   "plays": 7}])


def test_from_stats_accepts_a_bare_payload_and_an_empty_one():
    assert mod.from_stats({"from_ts": 1788220800, "artists": []}) == ("2026-09", [])


def test_a_stats_row_without_an_mbid_keeps_its_name():
    payload = {"payload": {"from_ts": 1788220800,
                           "artists": [{"artist_name": "j milo", "listen_count": 14}]}}
    _, rows = mod.from_stats(payload)
    assert rows == [{"mbid": None, "name": "j milo", "plays": 14}]


# ---- write_month / read_months ------------------------------------------


def test_a_month_round_trips_through_its_own_file(tmp_path):
    mod.write_month("2026-09", month([("mb-1", "A", 3)]), "stats", tmp_path)
    assert mod.read_months(tmp_path) == {"2026-09": [{"mbid": "mb-1", "name": "A",
                                                     "plays": 3}]}


def test_a_month_nobody_fetched_is_simply_absent(tmp_path):
    """One file per month on purpose: a hole is visible rather than inferred."""
    mod.write_month("2026-07", month([("mb-1", "A", 1)]), "stats", tmp_path)
    mod.write_month("2026-09", month([("mb-1", "A", 1)]), "stats", tmp_path)
    assert sorted(mod.read_months(tmp_path)) == ["2026-07", "2026-09"]


def test_read_months_ignores_files_that_are_not_months(tmp_path):
    mod.write_month("2026-09", month([("mb-1", "A", 1)]), "stats", tmp_path)
    (tmp_path / "notes.json").write_text("{}")
    assert list(mod.read_months(tmp_path)) == ["2026-09"]


def test_an_empty_directory_profiles_to_nothing(tmp_path):
    assert mod.read_months(tmp_path) == {}


# ---- fold ---------------------------------------------------------------


def test_a_name_only_row_takes_the_mbid_that_spelling_has_elsewhere():
    """The Drexler case: two rows in one month, one mapped, one not."""
    folded = mod.fold({"2026-09": month([("mb-drexler", "Jorge Drexler", 218),
                                         (None, "Jorge Drexler", 38)])})
    assert folded["2026-09"] == [{"mbid": "mb-drexler", "name": "Jorge Drexler",
                                 "plays": 256}]


def test_folding_adds_the_plays_rather_than_keeping_the_larger_row():
    folded = mod.fold({"2026-09": month([("mb-1", "A", 10), (None, "A", 5)])})
    assert folded["2026-09"][0]["plays"] == 15


def test_an_mbid_learned_in_one_month_resolves_a_bare_name_in_another():
    folded = mod.fold({"2025-01": month([("mb-1", "Marc Ribot", 40)]),
                       "2026-09": month([(None, "Marc Ribot", 75)])})
    assert folded["2026-09"] == [{"mbid": "mb-1", "name": "Marc Ribot", "plays": 75}]


def test_accents_fold_together_because_the_key_is_normalised():
    folded = mod.fold({"2026-09": month([("mb-l", "María José Llergo", 114),
                                         (None, "Maria José Llergo", 24)])})
    assert len(folded["2026-09"]) == 1
    assert folded["2026-09"][0]["plays"] == 138


def test_an_artist_nobody_ever_mapped_keeps_a_name_key_and_is_not_dropped():
    folded = mod.fold({"2026-09": month([(None, "j milo", 14)])})
    assert folded["2026-09"] == [{"mbid": None, "name": "j milo", "plays": 14}]


def test_two_different_artists_sharing_no_spelling_stay_apart():
    folded = mod.fold({"2026-09": month([("mb-1", "A", 1), ("mb-2", "B", 1)])})
    assert len(folded["2026-09"]) == 2


# ---- profile ------------------------------------------------------------


def test_months_are_counted_distinctly_and_plays_are_summed():
    """The whole point: 50 plays in one month is one active month."""
    rows = mod.profile({"2026-04": month([("mb-1", "A", 40)]),
                        "2026-05": month([("mb-1", "A", 10)])}, "2026-05", 24)
    assert (rows[0].months, rows[0].plays) == (2, 50)


def test_the_window_counts_back_from_now_and_excludes_its_far_edge():
    """A month exactly `window` back is outside -- 24 means the last 24, not 25."""
    months = {"2024-05": month([("mb-1", "A", 1)]),      # exactly 24 back
              "2024-06": month([("mb-1", "A", 1)]),      # 23 back, inside
              "2026-05": month([("mb-1", "A", 1)])}
    row = mod.profile(months, "2026-05", 24)[0]
    assert (row.months, row.recent) == (3, 2)


def test_a_month_after_now_does_not_count_as_recent():
    months = {"2026-09": month([("mb-1", "A", 5)]),
              "2026-05": month([("mb-1", "A", 5)])}
    row = mod.profile(months, "2026-05", 24)[0]
    assert (row.months, row.recent) == (2, 1)


def test_recent_plays_counts_only_what_happened_inside_the_window():
    """Omar's case: few recent months, but a burst of plays inside them."""
    months = {"2013-01": month([("mb-1", "A", 500)]),
              "2026-05": month([("mb-1", "A", 163)])}
    row = mod.profile(months, "2026-05", 24)[0]
    assert (row.plays, row.recent_plays) == (663, 163)


def test_first_and_last_span_the_whole_history():
    months = {"2013-04": month([("mb-1", "Mogwai", 1)]),
              "2025-05": month([("mb-1", "Mogwai", 1)])}
    row = mod.profile(months, "2026-05", 24)[0]
    assert (row.first, row.last) == ("2013-04", "2025-05")


def test_an_artist_with_no_mbid_gets_a_name_key_distinct_from_an_mbid_one():
    rows = {r.key: r for r in mod.profile(
        {"2026-05": month([("mb-1", "A", 1), (None, "B", 1)])}, "2026-05", 24)}
    assert set(rows) == {"mb-1", "name:b"}
    assert rows["name:b"].mbid is None


def test_the_profile_name_is_the_spelling_with_the_most_plays():
    months = {"2025-01": month([("mb-1", "Maria Jose Llergo", 2)]),
              "2026-05": month([("mb-1", "María José Llergo", 9)])}
    assert mod.profile(months, "2026-05", 24)[0].name == "María José Llergo"


def test_mogwai_is_deep_and_not_current_while_drexler_is_both():
    """The two shapes the bands exist to separate, as measured."""
    months = {f"2013-{m:02d}": month([("mb-mog", "Mogwai", 20)]) for m in range(1, 13)}
    months["2025-05"] = month([("mb-mog", "Mogwai", 1)])
    for m in range(1, 13):                       # same months, both artists
        months.setdefault(f"2025-{m:02d}", []).append(
            {"mbid": "mb-dre", "name": "Jorge Drexler", "plays": 50})
    rows = {r.name: r for r in mod.profile(months, "2026-05", 24)}
    assert (rows["Mogwai"].months, rows["Mogwai"].recent) == (13, 1)
    assert (rows["Jorge Drexler"].months, rows["Jorge Drexler"].recent) == (12, 12)


def test_a_credit_with_neither_an_mbid_nor_a_name_is_dropped(tmp_path):
    """Guards against inventing an artist keyed "name:" off an empty credit."""
    path = tmp_path / "z.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("listens/2026/5.jsonl", json.dumps({
            "listened_at": 1777000000,
            "track_metadata": {"artist_name": "X", "mbid_mapping": {
                "artists": [{"artist_mbid": None, "artist_credit_name": ""},
                            {"artist_mbid": "mb-1", "artist_credit_name": "Real"}]}}}) + "\n")
    assert mod.read_export(path)["2026-04"] == [{"mbid": "mb-1", "name": "Real",
                                                "plays": 1}]
