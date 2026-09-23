"""The wait for the mine to zoom in is a window of time, not a poll count.

Three polls used to give about 3.6s of patience, but only because each poll
spent 1.06s matching. Parallel matching cut that to ~0.36s, and a fixed count
would have silently cut the patience with it -- so the loop now runs until
the mine shows or ZOOM_IN_WINDOW_S has passed since the click.

And the second look for the gather popup before clicking the mine is gone:
asked 1,148 times in the log, it never once found the popup.
"""

import inspect

from rok_farm import config
from rok_farm import flow_steps
from rok_farm.flow_steps import GemFlowMixin
from vision.template_matcher import Match


class Clock:
    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


class Fake(GemFlowMixin):
    """Just enough of the runner for _click_icon_and_verify."""

    def __init__(self, clock, mine_after=None, compute_s=0.36):
        self.clock = clock
        self.mine_after = mine_after      # seconds after the click, or None
        self.compute_s = compute_s
        self.clicked_at = None
        self.polls = 0
        self.fast_matcher = self.matcher = object()
        self.auto_learn = False
        self._raw_frame = None
        self.mine_clicks = 0

    def _screen_xy(self, x, y):
        return x, y

    def _extract_icon_patch(self, frame, icon):
        return None

    def _click(self, sx, sy, hold_ms=0):
        if self.clicked_at is None:
            self.clicked_at = self.clock.t
        else:
            self.mine_clicks += 1
        return True

    def _wait(self, spec, variance=0.0):
        self.clock.sleep(spec[0] if isinstance(spec, tuple) else spec)

    def _grab(self):
        self.polls += 1
        return "frame"

    def _match_verify(self, frame, template, matcher, min_conf, roi=None):
        self.clock.sleep(self.compute_s / 3)
        if template.startswith("resources/gem_mine"):
            since = self.clock.t - self.clicked_at
            if self.mine_after is not None and since >= self.mine_after:
                return Match(template, 100, 100, 80, 60, 0.9, (140, 130))
        return None

    def _is_mine_occupied(self, frame, mine):
        return False, ""

    def _has_incoming_march(self, frame, mine):
        return False, ""


def _run(monkeypatch, **kw):
    clock = Clock()
    monkeypatch.setattr(flow_steps.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(flow_steps.time, "time", clock.time)
    monkeypatch.setattr(flow_steps.time, "sleep", clock.sleep)
    monkeypatch.setattr(flow_steps, "save_screenshot", lambda *a, **k: None)
    monkeypatch.setattr(flow_steps, "is_gem_mine_color",
                        lambda *a, **k: (True, {}))
    f = Fake(clock, **kw)
    icon = Match("resources/gem_icon", 10, 10, 36, 48, 0.9, (28, 34))
    f._click_icon_and_verify(icon, "t", 1)
    return f, clock


def test_a_slow_zoom_still_gets_the_old_patience(monkeypatch):
    """A mine that only shows 3.4s after the click was found by the old
    three slow polls; the fast polls must not give up before it."""
    f, _ = _run(monkeypatch, mine_after=3.4)
    assert f.mine_clicks == 1, "gave up on a mine the old loop would have seen"


def test_a_fast_zoom_is_not_kept_waiting(monkeypatch):
    f, clock = _run(monkeypatch, mine_after=0.5)
    assert f.polls <= 2
    assert f.mine_clicks == 1


def test_nothing_there_ends_at_the_window(monkeypatch):
    f, clock = _run(monkeypatch, mine_after=None)
    spent = clock.t - f.clicked_at
    assert config.ZOOM_IN_WINDOW_S <= spent <= config.ZOOM_IN_WINDOW_S + 1.5
    assert f.mine_clicks == 0


def test_the_window_matches_what_three_slow_polls_gave():
    """0.15 after the click, then three polls of 0.45 wait + 1.06 matching:
    the last frame was grabbed 0.15 + 3*0.45 + 2*1.06 = 3.62s in."""
    assert 3.4 <= config.ZOOM_IN_WINDOW_S <= 4.0


def test_the_dead_recheck_is_gone():
    src = inspect.getsource(GemFlowMixin._click_icon_and_verify)
    assert "_recheck_" not in src, (
        "the second look for the popup is back -- it found it 0 times in 1,148")
