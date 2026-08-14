"""The guardrails around a model-derived click.

This is the only path where a coordinate that came from a model turns into a
real click, so the tests here are about what must NEVER happen: clicking near
the deploy buttons, clicking on a screen that is not covered, clicking on faith
without checking the popup actually closed, or hunting for the button after a
miss.
"""

import numpy as np
import pytest

from rok_farm import config as cfg
from rok_farm.dismiss import DismissMixin

FRAME_W, FRAME_H = 1533, 863


def frame_with_ratio(ratio, border=120):
    frame = np.full((FRAME_H, FRAME_W, 3), border, dtype=np.uint8)
    frame[int(FRAME_H * 0.22):int(FRAME_H * 0.78),
          int(FRAME_W * 0.28):int(FRAME_W * 0.72)] = min(255, int(border * ratio))
    return frame


class StubRunner(DismissMixin):
    """Runner surface used by _dismiss_modal, with the world faked out."""

    def __init__(self, ratios, located=None, oracle=None):
        # ratios: dim ratio returned by each successive _grab()
        self._ratios = list(ratios)
        self._last_ratio = self._ratios[0]
        self.oracle = oracle
        self.win = {"left": 0, "top": 0, "width": FRAME_W, "height": FRAME_H}
        self.clicks = []
        self.learned = []
        self._located = located

    def _grab(self):
        if self._ratios:
            self._last_ratio = self._ratios.pop(0)
        return frame_with_ratio(self._last_ratio)

    def _screen_xy(self, x, y):
        return x, y

    def _click(self, sx, sy, hold_ms=0):
        self.clicks.append((sx, sy))
        return True

    def _pointer_scope(self, rect):
        from contextlib import nullcontext
        return nullcontext()

    def _find_on_frame(self, frame, template, threshold=0.65):
        return None

    def _learn_close_button(self, frame, point):
        self.learned.append(point)


class FakeOracle:
    def __init__(self, point):
        self.enabled = True
        self.point = point
        self.calls = 0

    def locate_dismiss(self, frame):
        self.calls += 1
        return self.point


# --- the point guardrails ----------------------------------------------------

@pytest.mark.parametrize("pct", [cfg.NEW_TROOP_BTN_PCT, cfg.MARCH_BTN_PCT])
def test_a_point_on_a_deploy_button_is_refused(pct):
    """The single most expensive mistake: a stray click that marches troops."""
    runner = StubRunner([4.9])
    point = (int(pct[0] * FRAME_W), int(pct[1] * FRAME_H))
    ok, why = runner._guard_dismiss_point(frame_with_ratio(4.9), point)
    assert ok is False
    assert "deploy" in why


def test_a_point_low_on_the_screen_is_refused():
    runner = StubRunner([4.9])
    ok, why = runner._guard_dismiss_point(frame_with_ratio(4.9),
                                          (900, int(FRAME_H * 0.9)))
    assert ok is False
    assert "upper part" in why


def test_a_point_outside_the_frame_is_refused():
    runner = StubRunner([4.9])
    ok, why = runner._guard_dismiss_point(frame_with_ratio(4.9), (FRAME_W + 5, 10))
    assert ok is False
    assert "outside" in why


def test_a_normal_close_button_position_is_accepted():
    runner = StubRunner([4.9])
    ok, _ = runner._guard_dismiss_point(frame_with_ratio(4.9), (1180, 120))
    assert ok is True


# --- the flow ----------------------------------------------------------------

def test_nothing_happens_when_the_screen_is_not_covered():
    oracle = FakeOracle((1180, 120))
    runner = StubRunner([1.05], oracle=oracle)
    assert runner._dismiss_modal() is False
    assert oracle.calls == 0, "no popup means no reason to ask, or to click"
    assert runner.clicks == []


def test_a_refused_point_is_never_clicked():
    oracle = FakeOracle((int(cfg.MARCH_BTN_PCT[0] * FRAME_W),
                         int(cfg.MARCH_BTN_PCT[1] * FRAME_H)))
    runner = StubRunner([4.9], oracle=oracle)
    assert runner._dismiss_modal() is False
    assert runner.clicks == []


def test_success_requires_the_dimming_to_go_away():
    """Covered -> clicked -> uncovered."""
    oracle = FakeOracle((1180, 120))
    runner = StubRunner([4.9, 1.05], oracle=oracle)
    assert runner._dismiss_modal() is True
    assert len(runner.clicks) == 1
    assert runner.learned == [(1180, 120)], "a button that worked must be learned"


def test_a_miss_is_not_retried():
    """Still dimmed afterwards: the model was wrong, so stop -- do not hunt."""
    oracle = FakeOracle((1180, 120))
    runner = StubRunner([4.9, 4.9], oracle=oracle)
    assert runner._dismiss_modal() is False
    assert len(runner.clicks) == 1, "exactly one attempt, never a second guess"
    assert runner.learned == [], "a button that did not work must not be learned"


def test_no_oracle_means_no_model_click():
    runner = StubRunner([4.9], oracle=None)
    assert runner._dismiss_modal() is False
    assert runner.clicks == []


def test_disabled_oracle_means_no_model_click():
    oracle = FakeOracle((1180, 120))
    oracle.enabled = False
    runner = StubRunner([4.9], oracle=oracle)
    assert runner._dismiss_modal() is False
    assert oracle.calls == 0


def test_oracle_returning_nothing_is_harmless():
    oracle = FakeOracle(None)
    runner = StubRunner([4.9], oracle=oracle)
    assert runner._dismiss_modal() is False
    assert runner.clicks == []
