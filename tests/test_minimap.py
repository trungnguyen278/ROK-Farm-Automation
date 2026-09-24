"""The minimap into tiles and provinces (rok_farm.minimap).

The home kingdom's calibration (HOME_H, 43 reads, 0.20 px) is taken for
another map when, scaled to that map's size, it places the map's own view
outlines within PRIOR_OK_PX; else a fit of the map's own, only from enough
outlines spread over the map. These tests feed it outline points made from
known homographies, and -- where this machine has it -- the survey the home
kingdom's provinces came from.
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from rok_farm import minimap

ROOT = Path(__file__).resolve().parents[1]
SURVEY = ROOT / "screenshots" / "minimap_survey" / "20260924_131855"


def points_from(H, tiles):
    src = np.float32(tiles)
    dst = cv2.perspectiveTransform(src[None], np.asarray(H, np.float64))[0]
    return [(x, y, float(px), float(py)) for (x, y), (px, py) in zip(tiles, dst)]


def grid_tiles(lo, hi, n=6):
    return [(int(x), int(y)) for x in np.linspace(lo, hi, n) for y in np.linspace(lo, hi, n)]


def test_the_home_calibration_places_its_own_outlines():
    pts = points_from(minimap.HOME_H, grid_tiles(100, 1100))
    assert minimap.residual(minimap.scaled_prior(1200), pts) < 1e-3


def test_a_map_twice_the_size_scales_the_home_calibration():
    """If the minimap draws every map in the same box, a 2400 map's tile
    (2x, 2y) sits where the home kingdom's (x, y) does."""
    H = minimap.scaled_prior(2400)
    a = cv2.perspectiveTransform(np.float32([[[1000, 800]]]), H)[0, 0]
    b = cv2.perspectiveTransform(np.float32([[[500, 400]]]), minimap.HOME_H)[0, 0]
    assert np.allclose(a, b, atol=1e-6)


