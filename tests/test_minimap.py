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
    """A 1440 map drawn in the home box: its view outline 24 x 12 x 1200/1440."""
    pts = points_from(minimap.scaled_prior(1440), grid_tiles(100, 1300))
    items = fake_items(monkeypatch, pts, size_px=(20, 10))
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


@pytest.mark.parametrize("dx,dy", [(0.0, -0.95), (1.5, -2.0)])
def test_a_notch_of_zoom_is_a_shift_the_prior_takes(monkeypatch, dx, dy):
    """Where the camera point sits in the outline moves with the zoom -- by
    (-0.08, -0.95) px a notch wider on the 14:50 trip. A shift is measured
    and taken, not refused."""
    pts = [(x, y, px + dx, py + dy) for x, y, px, py in
           points_from(minimap.HOME_H, grid_tiles(100, 1100))]
    items = fake_items(monkeypatch, pts, size_px=(30, 15), map_id="4096")
    H, how, err = minimap.calibrate(items, "4096", 1200)
    assert how.startswith("home calibration") and err < 0.01, how
    assert f"{dx:+.2f},{dy:+.2f}" in how
    # the provinces keep the minimap's own geometry: the prior, not shifted
    assert np.allclose(H, minimap.scaled_prior(1200))


def test_a_wrong_size_is_not_a_shift(monkeypatch):
    """A map drawn at 1200's scale though called 1440: the miss grows
    across the map, no shift takes it away -- a fit of its own instead."""
    pts = points_from(minimap.HOME_H, grid_tiles(150, 1250))
    items = fake_items(monkeypatch, pts, map_id="S20001")
    _H, how, _ = minimap.calibrate(items, "S20001", 1440)
    assert not how.startswith("home calibration"), how


