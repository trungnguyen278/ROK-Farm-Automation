"""A march the game refuses is caught, not counted.

2026-09-24, the operator's second account (3560, city 1113:548): "Vua bi chan
zone ban khong thay a". A deposit whose road runs through a pass the alliance
does not hold opens its deploy panel like any other; the refusal comes after
March -- "Duong toi diem den bi chan, truoc tien hay chiem Deo ..." -- with
the camera carried to the pass. Five marches went that way and the farm
counted all five as sent.
"""

import ast
import inspect

import numpy as np
import pytest

import rok_farm.flow_steps as fs
from rok_farm.flow_steps import GemFlowMixin

DEPOSIT = ("3560", 1083, 600)
PASS = ("3560", 1126, 554)


class Book:
    def __init__(self):
        self.unreachable = []

    def record_unreachable(self, site, city, pass_xy=None):
        self.unreachable.append((tuple(site), tuple(city),
                                 tuple(pass_xy) if pass_xy else None))


class Flow(GemFlowMixin):
    def __init__(self, camera, fired=False):
        self._pending_site = DEPOSIT
        self._city_xy = (1113, 548)
        self.mapmem = Book()
        self.camera, self.fired = camera, fired
        self.queue_reads = 0
        self.records = []

    def _grab(self):
        return np.zeros((863, 1534, 3), np.uint8)

    def _read_map_position(self, frame=None, **kwargs):
        return self.camera

    def _verify_march_fired(self, tries=3):
        self.queue_reads += 1
        return self.fired

    def _record(self, name, ok, why=""):
        self.records.append((name, ok, why))


@pytest.fixture(autouse=True)
def no_png(monkeypatch):
    monkeypatch.setattr(fs, "save_screenshot", lambda *a, **k: None)


def test_the_camera_on_the_pass_and_a_still_queue_is_a_refusal():
    f = Flow(PASS, fired=False)
    assert f._march_was_blocked("m2")
    assert f.mapmem.unreachable == [((1083, 600), (1113, 548), (1126, 554))]
    assert f.records == [("m2_march", False, "road blocked by a pass")]
    assert any(t[:2] == (1083, 600) for t in f._tried_tiles)


def test_a_march_that_went_leaves_the_camera_on_the_deposit():
    f = Flow(DEPOSIT)
    assert not f._march_was_blocked("m1")
    assert f.queue_reads == 0, "the badge is read only when the camera moved"
    assert f.mapmem.unreachable == [] and f.records == []


def test_the_queue_has_the_last_word():
    f = Flow(PASS, fired=True)
    assert not f._march_was_blocked("m3")
    assert f.mapmem.unreachable == []


def test_an_unread_queue_leaves_it_to_the_camera():
    assert Flow(PASS, fired=None)._march_was_blocked("m4")


def test_an_unreadable_camera_is_not_a_refusal():
    assert not Flow(None)._march_was_blocked("m5")
    assert not Flow(("S11001", 30, 535))._march_was_blocked("m6")


def test_the_march_step_asks_after_the_click_and_before_counting():
    src = ast.unparse(ast.parse(
        inspect.getsource(GemFlowMixin._step_click_march).lstrip()))
    click = src.index("self._click_pct(*MARCH_BTN_PCT")
    check = src.index("self._march_was_blocked(tag)")
    counted = src.index("self._log_deploy_panel(tag)")
    assert click < check < counted, "a refused march would be counted as sent"
