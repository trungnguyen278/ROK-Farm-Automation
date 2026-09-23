"""The position is read every scan, fast, and the whole view goes in the book.

The full OCR (text detection + recognition) cost ~520ms a read, so the scan
read the position every fourth frame and the book recorded one cell under
the camera. The strip is one line of text: recognition alone reads it in
~15ms, and gave the same position on all 59 icon-zoom frames it was checked
against (2026-09-23). With a position on every frame, each scan can record
every cell it showed -- about seven, from the survey's footprint -- instead
of one.
"""

import numpy as np
import pytest

from rok_farm import queue_ocr
from rok_farm.flow_steps import GemFlowMixin
from rok_farm.map_memory import CELL, MapMemory, _key
from rok_farm.queue_ocr import MapPositionMixin
from vision.template_matcher import Match

FRAME = np.zeros((863, 1534, 3), np.uint8)


class Engine:
    """RapidOCR stand-in: recognition-only answers one line of text."""

    def __init__(self, fast_text, full_boxes=None):
        self.fast_text = fast_text
        self.full_boxes = full_boxes
        self.calls = []

    def __call__(self, roi, use_det=None, use_cls=None, use_rec=None, **kw):
        if use_det is False:
            self.calls.append("fast")
            if self.fast_text is None:
                return None, None
            return [[self.fast_text, 0.9]], [0.01]
        self.calls.append("full")
        return self.full_boxes, [0.5]


class Reader(MapPositionMixin):
    def __init__(self, map_id="4096"):
        self._home_map_id = map_id
        self.mapmem = None


@pytest.fixture
def engine(monkeypatch):
    def install(fast_text, full_boxes=None):
        e = Engine(fast_text, full_boxes)
        monkeypatch.setattr(queue_ocr, "_ocr_engine", e)
        monkeypatch.setattr(queue_ocr, "_OCR_BACKEND", "rapidocr")
        return e
    return install


def test_the_fast_read_answers_alone(engine):
    e = engine("#4096X:528Y588Q")
    assert Reader()._read_map_position(FRAME) == ("4096", 528, 588)
    assert e.calls == ["fast"]


def test_a_different_map_id_goes_to_the_full_read(engine):
    """The fast read's one miss: "11465" for "S11465". It is not allowed to
    decide which map this is."""
    e = engine("#11465X:125Y:358Q", full_boxes=None)
    Reader(map_id="S11465")._read_map_position(FRAME)
    assert e.calls == ["fast", "full"]


def test_a_misread_y_is_refused(engine):
    e = engine("#4096X:535Y:5981Q", full_boxes=None)
    assert Reader()._read_map_position(FRAME) is None
    assert e.calls == ["fast", "full"]


def test_the_zoom_gauge_still_takes_the_full_read(engine):
    """The gauge comes from where the badge's box starts; the fast read has
    no boxes."""
    e = engine("#4096X:528Y588Q", full_boxes=None)
    Reader().read_zoom_gauge(FRAME)
    assert e.calls == ["full"]


@pytest.mark.parametrize("text,hint", [
    ("#4096X:528Y588Q", "icon"),
    ("28.527.874#4096X:535Y598O", "close"),   # the resource bar in front
])
def test_the_fast_read_says_whether_the_bar_is_showing(engine, text, hint):
    engine(text)
    r = Reader()
    r._read_map_position(FRAME)
    assert r._pos_zoom_hint == hint


class Scan(GemFlowMixin):
    def __init__(self):
        self.win = {"left": 0, "top": 0, "width": 1534, "height": 863}


def test_a_frame_shows_about_seven_cells_around_the_camera():
    cells = Scan()._view_cells((500, 600))
    assert 4 <= len(cells) <= 12, len(cells)
    assert (500 // CELL * CELL + CELL // 2, 600 // CELL * CELL + CELL // 2) in cells
    for x, y in cells:
        assert abs(x - 500) <= 16 and -8 <= y - 600 <= 13, (x, y)


def test_an_icon_is_placed_where_it_stands_on_the_map():
    """An icon above the centre of the frame is at a LARGER Y."""
    s = Scan()
    up = Match("g", 767 - 18, 200 - 24, 36, 48, 0.9, (767, 200))
    down = Match("g", 767 - 18, 700 - 24, 36, 48, 0.9, (767, 700))
    (ux, uy), (dx, dy) = s._icon_tiles((500, 600), FRAME, [up, down])
    assert uy > 600 > dy
    assert ux == dx == 500


def test_the_book_takes_the_whole_view(tmp_path, monkeypatch):
    import rok_farm.map_memory as mm
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    book = MapMemory("4096")
    cells = Scan()._view_cells((500, 600))
    keys = set(_key(*c) for c in cells)
    gem = (500, 600)                      # a gem in the middle of the view
    assert _key(*gem) in keys
    book.record_view(cells, [gem])
    cell = book.reach[_key(*gem)]
    assert (cell["gem"], cell["empty"]) == (1, 0)
    empties = [k for k in book.reach if book.reach[k]["empty"]]
    assert len(empties) == len(keys) - 1


def test_a_gem_in_the_margin_is_still_recorded(tmp_path, monkeypatch):
    """The margin decides what counts as SEEN empty; a gem that was actually
    detected there is still a gem."""
    import rok_farm.map_memory as mm
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    book = MapMemory("4096")
    cells = Scan()._view_cells((500, 600))
    edge = (505, 611)
    assert _key(*edge) not in set(_key(*c) for c in cells)
    book.record_view(cells, [edge])
    assert book.reach[_key(*edge)]["gem"] == 1
