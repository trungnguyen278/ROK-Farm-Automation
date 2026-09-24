"""The farm surveys a map once -- its size and its provinces -- when the
book has nothing saved about it (the operator, 2026-09-24: look the map up
in the book; only when it is not there, zoom out and work it out).

rok_farm/map_edge.py walks to the map's east and north edges, where the HUD
starts naming the kingdom next door, keeping the minimap beside every read;
rok_farm/minimap.py turns those into provinces. The flow runs it at the
start of a mine, brings the view back through the city, and takes the size
only when it is this map's, both edges agree on it, and it is not smaller
than positions already read; the provinces only with a size it took. A map
missing either is surveyed again after SIZE_PROBE_RETRY_S, at most
SIZE_PROBE_MAX_TRIES times.
"""

import numpy as np
import pytest

from rok_farm import map_memory as mm
from rok_farm.flow_steps import GemFlowMixin
from rok_farm.map_memory import MapMemory

KVK = "S20001"


class Flow(GemFlowMixin):
    def __init__(self, book, result=None, back=True, boom=False):
        self.mapmem = book
        self.win = {"left": 0, "top": 0, "width": 1534, "height": 863}
        self._city_xy = (300, 300)
        self.result, self.back, self.boom = result or {}, back, boom
        self.surveys, self.trips = 0, []

    def _survey_map(self, city=None, out_dir=None, known_size=None):
        self.surveys += 1
        self.known_size = known_size
        if self.boom:
            raise RuntimeError("capture lost")
        return dict(self.result)

    def _toggle_view(self, label):
        self.trips.append("city")

    def _wait(self, s):
        pass

    def _step_to_world_map(self, tag):
        self.trips.append("world")
        return self.back