def fake_items(monkeypatch, pts, size_px=(24, 12), map_id="S20001"):
    """(crop, hud) pairs whose outline() answers the given points."""
    table = {}
    items = []
    for k, (x, y, px, py) in enumerate(pts):
        crop = np.full((4, 4, 3), k % 256, np.uint8)
        crop[0, 0, 0] = k // 256
        table[(k % 256, k // 256)] = (px, py) + tuple(size_px)
        items.append((crop, (map_id, x, y)))
    monkeypatch.setattr(minimap, "outline",
                        lambda c: table.get((int(c[1, 1, 0]), int(c[0, 0, 0]))))
    return items


def test_the_prior_is_taken_where_it_fits(monkeypatch):
    pts = points_from(minimap.scaled_prior(1440), grid_tiles(100, 1300))
    items = fake_items(monkeypatch, pts)
    H, how, err = minimap.calibrate(items, "S20001", 1440)
    assert H is not None and how.startswith("home calibration") and err < 0.01


def test_a_map_drawn_otherwise_gets_its_own_fit(monkeypatch):
    """Drawn at the home kingdom's scale though 1440 a side: the scaled
    prior misses, the map's own spread outlines fit."""
    pts = points_from(minimap.HOME_H, grid_tiles(100, 1300))
    items = fake_items(monkeypatch, pts)
    H, how, err = minimap.calibrate(items, "S20001", 1440)
    assert H is not None and how.startswith("fitted") and err < 0.05


def test_outlines_in_one_corner_are_not_a_calibration(monkeypatch):
    """The north-east quarter alone put the home kingdom's far corners
    30-40 tiles off: not spread, no fit."""
    pts = points_from(minimap.HOME_H, grid_tiles(900, 1300))
    items = fake_items(monkeypatch, pts)
    H, how, _ = minimap.calibrate(items, "S20001", 1440)
    assert H is None and "spread" in how


def test_too_few_outlines_are_not_a_calibration(monkeypatch):
    pts = points_from(minimap.HOME_H, grid_tiles(100, 1300, n=3))
    items = fake_items(monkeypatch, pts)
    H, how, _ = minimap.calibrate(items, "S20001", 1440)
    assert H is None and "needed" in how


def test_outlines_at_another_zoom_do_not_test_the_prior(monkeypatch):
    """Where the camera point sits in the outline moves with the zoom: the
    prior is only checked at the zoom it was measured at."""
    pts = points_from(minimap.scaled_prior(1440), grid_tiles(100, 1300))
    items = fake_items(monkeypatch, pts, size_px=(40, 20))
    _H, how, _ = minimap.calibrate(items, "S20001", 1440)
    assert not how.startswith("home calibration")


def test_the_tile_grid_reads_the_province_under_each_cell():
    labels = np.zeros((100, 100), np.int32)
    labels[:, :50] = 1
    labels[:, 52:] = 2                       # a line between, at columns 50-51
    H = np.diag([100 / 1200.0, 100 / 1200.0, 1.0])
    grid = minimap.tile_grid(labels, H, size=1200)
    assert grid.shape == (150, 150)
    assert grid[10, 10] == 1 and grid[10, 140] == 2
    assert (grid > 0).all(), "a cell on the line takes the nearest province"


def test_build_refuses_a_city_off_the_map(monkeypatch):
    """Every cell of the map takes its nearest province, so a city in none
    is a city not on the map -- a misread, or the wrong map."""
    monkeypatch.setattr(minimap, "calibrate", lambda *a: (np.eye(3), "t", 0.0))
    monkeypatch.setattr(minimap, "segment", lambda m: (
        np.pad(np.ones((50, 50), np.int32), ((0, 50), (0, 50))) * 1
        + np.pad(np.ones((50, 50), np.int32), ((50, 0), (50, 0))) * 2,
        np.zeros((100, 100), np.uint8)))
    items = [(np.zeros((100, 100, 3), np.uint8), ("S20001", 5, 5))] * 8
    ok = minimap.build(items, "S20001", 96, city=(10, 10))
    assert "grid" in ok and ok["provinces"] == 2
    bad = minimap.build(items, "S20001", 96, city=(200, 10))
    assert bad.get("stage") == "city"


def test_build_says_which_stage_failed(monkeypatch):
    few = [(np.zeros((4, 4, 3), np.uint8), ("S20001", 5, 5))] * 3
    assert minimap.build(few, "S20001", 1440)["stage"] == "crops"
    monkeypatch.setattr(minimap, "calibrate", lambda *a: (None, "no fit", None))
    many = few * 4
    assert minimap.build(many, "S20001", 1440)["stage"] == "calibrate"


def test_saved_provinces_are_what_the_book_reads(tmp_path, monkeypatch):
    from rok_farm import map_memory as mm
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    grid = np.zeros((180, 180), np.int32)
    grid[:, :90], grid[:, 90:] = 1, 2
    minimap.save({"grid": grid, "H": np.eye(3).tolist(), "how": "t", "fit_px": 0.1,
                  "crops": 9}, "S20001")
    b = mm.MapMemory("S20001")
    assert b.has_provinces()
    assert b.province_of(100, 700) == 1 and b.province_of(1400, 700) == 2


@pytest.mark.skipif(not SURVEY.exists(), reason="the home kingdom's survey is not on this machine")
def test_the_home_survey_gives_ten_provinces_and_the_city_in_the_centre():
    import json
    meta = json.loads((SURVEY / "survey.json").read_text(encoding="utf-8"))
    items = [(cv2.imread(str(SURVEY / n)), tuple(h)) for n, h in meta["reads"] if h]
    res = minimap.build(items, "4096", 1200, city=(577, 615))
    assert res["provinces"] == 10
    assert res["how"].startswith("home calibration") and res["fit_px"] < 0.3
    grid = res["grid"]
    ids, counts = np.unique(grid[grid > 0], return_counts=True)
    assert grid[615 // 8, 577 // 8] == ids[np.argmin(counts)]
