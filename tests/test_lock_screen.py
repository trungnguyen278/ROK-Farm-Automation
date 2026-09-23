"""The farm gets past the Windows lock screen with a key, and types nothing else.

2026-09-23: with the board's jitter off, the idle machine locked itself; the
farm found LockApp.exe in front at 13:46 and 14:41 and could not start the
game. The operator: the machine has no password, let it lock like a real
one ("de may khoa cung duoc ma cho no that"), and whoever does not want that
can change it in Windows. So the farm presses ENTER to take the lock screen
down -- never a character, which on a password prompt would be typed into it.
"""

import inspect
import re
import sys
import types

import pytest

from rok_farm import game_process as gp
from rok_farm.game_process import GameLifecycleMixin


def _fake_win(monkeypatch, fg, exe=None, desktop=None):
    monkeypatch.setattr(gp.win32gui, "GetForegroundWindow", lambda: fg)
    monkeypatch.setitem(sys.modules, "win32process", types.SimpleNamespace(
        GetWindowThreadProcessId=lambda h: (1, 42)))
    monkeypatch.setitem(sys.modules, "psutil", types.SimpleNamespace(
        Process=lambda pid: types.SimpleNamespace(name=lambda: exe)))

    class Desk:
        def CloseDesktop(self):
            pass

    def open_desk(*a):
        if desktop is None:
            raise OSError("no input desktop")
        return Desk()
    monkeypatch.setitem(sys.modules, "win32service", types.SimpleNamespace(
        OpenInputDesktop=open_desk,
        GetUserObjectInformation=lambda d, i: desktop))


@pytest.mark.parametrize("exe,locked", [("LockApp.exe", True),
                                        ("LogonUI.exe", True),
                                        ("Code.exe", False),
                                        ("RiseOfKingdoms.exe", False)])
def test_the_lock_screen_is_known_by_who_holds_the_foreground(monkeypatch, exe, locked):
    _fake_win(monkeypatch, fg=5, exe=exe)
    assert gp.session_locked() is locked


def test_no_foreground_and_no_input_desktop_is_locked(monkeypatch):
    _fake_win(monkeypatch, fg=0, desktop=None)
    assert gp.session_locked() is True


def test_no_foreground_on_the_default_desktop_is_not(monkeypatch):
    _fake_win(monkeypatch, fg=0, desktop="Default")
    assert gp.session_locked() is False


class Cmd:
    def __init__(self):
        self.sent = []

    def send(self, *a, **k):
        self.sent.append(a)
        return True


class Farm(GameLifecycleMixin):
    def __init__(self):
        self.cmd = Cmd()


def _run(monkeypatch, states):
    """states: what session_locked says, call after call (last one sticks)."""
    seq = list(states)

    def locked():
        return seq.pop(0) if len(seq) > 1 else seq[0]
    clock = [0.0]
    monkeypatch.setattr(gp, "session_locked", locked)
    monkeypatch.setattr(gp.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    monkeypatch.setattr(gp.time, "time", lambda: clock[0])
    f = Farm()
    assert f._ensure_unlocked("test") is True
    return f.cmd.sent


def test_nothing_is_pressed_when_the_machine_is_open(monkeypatch):
    assert _run(monkeypatch, [False]) == []


def test_the_curtain_comes_down_with_enter(monkeypatch):
    # locked at the check; still locked after the first key (sign-in shows),
    # open after the second
    sent = _run(monkeypatch, [True] + [True] * 12 + [False])
    assert sent and all(c[0] == "KEY" and c[1] == "ENTER" for c in sent)
    assert len(sent) == 2


def test_a_prompt_keys_cannot_clear_gets_hands_off(monkeypatch):
    """Locked for a long time, keys or not: exactly UNLOCK_TRIES presses, then
    nothing at all until someone else unlocks it."""
    sent = _run(monkeypatch, [True] * 400 + [False])
    assert len(sent) == Farm.UNLOCK_TRIES
    assert all(c[:2] == ("KEY", "ENTER") for c in sent)


def test_the_farm_checks_before_it_touches_anything():
    from rok_farm.runner import GemFarmRunner
    setup = inspect.getsource(GemFarmRunner._setup)
    assert "_ensure_unlocked(" in setup
    loop = inspect.getsource(GemFarmRunner)
    assert loop.find("_ensure_unlocked(\"before a mine\")") < loop.find(
        "self._maintenance_hold()"), "a mine can start on a locked machine"
    focus = inspect.getsource(GameLifecycleMixin._ensure_game_focused)
    assert "_ensure_unlocked(" in focus


def test_a_long_lock_is_a_planned_wait_and_reaches_discord():
    sys.path.insert(0, "tools/dev/overnight")
    import logscan
    assert re.search(logscan.PATTERNS["planned_wait"], "Windows still locked, 12 min")
    import importlib.util
    spec = importlib.util.spec_from_file_location("discord_bot_src",
                                                  "tools/remote/discord_bot.py")
    src = open(spec.origin, encoding="utf-8").read()
    feed = src[src.index("FEED = re.compile("):src.index(")\n", src.index("FEED = re.compile("))]
    assert "Windows is locked" in feed