def provinces(size):
    n = size // 8
    grid = np.ones((n, n), np.int32)
    grid[:, n // 2:] = 2
    return {"grid": grid, "H": np.eye(3).tolist(), "how": "home calibration scaled",
            "fit_px": 0.2, "provinces": 2, "crops": 20}


def measured(size, map_id=KVK, confident=True, with_provinces=True):
    """Both edges agree on `size`; not confident: the north walk ran out of
    legs before it left the map (so its agreeing size proves nothing)."""
    return {"map_id": map_id, "size": size, "confident": confident,
            "east": {"ended": "left", "last": size - 40, "size": size},
            "north": {"ended": "left" if confident else "cap",
                      "last": size - 70, "size": size},
            "provinces": provinces(size) if with_provinces else {"error": "x", "stage": "segment"}}


@pytest.fixture
def clock(monkeypatch):
    import rok_farm.flow_steps as fs
    now = [1_000_000.0]
    monkeypatch.setattr(fs.time, "time", lambda: now[0])
    return now


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    return MapMemory(KVK)


def test_a_kvk_map_is_surveyed_once_and_remembered(book, clock):
    f = Flow(book, measured(1440))
    assert f._maybe_probe_map_size("m1")
    assert (f.surveys, f.trips) == (1, ["city", "world"])
    assert book.size == 1440 and book.size_measured and book.has_provinces()
    assert book.province_of(100, 100) == 1 and book.province_of(1400, 100) == 2
    clock[0] += 10 * GemFlowMixin.SIZE_PROBE_RETRY_S
    assert f._maybe_probe_map_size("m2") and f.surveys == 1
    again = MapMemory(KVK)
    assert again.size == 1440 and again.size_measured and again.has_provinces()
    g = Flow(again, measured(1440))
    assert g._maybe_probe_map_size("m3") and g.surveys == 0


def test_a_home_kingdom_with_its_zones_saved_is_not_surveyed(tmp_path, monkeypatch):
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    from rok_farm import minimap
    minimap.save(provinces(1200), "4096")
    f = Flow(MapMemory("4096"), measured(1200, map_id="4096"))
    assert f._maybe_probe_map_size("m1")
    assert (f.surveys, f.trips) == (0, [])


def test_a_home_kingdom_without_zones_is_surveyed_once_at_its_known_size(
        tmp_path, monkeypatch, clock):
    """Delete the saved zones and the farm works them out again by itself;
    the size of a home kingdom is not in question (1200)."""
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    home = MapMemory("4096")
    assert home.needs_survey()
    f = Flow(home, measured(1200, map_id="4096"))
    assert f._maybe_probe_map_size("m1")
    assert f.surveys == 1 and f.known_size == 1200
    assert home.has_provinces() and home.size == 1200 and not home.needs_survey()
    clock[0] += 10 * GemFlowMixin.SIZE_PROBE_RETRY_S
    assert f._maybe_probe_map_size("m2") and f.surveys == 1


def test_a_home_survey_spacing_survives_a_restart(tmp_path, monkeypatch, clock):
    """A failed home survey is not tried again at every farm start."""
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    Flow(MapMemory("4096"), {"error": "x"})._maybe_probe_map_size("m1")
    again = Flow(MapMemory("4096"), measured(1200, map_id="4096"))
    again._maybe_probe_map_size("m2")
    assert again.surveys == 0


@pytest.mark.parametrize("res,why", [
    (measured(1440, map_id="S99999"), "another map's edges"),
    ({"error": "the HUD did not read at the widest zoom"}, "no read"),
    (measured(1440, confident=False), "the two edges did not agree"),
])
def test_a_doubtful_size_is_not_taken_nor_its_provinces(book, res, why):
    f = Flow(book, res)
    assert f._maybe_probe_map_size("m1"), why
    assert not book.size_measured and book.size == 1200, why
    assert not book.has_provinces(), why
    assert f.trips == ["city", "world"], "the view must come back either way"


def test_positions_already_read_outrank_a_smaller_size(book):
    for k in range(mm.SIZE_EVIDENCE):
        book.note_extent(1500 + k, 600, now=1000.0 + k)
    assert book.size == 2400
    Flow(book, measured(1440))._maybe_probe_map_size("m1")
    assert book.size == 2400 and not book.size_measured and not book.has_provinces()


def test_a_size_without_provinces_is_surveyed_again_later(book, clock):
    f = Flow(book, measured(1440, with_provinces=False))
    f._maybe_probe_map_size("m1")
    assert book.size_measured and not book.has_provinces()
    clock[0] += GemFlowMixin.SIZE_PROBE_RETRY_S - 60
    f._maybe_probe_map_size("m2")
    assert f.surveys == 1, "too soon"
    clock[0] += 120
    f.result = measured(1440)
    f._maybe_probe_map_size("m3")
    assert f.surveys == 2 and book.has_provinces()


def test_the_tries_run_out(book, clock):
    f = Flow(book, {"error": "x"})
    for _ in range(GemFlowMixin.SIZE_PROBE_MAX_TRIES + 2):
        f._maybe_probe_map_size("m")
        clock[0] += GemFlowMixin.SIZE_PROBE_RETRY_S + 1
    assert f.surveys == GemFlowMixin.SIZE_PROBE_MAX_TRIES
    assert MapMemory(KVK).size_probe_tries == GemFlowMixin.SIZE_PROBE_MAX_TRIES


def test_a_survey_that_crashes_still_brings_the_view_back(book):
    f = Flow(book, boom=True)
    assert f._maybe_probe_map_size("m1")
    assert f.trips == ["city", "world"]
    assert not book.size_measured


def test_the_mine_stops_if_the_way_back_fails(book):
    assert not Flow(book, measured(1440), back=False)._maybe_probe_map_size("m1")


def test_the_mine_calls_it_right_after_reaching_the_world_map():
    import ast
    import inspect
    import textwrap
    src = textwrap.dedent(inspect.getsource(GemFlowMixin))
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("_step_to_world_map", "_maybe_probe_map_size",
                                 "_step_scan_and_verify_gem")]
    order = [c.func.attr for c in sorted(calls, key=lambda c: (c.lineno, c.col_offset))]
    i = order.index("_maybe_probe_map_size")
    assert order[i - 1] == "_step_to_world_map"
    assert "_step_scan_and_verify_gem" in order[i + 1:]


def test_zones_deleted_after_a_survey_are_surveyed_again_at_once(tmp_path, monkeypatch, clock):
    """The operator's test: delete the saved zones and the farm works them
    out again -- the six hours between tries are for surveys that failed."""
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    home = MapMemory("4096")
    f = Flow(home, measured(1200, map_id="4096"))
    f._maybe_probe_map_size("m1")
    assert home.has_provinces() and home.size_probe_tries == 0
    (tmp_path / "4096_provinces.png").unlink()
    home.reload_provinces()
    clock[0] += 60
    f._maybe_probe_map_size("m2")
    assert f.surveys == 2 and home.has_provinces()

