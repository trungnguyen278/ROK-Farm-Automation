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


# --- reach on the pictures -------------------------------------------------
# 3560, 2026-09-25, the operator on !map: the city sits by its zone's edge and
# the minimap's line put it in the zone above, which it cannot enter. The
# pictures now show what the farm decides, from where its marches went.

def _edge_book(tmp_path, monkeypatch):
    import cv2
    import numpy as np
    import rok_farm.map_memory as mm
    monkeypatch.setattr(reports, "BOOKS", tmp_path)
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    grid = np.full((150, 150), 6, np.uint8)
    grid[:504 // 8, :] = 2                      # the minimap's line, 50 tiles south
    cv2.imwrite(str(tmp_path / "3560_provinces.png"), grid)
    now = time.time()
    city = [1113, 548]
    # The book's own marches from that morning: most went deep in the zone
    # below, a few in the band between the minimap's line and the pass.
    went = [(1114, 531), (1085, 536), (1108, 536), (1117, 484), (1135, 514),
            (1101, 478), (1066, 485), (1115, 491), (1128, 466), (1103, 488),
            (1110, 425), (1108, 476), (1121, 448)]
    refused = [(1081, 563), (1087, 576), (1137, 581), (1080, 568), (1114, 601)]
    return {"map_id": "3560", "city": city, "size": 1200,
            "track": [[int(now - 60 + k), 1113, 548 - k] for k in range(5)],
            "reached": [{"x": x, "y": y, "t": now, "city": city} for x, y in went],
            "unreachable": [{"x": x, "y": y, "t": now, "city": city, "pass": [1126, 554]}
                            for x, y in refused]}


def test_the_picture_closes_what_the_farm_closes(tmp_path, monkeypatch):
    book = _edge_book(tmp_path, monkeypatch)
    mem = reports.reach_book(book, reports.province_grid(book))
    closed = reports.closed_cells(mem, (1113, 548), 900, 350, 400)
    assert (1100 // 8, 590 // 8) in closed, "past the pass"
    assert (1113 // 8, 548 // 8) not in closed, "the city's own ground"
    assert (1100 // 8, 548 // 8) not in closed
    assert reports.city_label(mem, (1113, 548)) == "city: P2 (minimap said P6)"


def test_the_map_hatches_closed_ground_only_when_there_is_some(tmp_path, monkeypatch):
    import cv2
    import numpy as np
    book = _edge_book(tmp_path, monkeypatch)

    def closed_px(b):
        png, _ = reports.book_map(time.strftime("%Y-%m-%d"), book=b, px=2,
                                  log=tmp_path / "none.log")
        img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        return int((np.abs(img.astype(int) - reports._CLOSED).sum(axis=2) < 10).sum())
    assert closed_px(book) > 50
    assert closed_px(dict(book, unreachable=[])) == 0


def test_the_lines_are_drawn_where_the_marches_put_them(tmp_path, monkeypatch):
    """The operator on !map: the purple line still put the city in the zone
    above. Round the city the picture's grid follows the marches."""
    book = _edge_book(tmp_path, monkeypatch)
    grid = reports.province_grid(book)
    mem = reports.reach_book(book, grid)
    shown = reports.display_grid(grid, mem, (1113, 548), 913, 348, 400)
    at = lambda x, y: int(shown[y // 8, x // 8])
    assert grid[548 // 8, 1113 // 8] == 6, "the minimap's line puts the city above"
    assert at(1113, 548) == 2 and at(1100, 530) == 2, "the city's side"
    assert at(1100, 590) == 6, "past the pass"
    assert at(1000, 300) == int(grid[300 // 8, 1000 // 8]), "far from any march: the grid"
