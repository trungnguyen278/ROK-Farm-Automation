"""A map's size comes from its id: a kingdom's own map is 1200, a KvK map is
learned.

Everything used to assume 1200 tiles a side. On a KvK map (id #S11465,
2026-09-09..18) that is only a guess: KvK maps are 1200, 1440 or 2400 by
type, and a HUD read of X 1300 would have been thrown away as a misread --
every read, if the city sits past 1200. The book starts a KvK map at the
smallest size and steps up on positions read past its edge; the HUD is read
up to the largest size so those positions can arrive at all.
"""

import json

import numpy as np
import pytest

from rok_farm import queue_ocr
from rok_farm import map_memory as mm
from rok_farm.flow_steps import GemFlowMixin
from rok_farm.map_memory import (HOME_TILES, MAP_SIZES, SIZE_EVIDENCE,
                                 SIZE_WINDOW_S, MapMemory, read_limit)
from rok_farm.queue_ocr import MapPositionMixin

FRAME = np.zeros((863, 1534, 3), np.uint8)
KVK = "S20001"


@pytest.fixture
def books(tmp_path, monkeypatch):
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    return tmp_path


def test_the_sizes_are_the_measured_and_the_researched_ones():
    assert HOME_TILES == 1200
    assert MAP_SIZES == (1200, 1440, 2400)
    assert read_limit("4096") == 1200
    assert read_limit("S11465") == 2400


# --- the HUD read -----------------------------------------------------------

class Engine:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def __call__(self, roi, use_det=None, use_cls=None, use_rec=None, **kw):
        if use_det is False:
            self.calls.append("fast")
            return [[self.text, 0.9]], [0.01]
        self.calls.append("full")
        return [[[[10, 5], [300, 5], [300, 30], [10, 30]], self.text, 0.9]], [0.5]


class Reader(MapPositionMixin):
    def __init__(self, map_id):
        self._home_map_id = map_id
        self.mapmem = None


@pytest.fixture
def ocr(monkeypatch):
    def install(text):
        e = Engine(text)
        monkeypatch.setattr(queue_ocr, "_ocr_engine", e)
        monkeypatch.setattr(queue_ocr, "_OCR_BACKEND", "rapidocr")
        return e
    return install


def test_a_kvk_position_past_1200_is_read(ocr):
    e = ocr(f"#{KVK}X:1300Y:1350Q")
    assert Reader(KVK)._read_map_position(FRAME) == (KVK, 1300, 1350)
    # By the 15 ms read alone: refused there, every scan past 1200 would
    # pay the 520 ms full read to get the same answer.
    assert e.calls == ["fast"]
    assert Reader(KVK)._read_map_position(FRAME, full=True) == (KVK, 1300, 1350)


def test_the_home_kingdom_still_refuses_the_digit_collision(ocr):
    """577,182 read as 577,1822 -- the misread the 1200 bound was for."""
    ocr("#4096X:577Y:1822Q")
    assert Reader("4096")._read_map_position(FRAME) is None
    assert Reader("4096")._read_map_position(FRAME, full=True) is None


def test_nothing_past_the_largest_map_is_a_place(ocr):
    ocr(f"#{KVK}X:524Y:5240Q")      # logged 2026-09-11 as a deposit
    assert Reader(KVK)._read_map_position(FRAME) is None


# --- the book's size --------------------------------------------------------

def test_a_home_map_is_1200_and_never_grows(books):
    b = MapMemory("4096")
    assert b.size == 1200
    for k in range(3 * SIZE_EVIDENCE):
        assert not b.note_extent(1250, 600, now=1000.0 + k)
    assert b.size == 1200


def test_a_kvk_map_starts_at_the_smallest_size(books):
    assert MapMemory(KVK).size == MAP_SIZES[0]


def test_it_grows_on_enough_positions_past_the_edge(books):
    b = MapMemory(KVK)
    for k in range(SIZE_EVIDENCE - 1):
        assert not b.note_extent(1250 + k, 600, now=1000.0 + 5 * k)
    assert b.size == 1200
    assert b.note_extent(1260, 600, now=1030.0)
    assert b.size == 1440


def test_the_nearest_position_decides_not_a_misread(books):
    """One 1965 (196 with a stray digit) among real reads past 1200 must not
    make the map 2400."""
    b = MapMemory(KVK)
    for k, v in enumerate([1250, 1965, 1260, 1270, 1280]):
        b.note_extent(600, v, now=1000.0 + k)
    assert b.size == 1440


def test_a_city_past_1440_takes_it_straight_to_2400(books):
    b = MapMemory(KVK)
    for k in range(SIZE_EVIDENCE):
        b.note_extent(1500 + k, 1600, now=1000.0 + k)
    assert b.size == 2400


