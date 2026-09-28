"""How a wait is spent: quit the client, alt-tab, or stay on the screen.

The operator, 2026-09-28: "tan suat thoat game dung co dinh qua nua" and "co
the them treo tai man hinh khong can alt tab". Measured 09-21..25: 60-95% of
waits quit the client, 19-33 quits a day, 18-28 minutes between them at the
median. Each wait now draws its way from weights drawn once a session, with
runs; a quit comes back at a varied time. And since a game update, leaving
the front stops the barbarian auto, so the AP dwell ends when that happens.
"""

import random
from collections import Counter

from rok_farm import phases as ph
from rok_farm.phases import PhasesMixin


class Waiter(PhasesMixin):
    pass


def draws(w, plan, can_quit, n=3000):
    return Counter(w._choose_wait_mode(plan, can_quit) for _ in range(n))


def test_all_three_ways_happen():
    random.seed(1)
    w = Waiter()
    w._wait_weights = {"quit": 0.5, "tab": 0.3, "screen": 0.2}
    assert set(draws(w, 10 * 60, True)) == {"quit", "tab", "screen"}


def test_no_quit_when_it_may_not():
    random.seed(2)
    assert "quit" not in draws(Waiter(), 10 * 60, False)


def test_long_waits_are_seldom_spent_on_screen():
    random.seed(3)
    w = Waiter()
    w._wait_weights = {"quit": 0.4, "tab": 0.3, "screen": 0.3}
    short = draws(w, 10 * 60, True)["screen"]
    w._last_wait_mode = None
    long_ = draws(w, 30 * 60, True)["screen"]
    assert long_ < 0.6 * short


def test_sessions_differ():
    random.seed(4)
    a, b = Waiter()._wait_mode_weights(), Waiter()._wait_mode_weights()
    assert a != b
    assert abs(sum(a.values()) - 1.0) < 1e-9 and abs(sum(b.values()) - 1.0) < 1e-9


def test_the_ways_come_in_runs():
    """More repeats than independent draws would give (the sum of the
    squared weights), so a day shows stretches, not one beat."""
    random.seed(5)
    w = Waiter()
    w._wait_weights = {"quit": 0.5, "tab": 0.3, "screen": 0.2}
    seq = [w._choose_wait_mode(600, True) for _ in range(4000)]
    repeats = sum(a == b for a, b in zip(seq, seq[1:])) / (len(seq) - 1)
    assert repeats > 0.5 ** 2 + 0.3 ** 2 + 0.2 ** 2 + 0.1


def test_a_quit_comes_back_at_varied_times():
    random.seed(6)
    late = [Waiter()._late_return_s() for _ in range(5000)]
    assert 0.55 < sum(x < 120 for x in late) / len(late) < 0.75
    assert any(x > 480 for x in late) and max(late) <= 1500 and min(late) >= 0


class WaitFake(PhasesMixin):
    """A runner whose wait has been drawn in advance."""

    def __init__(self, mode, wait_s=900.0):
        self.mode, self.wait_s = mode, wait_s
        self.calls = []

    def _window_check(self, planned_s=0.0):
        return True

    def seconds_until_first_return(self):
        return self.wait_s

    def _detect_march_queue(self, retries=3):
        return (5, 5)

    def _choose_wait_mode(self, plan_s, can_quit):
        return self.mode

    def _may_quit_again(self):
        return True

    def _late_return_s(self):
        return 300.0

    def _check_panels_before_quit(self):
        self.calls.append("panels")

    def _note_quit(self):
        self.calls.append("note_quit")

    def _restart_game(self, reason, extra_wait=0.0):
        self.calls.append(("restart", extra_wait))
        return True

    def _note_relaunch_overhead(self, seconds):
        self.calls.append(("overhead", seconds))

    def _score_wait_prediction(self, before, wait_s, how):
        self.calls.append(("score", how))

    def _tab_out(self):
        self.calls.append("tab_out")

    def _tab_back(self):
        self.calls.append("tab_back")

    def _sleep_until_woken(self, seconds, reason):
        self.calls.append(("sleep", reason, seconds))
        return True


def planned(wait_s):
    return min(wait_s, max(ph.TAB_CYCLE_COST, wait_s - ph.WAIT_EARLY_MARGIN))


def test_on_screen_waits_without_tabbing_out():
    f = WaitFake("screen")
    f._phase_wait_return()
    sleeps = [c for c in f.calls if isinstance(c, tuple) and c[0] == "sleep"]
    assert sleeps and sleeps[0][1] == "on-screen wait"
    assert planned(900.0) <= sleeps[0][2] <= planned(900.0) + 45.0
    assert "tab_out" not in f.calls and not any(
        isinstance(c, tuple) and c[0] == "restart" for c in f.calls)
    assert ("score", "screen") in f.calls


def test_a_quit_stays_out_for_the_wait_and_the_late_return():
    f = WaitFake("quit")
    f._phase_wait_return()
    assert ("restart", planned(900.0) + 300.0) in f.calls
    assert ("score", "quit") in f.calls


def test_alt_tab_still_tabs_out_and_back():
    f = WaitFake("tab")
    f._phase_wait_return()
    assert "tab_out" in f.calls and "tab_back" in f.calls
    assert ("score", "alt-tab") in f.calls


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def time(self):
        return self.now


class Dwell(PhasesMixin):
    """An AP dwell whose client leaves the front on the third look."""

    def __init__(self, clock):
        self.clock, self.looks, self.slept = clock, 0, []

    def _sleep_until_woken(self, seconds, reason):
        self.slept.append(seconds)
        self.clock.now += seconds
        return True

    def _detect_march_queue(self, retries=3):
        return (3, 5)

    def _game_in_front(self):
        self.looks += 1
        return self.looks < 3


def test_the_ap_dwell_ends_when_the_game_leaves_the_front(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(ph.time, "time", clock.time)
    d = Dwell(clock)
    d._ap_dwell(1500.0)
    assert len(d.slept) == 3 and sum(d.slept) < 1500.0
