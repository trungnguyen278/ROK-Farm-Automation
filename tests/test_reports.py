"""The reports the Discord bot shows: numbers, periods, pictures."""

import time

import pytest

from rok_farm import reports


def test_the_flow_constants_are_the_flows():
    """reports repeats a few flow constants so the bot never imports the
    flow (that builds the OCR engine). They must not drift apart."""
    from rok_farm.flow_steps import GemFlowMixin
    from rok_farm.map_memory import CELL
    assert reports.CELL == CELL
    assert reports.VIEW_MARGIN == GemFlowMixin.VIEW_MARGIN
    assert reports.SWEEP_RADIUS == GemFlowMixin.SWEEP_RADIUS_TILES
    assert reports.SWEEP_STALE_H == GemFlowMixin.SWEEP_STALE_H


NOW = time.mktime(time.strptime("2026-09-24 11:05", "%Y-%m-%d %H:%M"))


@pytest.mark.parametrize("args,want", [
    ([], "2026-09-23 00:00"),
    (["today"], "2026-09-24 00:00"),
    (["yesterday"], "2026-09-23 00:00"),
    (["24h"], "2026-09-23 11:05"),
    (["2d"], "2026-09-23 00:00"),
    (["7d"], "2026-09-18 00:00"),
    (["all"], "2000-01-01 00:00"),
    (["2026-09-20"], "2026-09-20 00:00"),
    (["09-21"], "2026-09-21 00:00"),
    (["bogus"], "2026-09-23 00:00"),
])
def test_periods_as_typed_on_discord(args, want):
    assert reports.parse_since(args, now=NOW) == want


LOG = """\
2026-09-24 08:00:00,000 [INFO   ] gem_farm_test: Gem counter starts at 1000
2026-09-24 08:10:00,000 [INFO   ] gem_farm_test: Deploy panel: march=200s bonuses=[1.0] troops=1/2 load=20
2026-09-24 08:20:00,000 [INFO   ] gem_farm_test: Gems now 1020 (+20 since start)
2026-09-24 08:40:00,000 [INFO   ] gem_farm_test: Gems now 1030 (+30 since start)
2026-09-24 08:50:00,000 [INFO   ] gem_farm_test: Gems now 630 (-370 since start)
2026-09-24 09:00:00,000 [INFO   ] gem_farm_test: Gems now 650 (-350 since start)
2026-09-24 09:10:00,000 [INFO   ] gem_farm_test: Gems now 950 (-50 since start)
2026-09-24 11:30:00,000 [INFO   ] gem_farm_test: Gems now 960 (-40 since start)
"""


@pytest.fixture
def log(tmp_path):
    p = tmp_path / "farm_run.log"
    p.write_text(LOG, encoding="utf-8")
    return p


def test_spending_never_counts_against_the_farm(log):
    """-400 spent at 08:50: left out, not subtracted. +300 at 09:10 is no
    march (they carry 10-20): listed, not counted. The 11:30 reading is
    2h20 after the last -- not one running farm, so not counted either."""
    r = reports.gem_rate("2026-09-24", log=log)
    assert r.gems == 20 + 10 + 20
    assert r.hours == pytest.approx(70 / 60)
    assert [d for _w, d in r.falls] == [-400]
    assert [d for _w, d in r.odd] == [300]
    assert r.marched[8] == 20


def test_the_embed_says_what_was_left_out(log):
    spec = reports.stats_spec(reports.gem_rate("2026-09-24", log=log))
    left = dict((n, v) for n, v, _i in spec["fields"])["Left out"]
    assert "-400" in left and "rise" in left
    assert spec["image"] == "gem_rate.png"


def test_an_empty_period_says_so(log):
    spec = reports.stats_spec(reports.gem_rate("2026-09-25", log=log))
    assert "No readings" in spec["description"] and spec["image"] is None


