"""Play is never clicked at the stored position while something covers it.

2026-09-23 13:46: a cold start with the full-screen IDE in front. The
launcher runs elevated, SetForegroundWindow was refused, the screen grab of
its rect showed the IDE, the template did not match -- and the stored
position was clicked anyway. The click went into the IDE; the game never
started.
"""

import numpy as np

from rok_farm import game_process as gp


class Ctx:
    def __init__(self):
        self.cache = self
        self.matcher = self
        self.clicks = []

    # cache / matcher stand-ins
    def get(self, name):
        return np.zeros((10, 10, 3), np.uint8)

    def match_single(self, img, name):
        return None                     # the grab shows something else

    def _pointer_scope(self, win):
        import contextlib
        return contextlib.nullcontext()

    def _click(self, x, y):
        self.clicks.append((x, y))


def _game(monkeypatch, in_front):
    g = gp.GameProcess.__new__(gp.GameProcess)
    g.play_btn_pct = (0.866, 0.830)
    win = {"hwnd": 1, "left": 100, "top": 100, "width": 800, "height": 500}
    monkeypatch.setattr(g, "launcher_window", lambda: win, raising=False)
    monkeypatch.setattr(gp, "focus_window", lambda hwnd, retries=2: in_front)
    monkeypatch.setattr(gp, "grab_rect", lambda rect: np.zeros((500, 800, 3), np.uint8))
    monkeypatch.setattr(gp.time, "sleep", lambda s: None)
    return g


def test_a_covered_launcher_is_not_clicked(monkeypatch):
    g, ctx = _game(monkeypatch, in_front=False), Ctx()
    assert g.press_play(ctx) is False
    assert ctx.clicks == []


def test_a_launcher_in_front_still_uses_the_stored_position(monkeypatch):
    """In front but the template did not match (a new skin, say): the
    stored position is still the right place to click."""
    g, ctx = _game(monkeypatch, in_front=True), Ctx()
    assert g.press_play(ctx) is True
    assert ctx.clicks == [(100 + int(800 * 0.866), 100 + int(500 * 0.830))]


def test_forcing_the_foreground_always_lets_go_of_the_other_thread(monkeypatch):
    """The 13:46 start could not raise the launcher while the IDE held the
    foreground. The fallback borrows the foreground thread's input state for
    one call -- and must hand it back even when the call fails."""
    import sys
    import types
    calls = []
    fake_proc = types.SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd: (77, 1),
        AttachThreadInput=lambda a, b, on: calls.append(("attach", a, b, on)))
    fake_api = types.SimpleNamespace(GetCurrentThreadId=lambda: 11)
    monkeypatch.setitem(sys.modules, "win32process", fake_proc)
    monkeypatch.setitem(sys.modules, "win32api", fake_api)
    monkeypatch.setattr(gp.win32gui, "GetForegroundWindow", lambda: 5)
    monkeypatch.setattr(gp.win32gui, "BringWindowToTop", lambda h: None)

    def refuse(h):
        raise OSError("Access is denied")
    monkeypatch.setattr(gp.win32gui, "SetForegroundWindow", refuse)
    gp._force_foreground(9)
    assert calls == [("attach", 11, 77, True), ("attach", 11, 77, False)]
