"""The launcher comes to the front with ALT+TAB on the board.

2026-09-25 17:14: the farm, started windowless, could not bring the (elevated)
launcher in front of the IDE -- SetForegroundWindow "Access is denied" -- and
refused to click Play blind; the run ended at once. Keys from the board are
real input and Windows does not refuse them.
"""

import types

from rok_farm import game_process as gp


class Board:
    def __init__(self, desk, raises_on=1):
        self.desk, self.raises_on, self.sent = desk, raises_on, []

    def send(self, *args):
        self.sent.append(args[:3])
        if len(self.sent) >= self.raises_on:
            self.desk.front = 77


def desk(monkeypatch):
    state = types.SimpleNamespace(front=1)
    monkeypatch.setattr(gp.win32gui, "GetForegroundWindow", lambda: state.front)
    monkeypatch.setattr(gp.time, "sleep", lambda s: None)
    return state


def test_one_alt_tab_brings_it(monkeypatch):
    d = desk(monkeypatch)
    ctx = types.SimpleNamespace(cmd=Board(d))
    assert gp.bring_forward_by_board(ctx, 77)
    assert ctx.cmd.sent == [("COMBO", "ALT", "TAB")]


def test_it_gives_up_after_its_tries(monkeypatch):
    d = desk(monkeypatch)
    ctx = types.SimpleNamespace(cmd=Board(d, raises_on=99))
    assert not gp.bring_forward_by_board(ctx, 77)
    assert len(ctx.cmd.sent) == 2


def test_without_a_board_it_does_nothing(monkeypatch):
    desk(monkeypatch)
    assert not gp.bring_forward_by_board(types.SimpleNamespace(), 77)


def test_press_play_tries_the_board():
    import inspect
    src = inspect.getsource(gp.GameProcess.press_play)
    assert "bring_forward_by_board(ctx" in src
