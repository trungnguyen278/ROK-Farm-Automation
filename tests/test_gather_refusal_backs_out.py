"""A refused Gather leaves the popup behind -- and then the mine after it
refuses the very same popup.

2026-09-24 07:38-07:40: mines 37 to 41 all failed on one gem deposit's popup,
open at the top of the screen with its button at y 0.350-0.358 and its text
unreadable. The misplaced-button refusal returned without closing it or
undoing the zoom, so each next mine met it again. Mine 42 met the deposit
afresh and marched to it.
"""

import time

import numpy as np
import pytest

import rok_farm.flow_steps as fs
from rok_farm.flow_steps import GemFlowMixin
from vision.template_matcher import Match


class Matcher:
    def __init__(self, y):
        self.y = y

    def match_single(self, frame, name):
        return Match(name, 520, self.y - 30, 180, 60, 0.93, (610, self.y))


class Gather(GemFlowMixin):
    def __init__(self, button_y):
        self.matcher = Matcher(button_y)
        self.calls = []

    def _grab(self):
        return np.zeros((863, 1534, 3), np.uint8)

    def _press_escape(self):
        self.calls.append("dismiss")

    def _wait(self, *a, **k):
        pass

    def _return_to_icon_zoom(self, *a, **k):
        self.calls.append("zoom out")

    def _record(self, *a, **k):
        pass

    def _read_map_position(self, frame=None, full=False):
        return None

    def _click_match(self, m):
        self.calls.append("gather")
        return True


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(fs, "save_screenshot", lambda *a, **k: None)
    monkeypatch.setattr(fs, "save_annotated", lambda *a, **k: None)
    monkeypatch.setattr(time, "sleep", lambda s: None)


def test_a_misplaced_unreadable_button_is_refused_and_left_behind(monkeypatch):
    monkeypatch.setattr(fs, "read_button_text", lambda *a, **k: [])
    g = Gather(button_y=303)                       # y 0.351, as at 07:38:58
    assert g._step_click_gather("m37") is False
    assert g.calls == ["dismiss", "zoom out"]


def test_a_wrong_button_is_refused_and_left_behind(monkeypatch):
    monkeypatch.setattr(fs, "read_button_text",
                        lambda *a, **k: ["DICH", "CHUYEN"])
    monkeypatch.setattr(fs, "button_verdict", lambda words: "other")
    g = Gather(button_y=527)
    assert g._step_click_gather("m6") is False
    assert g.calls == ["dismiss", "zoom out"]


def test_a_button_in_its_place_is_still_clicked(monkeypatch):
    monkeypatch.setattr(fs, "read_button_text", lambda *a, **k: [])
    g = Gather(button_y=527)                       # y 0.611
    assert g._step_click_gather("m42") is True
    assert g.calls == ["gather"]


def test_a_duplicate_deposit_is_left_behind(monkeypatch):
    monkeypatch.setattr(fs, "read_button_text", lambda *a, **k: [])
    g = Gather(button_y=527)
    g._read_map_position = lambda frame=None, full=False: ("4096", 632, 622)
    g._marched_before = lambda site: (True, 0)
    assert g._step_click_gather("m3") is False
    assert g.calls == ["dismiss", "zoom out"]
