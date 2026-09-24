"""The farm measures a KvK map's size once, and only a KvK map.

rok_farm/map_edge.py walks to the map's east and north edges, where the HUD
starts naming the kingdom next door. The flow runs it at the start of a mine,
brings the view back through the city, and takes the size only when it is of
this map, both edges agree on it, and it is not smaller than positions
already read on the map.
"""

import pytest

from rok_farm import map_memory as mm
from rok_farm.flow_steps import GemFlowMixin
from rok_farm.map_memory import MapMemory

KVK = "S20001"


class Flow(GemFlowMixin):
    def __init__(self, book, result=None, back=True, boom=False):
        self.mapmem = book
        self.win = {"left": 0, "top": 0, "width": 1534, "height": 863}
        self.result, self.back, self.boom = result or {}, back, boom
        self.probes, self.trips = 0, []

    def _probe_map_size(self, out_dir=None):
        self.probes += 1
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


def measured(size, map_id=KVK, confident=True):
    """Both edges agree on `size`; not confident: the north walk ran out of
    legs before it left the map (so its agreeing size proves nothing)."""
    return {"map_id": map_id, "size": size, "confident": confident,
            "east": {"ended": "left", "last": size - 40, "size": size},
            "north": {"ended": "left" if confident else "cap",
                      "last": size - 70, "size": size}}


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    return MapMemory(KVK)


def test_a_kvk_map_is_measured_once_and_remembered(book, tmp_path):
    f = Flow(book, measured(1440))
    assert f._maybe_probe_map_size("m1")
    assert (f.probes, f.trips) == (1, ["city", "world"])
    assert book.size == 1440 and book.size_measured
    assert f._maybe_probe_map_size("m2") and f.probes == 1
    again = MapMemory(KVK)
    assert again.size == 1440 and again.size_measured
    assert Flow(again, measured(1440))._maybe_probe_map_size("m3")


def test_a_home_kingdom_is_never_probed(tmp_path, monkeypatch):
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    f = Flow(MapMemory("4096"), measured(1200, map_id="4096"))
    assert f._maybe_probe_map_size("m1")
    assert (f.probes, f.trips) == (0, [])


@pytest.mark.parametrize("res,why", [
    (measured(1440, map_id="S99999"), "another map's edges"),
    ({"error": "the HUD did not read at the widest zoom"}, "no read"),
    (measured(1440, confident=False), "the two edges did not agree"),
])
def test_a_doubtful_read_is_not_taken(book, res, why):
    f = Flow(book, res)
    assert f._maybe_probe_map_size("m1"), why
    assert not book.size_measured and book.size == 1200, why
    assert f.trips == ["city", "world"], "the view must come back either way"


def test_positions_already_read_outrank_a_smaller_measured(book):
    for k in range(mm.SIZE_EVIDENCE):
        book.note_extent(1500 + k, 600, now=1000.0 + k)
    assert book.size == 2400
    Flow(book, measured(1440))._maybe_probe_map_size("m1")
    assert book.size == 2400 and not book.size_measured


def test_a_failed_probe_waits_before_the_next_try(book, monkeypatch):
    import rok_farm.flow_steps as fs
    now = [1_000_000.0]
    monkeypatch.setattr(fs.time, "time", lambda: now[0])
    f = Flow(book, {"error": "x"})
    f._maybe_probe_map_size("m1")
    now[0] += GemFlowMixin.SIZE_PROBE_RETRY_S - 60
    f._maybe_probe_map_size("m2")
    assert f.probes == 1
    now[0] += 120
    f._maybe_probe_map_size("m3")
    assert f.probes == 2


def test_a_probe_that_crashes_still_brings_the_view_back(book):
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