def test_outlines_cut_by_an_edge_do_not_count(monkeypatch):
    """Near an edge the map's edge cuts the view outline and its centroid
    moves inward (4-5 px at the east edge, 14:50): such outlines, however
    many, must not decide the calibration."""
    good = points_from(minimap.HOME_H, grid_tiles(300, 900, n=3))
    cut = [(x, y, px - 4.5, py) for x, y, px, py in
           points_from(minimap.HOME_H, [(1150, y) for y in range(200, 1000, 50)])]
    items = fake_items(monkeypatch, good + cut, map_id="4096")
    H, how, err = minimap.calibrate(items, "4096", 1200)
    assert how.startswith("home calibration") and err < 0.01, how


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
    monkeypatch.setattr(minimap, "segment", lambda m, *a: (
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


def test_the_prior_is_checked_at_the_outline_size_of_the_map(monkeypatch):
    """A 2400 map drawn in the home box shows the widest readable view at
    half the size: 12 x 6, not 24 x 12."""
    pts = points_from(minimap.scaled_prior(2400), grid_tiles(200, 2200))
    items = fake_items(monkeypatch, pts, size_px=(12, 6))
    H, how, _ = minimap.calibrate(items, "S20001", 2400)
    assert H is not None and how.startswith("home calibration")


def test_agreement_does_not_care_how_provinces_are_numbered():
    a = np.array([[1, 1, 2, 2], [1, 1, 2, 2]])
    assert minimap.agreement(a, 3 - a) == 1.0
    merged = np.ones_like(a)
    assert minimap.agreement(merged, a) == 0.5 == minimap.agreement(a, merged)


def night_minimap():
    """A see-through minimap over a light background: the land is not dark,
    four provinces split by a bright cross, drawn inside HOME_H's square."""
    img = np.full((215, 384, 3), (150, 140, 150), np.uint8)
    quad = cv2.perspectiveTransform(
        np.float32([[[0, 0], [1200, 0], [1200, 1200], [0, 1200]]]), minimap.HOME_H)[0]
    cv2.fillPoly(img, [np.round(quad).astype(np.int32)], (140, 130, 125))
    c = cv2.perspectiveTransform(np.float32([[[600, 600]]]), minimap.HOME_H)[0, 0]
    cv2.line(img, (int(c[0]), 0), (int(c[0]), 214), (230, 230, 230), 1)
    cv2.line(img, (0, int(c[1])), (383, int(c[1])), (230, 230, 230), 1)
    return img


def test_a_minimap_whose_land_is_not_dark_is_split_by_the_map_square():
    """2026-09-24 14:50, night theme: the dark-land mask ran round the
    panel's margin and joined the rim provinces. The calibrated square
    does not care what colour the land is."""
    img = night_minimap()
    labels_dark, _ = minimap.segment(img)
    labels_sq, _ = minimap.segment(img, minimap.HOME_H, 1200)
    assert labels_dark.max() != 4
    assert labels_sq.max() == 4


NIGHT = ROOT / "screenshots" / "map_edge" / "20260924_145045"


@pytest.mark.skipif(not (NIGHT.exists() and SURVEY.exists()),
                    reason="the home kingdom's day and night crops are not on this machine")
def test_day_and_night_give_the_same_ten_provinces():
    import json

    def items(folder, key):
        meta = json.loads((folder / key).read_text(encoding="utf-8"))
        rows = meta.get("reads") or meta.get("frames")
        return [(cv2.imread(str(folder / r[0])), tuple(r[1])) for r in rows if r[1]]
    day = minimap.build(items(SURVEY, "survey.json"), "4096", 1200, city=(577, 615))
    night = minimap.build(items(NIGHT, "probe.json"), "4096", 1200, city=(577, 615))
    assert day["provinces"] == night["provinces"] == 10
    assert night["how"].startswith("home calibration"), night["how"]
    assert minimap.agreement(day["grid"], night["grid"]) > 0.98


BACKUP = ROOT / "data" / "map_knowledge" / "backup_20260924" / "4096_provinces.png"


@pytest.mark.skipif(not (NIGHT.exists() and BACKUP.exists()),
                    reason="the 14:50 trip and the saved split are not on this machine")
def test_the_first_build_of_the_14_50_trip_needs_no_spread_walk():
    """The walks' crops alone (the zoom's left out), a notch wider than the
    survey and by night: the shifted prior takes them, 10 provinces."""
    import json
    meta = json.loads((NIGHT / "probe.json").read_text(encoding="utf-8"))
    zoom = 1 + meta["notches_out"] + meta["notches_in"]
    items = [(cv2.imread(str(NIGHT / n)), tuple(h)) for n, h in meta["frames"][zoom:30] if h]
    res = minimap.build(items, "4096", 1200, city=(577, 615))
    assert res.get("provinces") == 10, res.get("error")
    assert res["how"].startswith("home calibration")
    saved = cv2.imread(str(BACKUP), cv2.IMREAD_UNCHANGED)
    assert minimap.agreement(res["grid"], saved) > 0.95


def test_an_outline_that_stays_on_one_spot_is_not_a_province_line():
    """3560, 2026-09-24 21:31: the city 86 tiles from the east edge, so half
    the survey's crops had the view outline on one minimap row; the plain
    median kept its edge as a line and cut a province in two (11, not 10)."""
    base = night_minimap()
    spots = [(1000, 300)] * 7 + [(250, 200), (400, 350), (850, 900), (1000, 1050),
                                 (300, 950)]
    crops = []
    for x, y in spots:
        c = base.copy()
        cx, cy = cv2.perspectiveTransform(np.float32([[[x, y]]]), minimap.HOME_H)[0, 0]
        cv2.rectangle(c, (int(cx) - 12, int(cy) - 6), (int(cx) + 12, int(cy) + 6),
                      (255, 255, 255), 1)
        crops.append(c)
    plain = np.median(np.stack(crops), axis=0).astype(np.uint8)
    assert minimap.segment(plain, minimap.HOME_H, 1200)[0].max() > 4, (
        "the fake no longer reproduces the extra province")
    labels, _ = minimap.segment(minimap.median_minimap(crops), minimap.HOME_H, 1200)
    assert labels.max() == 4
