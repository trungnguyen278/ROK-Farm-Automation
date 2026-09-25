"""!stop closes the game, or says it did not.

2026-09-24 18:01 the operator sent !stop; the bot could not bring the game
to the front, fell back to taskkill, and answered "killed instead" -- the
game stayed up ("!stop nhung game khong tat chi tat farm"). taskkill's
answer was never looked at, and the farm's own way to the front (ALT+TAB on
the board) was never tried.
"""

import types

import pytest

from rok_farm import game_process as gp
from rok_farm import session_control as sc


class Board:
    def __init__(self):
        self.sent = []

    def send(self, *args):
        self.sent.append(args[:3])


@pytest.fixture
def desk(monkeypatch):
    """A game window that SetForegroundWindow cannot raise."""
    import win32gui
    state = types.SimpleNamespace(front=1, alive=True, kill_works=False, alt_tab_raises=False)
    monkeypatch.setattr(win32gui, "EnumWindows", lambda cb, _x: cb(42, None))
    monkeypatch.setattr(win32gui, "IsWindowVisible", lambda h: True)
    monkeypatch.setattr(win32gui, "GetWindowText", lambda h: "Rise of Kingdoms")
    monkeypatch.setattr(win32gui, "GetForegroundWindow", lambda: state.front)
    monkeypatch.setattr(gp, "focus_window", lambda h, retries=2: False)

    def kill(name):
        if state.kill_works:
            state.alive = False
        return state.kill_works
    monkeypatch.setattr(gp, "taskkill", kill)
    monkeypatch.setattr(sc, "game_proc", lambda: object() if state.alive else None)
    monkeypatch.setattr(sc.time, "sleep", lambda s: None)
    return state


def test_it_tries_the_board_before_giving_up(desk):
    board = Board()
    sc._quit_game_gracefully(board)
    assert ("COMBO", "ALT", "TAB") in board.sent


def test_a_refused_kill_is_reported_not_claimed(desk):
    msg = sc._quit_game_gracefully(Board())
    assert "STILL RUNNING" in msg and "killed instead" not in msg


def test_a_kill_that_worked_says_so(desk):
    desk.kill_works = True
    msg = sc._quit_game_gracefully(Board())
    assert "killed instead" in msg


def test_alt_tab_that_raises_it_leads_to_alt_f4(desk):
    class Raising(Board):
        def send(self, *args):
            super().send(*args)
            if args[:3] == ("COMBO", "ALT", "TAB"):
                desk.front = 42
            if args[:3] == ("COMBO", "ALT", "F4"):
                desk.alive = False
    board = Raising()
    msg = sc._quit_game_gracefully(board)
    assert ("COMBO", "ALT", "F4") in board.sent
    assert msg.startswith("Game closed")
