"""Nothing starts the farm outside the run window -- no flag, no variable.

do_start(force=True) used to hand the farm and its watchdog an environment
variable that opened the window. On the night of 2026-09-23/24 every restart
after a test went through it: the farm ran 00:45-07:55, the account was
online 17.1 h of the UTC day, and the next audit blocked its marches for
12 hours. The operator: it was the night online. So the window is absolute;
hours outside it are a config change, made on purpose.
"""

import datetime as dt
import inspect
from pathlib import Path

import pytest

from rok_farm import run_window, session_control as sc

ROOT = Path(__file__).resolve().parents[1]


def test_outside_the_window_nothing_is_spawned(monkeypatch):
    monkeypatch.setattr(sc, "farm_procs", lambda: [])
    monkeypatch.setattr(run_window, "in_window", lambda *a: False)

    def boom(*args, **kwargs):
        raise AssertionError("the farm was spawned outside the window")

    monkeypatch.setattr(sc, "spawn_detached", boom)
    msg = sc.do_start(with_watchdog=True)
    assert "window" in msg.lower()


def test_there_is_no_force():
    """A script cannot ask for it: the parameter is gone."""
    with pytest.raises(TypeError):
        sc.do_start(with_watchdog=True, force=True)


def test_the_old_variable_opens_nothing(monkeypatch):
    monkeypatch.setenv("ROK_IGNORE_RUN_WINDOW", "1")
    monkeypatch.setattr(run_window.config, "RUN_WINDOW_START_H", 8)
    monkeypatch.setattr(run_window.config, "RUN_WINDOW_END_H", 23)
    night = dt.datetime(2026, 9, 24, 0, 45)
    assert not run_window.in_window(night)
    assert run_window.seconds_left(night) == 0.0
    assert run_window.window_label() == "08:00-23:00"


def test_inside_the_window_farm_and_watchdog_start_plain(monkeypatch):
    calls = []

    def fake_spawn(role, *args):
        calls.append((role, *args))
        return 1234

    monkeypatch.setattr(sc, "spawn_detached", fake_spawn)
    monkeypatch.setattr(sc, "farm_procs", lambda: [])
    monkeypatch.setattr(run_window, "in_window", lambda *a: True)
    monkeypatch.setattr(sc, "blog", lambda *a, **k: None)
    msg = sc.do_start(with_watchdog=True)
    assert calls == [("farm",), ("watchdog", 1234)]
    assert "1234" in msg


def test_a_spawn_carries_no_extra_environment(monkeypatch):
    """Nothing can smuggle a variable to the farm: the child gets env=None,
    which is this process's own environment."""
    assert list(inspect.signature(sc.spawn_detached).parameters) == ["role", "args"]
    seen = {}

    class FakePopen:
        def __init__(self, argv, **kwargs):
            seen.update(kwargs)

    procs = iter([[], [type("P", (), {"pid": 77})()]])
    monkeypatch.setattr(sc.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(sc, "find_procs", lambda role: next(procs))
    assert sc.spawn_detached("farm") == 77
    assert seen.get("env") is None


def test_no_code_knows_the_old_variable():
    hits = []
    for path in list((ROOT / "rok_farm").glob("*.py")) + list((ROOT / "tools").rglob("*.py")) \
            + list((ROOT / "app").glob("*.py")) + [ROOT / "run_farm.py"]:
        if "ROK_IGNORE_RUN_WINDOW" in path.read_text(encoding="utf-8", errors="replace"):
            hits.append(str(path.relative_to(ROOT)))
    assert not hits, hits
