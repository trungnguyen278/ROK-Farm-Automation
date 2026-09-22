"""The pointer should not freeze solid for every alt-tab, every time.

The operator's point, 2026-09-22: a cursor that stops absolutely, for exactly
as long as the client is backgrounded, on every single wait, is a clean
correlation for anything sampling the global cursor position. Nobody has shown
ROK samples it -- this guards an unconfirmed channel, which is worth keeping
straight, since everything else changed today fixed a measured one.

It is cheap because the window is small. Measured over every saved log,
alt-tab absences run 5 to 97 seconds with a median of 32; long waits close the
client entirely and nothing observes anything then.
"""

import ast
import inspect
import pytest

from rok_farm.phases import PhasesMixin


def src():
    return inspect.getsource(PhasesMixin._tab_away)


def test_it_sometimes_does_nothing_at_all():
    """A rule with no exception is its own fingerprint, and a player who
    steps away really does leave the mouse where it lies."""
    assert 0.0 < PhasesMixin.TAB_IDLE_CHANCE < 1.0, PhasesMixin.TAB_IDLE_CHANCE
    assert 0.3 <= PhasesMixin.TAB_IDLE_CHANCE <= 0.8


def test_the_moves_are_seconds_apart_not_a_twitch():
    """The 137,000 nudges removed this morning fired every 1.75s. This has to
    look like a hand on another window, not like that coming back."""
    lo, hi = PhasesMixin.TAB_IDLE_GAP_S
    assert lo >= 4.0, PhasesMixin.TAB_IDLE_GAP_S
    assert hi > lo


def test_it_never_clicks():
    """Another application owns the screen. A stray click lands in someone's
    editor; a move is harmless."""
    tree = ast.parse(inspect.getsource(PhasesMixin._tab_idle_move).lstrip())
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    for bad in ("_click", "_click_pct", "_click_match", "send"):
        assert bad not in called, f"the idle move calls {bad}"
    assert "_moveto" in called


def test_the_whole_wait_is_still_waited(monkeypatch):
    """Moving must not cut the wait short -- the troops are the point.

    The stub owns the clock as well as the sleeping. A first version only
    replaced sleep, so time.time() never advanced, the loop never reached its
    deadline and the test hung up eighty million seconds of naps -- the same
    trap the AP dwell test fell into this morning.
    """
    slept = []
    now = [1_000_000.0]

    class Fake(PhasesMixin):
        win = {"left": 0, "top": 0, "width": 1533, "height": 862}

        def _tab_out(self):
            pass

        def _moveto(self, x, y):
            return True

    import rok_farm.phases as ph
    monkeypatch.setattr(ph.time, "time", lambda: now[0])

    def fake_sleep(s):
        slept.append(s)
        now[0] += s

    monkeypatch.setattr(ph.time, "sleep", fake_sleep)

    fake = Fake()
    moved = idle = 0
    for _ in range(60):
        slept.clear()
        before = now[0]
        fake._tab_away()
        total = now[0] - before
        assert 5.0 <= total <= 600.5, total
        assert sum(slept) == pytest.approx(total, abs=0.01)
        if len(slept) > 1:
            moved += 1
        else:
            idle += 1
    # and both behaviours actually occur
    assert moved > 0, "it never moves"
    assert idle > 0, "it always moves -- that is a rule, not a hand"


def test_it_only_runs_while_the_client_is_in_the_background():
    """The tell removed this morning was movement WITH the game in front."""
    body = src()
    out = body.find("_tab_out()")
    move = body.find("_tab_idle_move()")
    assert out != -1 and move != -1
    assert out < move, "the pointer is moved before the client is backgrounded"
