"""_click_match is the only place a template match turns into a click, so the
button-position guard has to hold exactly there.

Uses a stub runner rather than the real one: no ESP32, no game, no capture.
"""

import pytest

from rok_farm import config as cfg
from rok_farm.button_registry import ButtonRegistry
from rok_farm.input_hid import HidInputMixin
from vision.template_matcher import Match

GATHER = "buttons/gather_btn"


class StubRunner(HidInputMixin):
    """Just enough of the runner for _click_match to run."""

    def __init__(self, registry):
        self.buttons = registry
        self.win = {"left": 0, "top": 0, "width": 1000, "height": 800}
        self.clicks = []

    def _screen_xy(self, fx, fy):
        return fx, fy

    def _click(self, sx, sy, hold_ms=0):
        self.clicks.append((sx, sy))
        return True


def match_at(x, y, name=GATHER):
    return Match(name, x - 10, y - 10, 20, 20, 0.9, (x, y))


@pytest.fixture
def trained(tmp_path):
    """A registry that has seen gather_btn at the centre-ish many times."""
    reg = ButtonRegistry(path=tmp_path / "registry.json")
    for _ in range(cfg.REGISTRY_WARMUP + 5):
        reg.record(GATHER, (0.5, 0.6))
    return reg


def test_outlier_is_never_clicked(trained):
    runner = StubRunner(trained)
    assert runner._click_match(match_at(50, 760)) is False
    assert runner.clicks == [], "a refused match must not reach the HID layer"


def test_expected_position_is_clicked(trained):
    runner = StubRunner(trained)
    assert runner._click_match(match_at(500, 480)) is True
    assert len(runner.clicks) == 1
    sx, sy = runner.clicks[0]
    # humanize_click adds a small offset, so allow a little slack
    assert abs(sx - 500) < 40 and abs(sy - 480) < 40


def test_untrained_button_is_clicked(tmp_path):
    """An empty registry must not block a first run."""
    runner = StubRunner(ButtonRegistry(path=tmp_path / "registry.json"))
    assert runner._click_match(match_at(50, 760)) is True
    assert len(runner.clicks) == 1


def test_accepted_click_is_recorded(trained):
    before = trained.stats(GATHER)["n"]
    StubRunner(trained)._click_match(match_at(500, 480))
    assert trained.stats(GATHER)["n"] == before + 1


def test_guard_is_skipped_when_no_registry(tmp_path):
    """The mixin must still work on an object without a registry attached."""
    runner = StubRunner(ButtonRegistry(path=tmp_path / "r.json"))
    del runner.buttons
    assert runner._click_match(match_at(50, 760)) is True
