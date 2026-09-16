"""The account may only be online inside the run window.

On 2026-09-14 the game reclaimed 3,006 gems -- almost exactly everything the
farm gathered on 09-13 -- and the operator's reading is that the account was
online too long: at least ~8 hours a day have to be offline, their own play
counted in. The window is what keeps those hours free, so these tests pin the
hours themselves, the edges, and the four ways the account could otherwise
come back online: the farm's own loop, a wait between gathers, the watchdog,
and a remote start.
"""

from datetime import datetime

import pytest

from rok_farm import PROJECT_ROOT, config, run_window


def at(hour, minute=0):
    return datetime(2026, 9, 16, hour, minute)


def src(rel):
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8")


def test_the_window_leaves_at_least_eight_hours_off():
    assert run_window.offline_hours() >= 8, (
        f"{run_window.window_label()} leaves only "
        f"{run_window.offline_hours():.0f}h off; the reclaim on 2026-09-14 was "
        f"put down to less than 8")


@pytest.mark.parametrize("hour,minute,inside", [
    (7, 59, False), (8, 0, True), (12, 30, True), (22, 59, True),
    (23, 0, False), (2, 0, False),
])
def test_the_edges_are_where_the_config_says(hour, minute, inside):
    assert run_window.in_window(at(hour, minute)) is inside


def test_seconds_left_runs_down_to_the_close():
    assert run_window.seconds_left(at(22, 0)) == pytest.approx(3600, abs=1)
    assert run_window.seconds_left(at(23, 0)) == 0.0
    assert run_window.seconds_left(at(3, 0)) == 0.0


def test_a_window_across_midnight_still_works(monkeypatch):
    monkeypatch.setattr(config, "RUN_WINDOW_START_H", 20)
    monkeypatch.setattr(config, "RUN_WINDOW_END_H", 6)
    assert run_window.in_window(at(23, 0))
    assert run_window.in_window(at(2, 0))
    assert not run_window.in_window(at(7, 0))
    assert run_window.offline_hours() == 14


def test_the_farm_asks_before_it_opens_the_client_and_before_every_mine():
    runner = src("rok_farm/runner.py")
    assert runner.count("self._window_check()") >= 2, (
        "the run starts the client, or a mine, without asking the window")
    assert runner.index("self._window_check()") < runner.index("self._setup()"), \
        "the client is opened before the window is asked"


def test_no_wait_outlives_the_window():
    phases = src("rok_farm/phases.py")
    at_ = phases.index("def _phase_wait_return")
    body = phases[at_:phases.index("\n    def ", at_ + 10)]
    assert "_window_check()" in body, "a vigil can start outside the window"
    assert "_window_check(plan)" in body, (
        "the planned wait is not measured against the window, so an alt-tab "
        "wait can hold the client open past its end")


def test_closing_the_window_closes_the_client():
    """A farm that merely stops leaves the account logged in."""
    phases = src("rok_farm/phases.py")
    at_ = phases.index("def _window_check")
    body = phases[at_:phases.index("\n    def ", at_ + 10)]
    assert "quit_game" in body


def test_the_watchdog_does_not_relaunch_outside_it():
    wd = src("tools/dev/overnight/watchdog2.py")
    at_ = wd.index("def restart_farm")
    body = wd[at_:wd.index("\ndef ", at_ + 10)]
    assert "in_window()" in body, "the supervisor can put the account back online"
    assert body.index("in_window()") < body.index("spawn_detached"), \
        "it relaunches first and checks the window afterwards"


def test_a_remote_start_is_refused_outside_the_window(monkeypatch):
    from rok_farm import session_control as sc

    monkeypatch.setattr(sc, "farm_procs", lambda: [])
    monkeypatch.setattr(run_window, "in_window", lambda *a: False)

    def boom(*args, **kwargs):
        raise AssertionError("the farm was spawned outside the window")

    monkeypatch.setattr(sc, "spawn_detached", boom)
    msg = sc.do_start(with_watchdog=False)
    assert "window" in msg.lower()


def test_force_still_starts_it(monkeypatch):
    """The override stays, for the times the operator knows better."""
    from rok_farm import session_control as sc

    monkeypatch.setattr(sc, "farm_procs", lambda: [])
    monkeypatch.setattr(run_window, "in_window", lambda *a: False)
    monkeypatch.setattr(sc, "spawn_detached", lambda *a, **k: 4321)
    monkeypatch.setattr(sc, "blog", lambda *a, **k: None)
    msg = sc.do_start(with_watchdog=False, force=True)
    assert "4321" in msg