def test_positions_days_apart_do_not_add_up(books):
    """A misread pair now and then is not a camera standing out there."""
    b = MapMemory(KVK)
    for k in range(3 * SIZE_EVIDENCE):
        b.note_extent(1250, 600, now=1000.0 + k * (SIZE_WINDOW_S + 1))
    assert b.size == 1200


def test_the_size_is_kept_and_a_hand_written_one_is_taken(books):
    b = MapMemory(KVK)
    for k in range(SIZE_EVIDENCE):
        b.note_extent(1250, 600, now=1000.0 + k)
    assert MapMemory(KVK).size == 1440
    # The operator can write it with the farm stopped ...
    (books / "S30003.json").write_text(json.dumps({"size": 2400}), encoding="utf-8")
    assert MapMemory("S30003").size == 2400
    # ... but a home map's size is not a question.
    (books / "4097.json").write_text(json.dumps({"size": 2400}), encoding="utf-8")
    assert MapMemory("4097").size == 1200


def test_the_edge_moves_with_the_size(books):
    b = MapMemory(KVK)
    b.set_city(1150, 600)
    assert b.score(1300, 600) <= -10, "past a 1200 edge is off the map"
    assert b.blocked(1180, 600, 0.0)
    assert not any(x >= 1200 for x, _y, _d in b.gaps_near((1150, 600), 150, 2.0))
    for k in range(SIZE_EVIDENCE):
        b.note_extent(1250, 600, now=1000.0 + k)
    assert b.score(1300, 600) > -10
    assert not b.blocked(1180, 600, 0.0)
    assert any(x >= 1200 for x, _y, _d in b.gaps_near((1150, 600), 150, 2.0))


# --- the flow feeds it ------------------------------------------------------

class Scan(GemFlowMixin):
    def __init__(self, book, reads):
        self.mapmem = book
        self._home_map_id = book.map_id
        self.win = {"left": 0, "top": 0, "width": 1534, "height": 863}
        self._reads = list(reads)

    def _read_map_position(self, frame=None, full=False):
        return self._reads.pop(0)


def test_the_scan_reads_teach_the_book_its_size(books):
    """A camera working ground past 1200 grows the book within a few scans
    -- through the misread hold, which still stands in front of it."""
    b = MapMemory(KVK)
    walk = [(KVK, 1190 + 9 * k, 700) for k in range(SIZE_EVIDENCE + 3)]
    s = Scan(b, walk)
    for _ in walk:
        s._map_sync(FRAME, False, force=True)
    assert b.size == 1440


def test_a_lone_far_read_on_a_kvk_map_is_still_held(books):
    b = MapMemory(KVK)
    s = Scan(b, [(KVK, 300, 196), (KVK, 300, 1965), (KVK, 305, 190)])
    assert s._map_sync(FRAME, False, force=True) == (300, 196)
    assert s._map_sync(FRAME, False, force=True) == (300, 196)
    assert s._map_sync(FRAME, False, force=True) == (305, 190)


# --- the pictures -----------------------------------------------------------

def test_the_report_map_draws_a_kvk_city_past_1200(tmp_path):
    """!map cut the ground at 1200: a city at 1300,1300 on a 1440 map kept 7
    x 7 of the ~37 x 37 cells round it."""
    from rok_farm import reports
    t0 = 1_790_000_000
    track = [[t0 + 10 * k, 1300 + k, 1300] for k in range(20)]
    cells = {}
    for size in (1200, 1440):
        png, s = reports.book_map("2026-09-01", None, 2.0, 150, 1,
                                  {"city": [1300, 1300], "track": track,
                                   "size": size}, log=tmp_path / "none.log")
        assert png is not None
        cells[size] = s["cells"]
    assert cells[1440] > 10 * cells[1200], cells


# --- the operator hears about an edge only assumed ---------------------------

def test_a_city_under_an_assumed_edge_is_reported_once(books, caplog):
    b = MapMemory(KVK)
    s = Scan(b, [(KVK, 1150, 600), (KVK, 1155, 604), (KVK, 1160, 600)])
    s._city_xy = (1150, 600)
    with caplog.at_level("WARNING", logger="gem_farm_test"):
        for _ in range(3):
            s._map_sync(FRAME, False, force=True)
    notes = [r for r in caplog.records if "edge the book assumes" in r.getMessage()]
    assert len(notes) == 1
    assert "1440 or 2400" in notes[0].getMessage()


@pytest.mark.parametrize("map_id,city", [("4096", (1150, 600)),
                                         (KVK, (600, 600))])
def test_no_note_at_home_or_far_from_the_edge(books, caplog, map_id, city):
    b = MapMemory(map_id)
    s = Scan(b, [(map_id, *city)])
    s._city_xy = city
    with caplog.at_level("WARNING", logger="gem_farm_test"):
        s._map_sync(FRAME, False, force=True)
    assert not [r for r in caplog.records
                if "edge the book assumes" in r.getMessage()]