def test_the_chart_is_a_png(log):
    png = reports.rate_chart(reports.gem_rate("2026-09-24", log=log))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def _book(start):
    track = [[int(start + 5 * k), 577 + 10 * k, 615] for k in range(8)]
    return {"city": [577, 615], "track": track, "reach": {}}


def test_the_map_draws_a_period_of_the_track(tmp_path):
    start = time.mktime(time.strptime("2026-09-24 09:00", "%Y-%m-%d %H:%M"))
    png, s = reports.book_map("2026-09-24 08:00", book=_book(start), px=1,
                              log=tmp_path / "none.log")
    assert png[:4] == b"\x89PNG" and s["views"] == 8
    assert reports.map_spec(s, "today")["image"] == "map.png"


def test_a_run_is_drawn_and_counted(tmp_path):
    start = time.mktime(time.strptime("2026-09-24 09:00", "%Y-%m-%d %H:%M"))
    run = (start - 1, start + 60, [(start + 20, "march", (607, 615)),
                                  (start + 30, "done", 1)])
    png, s = reports.run_map(run, 1, book=_book(start), px=2)
    assert png[:4] == b"\x89PNG"
    assert s["views"] == 8 and s["marches"] == 1 and s["crossings"] == 0
    assert s["farthest"] == 70
    spec = reports.run_spec(s, 1)
    assert spec["image"] == "run.png" and spec["title"].startswith("Run 1:")


# --- provinces on the pictures ---------------------------------------------

def _purple(png):
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    b, g, r = img[..., 0].astype(int), img[..., 1].astype(int), img[..., 2].astype(int)
    return int(((abs(b - 150) < 8) & (abs(g - 50) < 8) & (abs(r - 150) < 8)).sum())


def _survey(folder, map_id="4096"):
    import cv2
    import numpy as np
    grid = np.full((150, 150), 1, np.uint8)
    grid[:, 75:] = 2                         # a border at X 600
    cv2.imwrite(str(folder / f"{map_id}_provinces.png"), grid)


def test_the_pictures_draw_the_province_borders_when_the_map_has_them(tmp_path, monkeypatch):
    """The operator, 2026-09-24: put the zones we worked out on the scan
    pictures."""
    monkeypatch.setattr(reports, "BOOKS", tmp_path)
    start = time.mktime(time.strptime("2026-09-24 09:00", "%Y-%m-%d %H:%M"))
    run = (start - 1, start + 60, [(start + 30, "done", 1)])
    book = dict(_book(start), map_id="4096")
    plain_run, _ = reports.run_map(run, 1, book=book, px=2)
    plain_map, _ = reports.book_map("2026-09-24 08:00", book=book, px=1,
                                    log=tmp_path / "none.log")
    assert _purple(plain_run) == 0 and _purple(plain_map) == 0
    _survey(tmp_path)
    run_png, _ = reports.run_map(run, 1, book=book, px=2)
    map_png, _ = reports.book_map("2026-09-24 08:00", book=book, px=1,
                                  log=tmp_path / "none.log")
    assert _purple(run_png) > 100 and _purple(map_png) > 100


def test_the_active_book_is_a_book_not_its_provinces(tmp_path, monkeypatch):
    """A survey writes <map>_provinces.json after the book: for a while the
    newest .json in the folder, and !map drew it as the book."""
    import os
    monkeypatch.setattr(reports, "BOOKS", tmp_path)
    book = tmp_path / "4096.json"
    book.write_text('{"city": [577, 615], "track": []}', encoding="utf-8")
    old = tmp_path / "4096.before-clean-20260923-162029.json"
    old.write_text("{}", encoding="utf-8")
    prov = tmp_path / "4096_provinces.json"
    prov.write_text('{"provinces": 10}', encoding="utf-8")
    t = time.time()
    os.utime(book, (t - 60, t - 60))
    assert reports.active_book() == book
    loaded = reports.load_book()
    assert loaded["map_id"] == "4096" and loaded["city"] == [577, 615]
