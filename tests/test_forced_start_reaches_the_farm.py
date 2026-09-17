"""A forced start has to reach the farm, not just the command that spawns it.

2026-09-18 02:00, the operator asked for one test run before a trip. do_start
was called with force=True, reported "Farm started (pid 26780)", and the farm
read the run window ON ITS OWN and stopped 0.3 seconds later. The only trace
was "No mines completed" in the report -- the window was never mentioned as
the reason. `!start force` outside the window had never once produced a
running farm.

The farm is spawned detached through `cmd /c start` with a fixed argv, so the
override travels as an environment variable on that one child.
"""

import os

import pytest

from rok_farm import run_window, session_control as sc


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv(run_window.IGNORE_ENV, raising=False)


def test_without_the_flag_the_window_still_rules(monkeypatch):
    monkeypatch.setattr(run_window.config, "RUN_WINDOW_START_H", 8)
    monkeypatch.setattr(run_window.config, "RUN_WINDOW_END_H", 23)
    import datetime as dt
    assert not run_window.in_window(dt.datetime(2026, 9, 18, 2, 0))


def test_the_flag_opens_the_window_for_this_process(monkeypatch):
    monkeypatch.setenv(run_window.IGNORE_ENV, "1")
    import datetime as dt
    assert run_window.in_window(dt.datetime(2026, 9, 18, 2, 0))
    assert run_window.seconds_left(dt.datetime(2026, 9, 18, 2, 0)) > 0


def test_the_label_says_so_when_it_is_overridden(monkeypatch):
    """A log line reading plain 08:00-23:00 during a 2am run would be a lie."""
    monkeypatch.setenv(run_window.IGNORE_ENV, "1")
    assert "overridden" in run_window.window_label()


def test_a_forced_start_hands_the_flag_to_the_farm(monkeypatch):
    seen = {}

    def fake_spawn(role, *args, env_extra=None):
        seen[role] = env_extra
        return 1234

    monkeypatch.setattr(sc, "spawn_detached", fake_spawn)
    monkeypatch.setattr(sc, "farm_procs", lambda: [])
    monkeypatch.setattr(run_window, "in_window", lambda *a: False)
    sc.do_start(with_watchdog=True, force=True)
    assert seen["farm"] == {run_window.IGNORE_ENV: "1"}
    assert seen["watchdog"] == {run_window.IGNORE_ENV: "1"}, (
        "the watchdog would refuse to relaunch the farm it is supervising"
    )


def test_an_ordinary_start_inside_the_window_hands_over_nothing(monkeypatch):
    """The override must not leak into normal runs."""
    seen = {}

    def fake_spawn(role, *args, env_extra=None):
        seen[role] = env_extra
        return 1234

    monkeypatch.setattr(sc, "spawn_detached", fake_spawn)
    monkeypatch.setattr(sc, "farm_procs", lambda: [])
    monkeypatch.setattr(run_window, "in_window", lambda *a: True)
    sc.do_start(with_watchdog=True, force=True)
    assert seen["farm"] is None
    assert seen["watchdog"] is None


def test_the_controller_environment_is_left_alone(monkeypatch):
    """Setting it on this process would turn the window off for the rest of
    the day, for every later spawn."""
    monkeypatch.setattr(sc, "spawn_detached", lambda role, *a, env_extra=None: 1)
    monkeypatch.setattr(sc, "farm_procs", lambda: [])
    monkeypatch.setattr(run_window, "in_window", lambda *a: False)
    sc.do_start(with_watchdog=False, force=True)
    assert run_window.IGNORE_ENV not in os.environ
