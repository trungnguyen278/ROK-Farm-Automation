"""!start refused the very person who sent it.

The guard asked "was this machine used in the last five minutes" -- but typing
!start IS using it, so the answer was always yes. Measured over every !start in
the Discord log: 15 plain ones, 11 followed by "!start force" 6-26 seconds
later with the farm only coming up after the force, and the other four started
nothing. Plain !start had never once worked, which is exactly what the operator
said on 2026-09-17: "start chua bao gio duoc chi co start force thoi".

Those eleven forced starts ran seconds after the operator's hands left the
keyboard and none of them fought anyone for the mouse, so the question is not
whether the machine was touched but whether the person has stepped away since
asking. This waits for that.
"""

import ast
import inspect

import pytest

from rok_farm import session_control as sc


@pytest.fixture
def clock(monkeypatch):
    """A clock that only moves when the code sleeps."""
    now = [1000.0]
    monkeypatch.setattr(sc.time, "time", lambda: now[0])
    monkeypatch.setattr(sc.time, "sleep", lambda s: now.__setitem__(0, now[0] + s))
    return now


def idle_is(monkeypatch, *values):
    """Successive idle readings; the last one repeats."""
    seq = list(values)

    def read():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    monkeypatch.setattr(sc, "idle_seconds", read)


def test_a_machine_already_quiet_starts_at_once(monkeypatch, clock):
    idle_is(monkeypatch, 120.0)
    assert sc.wait_until_idle(settle_s=30.0, give_up_after=180.0)
    assert clock[0] == 1000.0, "it waited when it had no reason to"


def test_it_waits_for_the_operator_to_step_away(monkeypatch, clock):
    """The command itself is input, so the first reading is always tiny."""
    idle_is(monkeypatch, 0.0, 5.0, 12.0, 31.0)
    assert sc.wait_until_idle(settle_s=30.0, give_up_after=180.0)
    assert clock[0] > 1000.0, "it never actually waited"


def test_a_machine_in_constant_use_gives_up(monkeypatch, clock):
    idle_is(monkeypatch, 1.0)
    assert not sc.wait_until_idle(settle_s=30.0, give_up_after=180.0)
    assert clock[0] <= 1000.0 + 180.0 + 2.0


def test_an_unreadable_idle_never_blocks_a_start(monkeypatch, clock):
    """idle_seconds returns -1 when Windows will not say. A guard that cannot
    measure must not be able to refuse."""
    idle_is(monkeypatch, -1.0)
    assert sc.wait_until_idle(settle_s=30.0, give_up_after=180.0)


def test_the_settle_window_is_far_below_the_old_refusal():
    """300s could never be met: every !start resets the idle clock to zero."""
    assert sc.START_SETTLE_S < sc.HUMAN_IDLE_GUARD / 5
    assert sc.START_SETTLE_S > 26, (
        "the longest gap the operator ever left between !start and !start "
        "force was 26s; settling must mean more than that"
    )


def test_the_command_no_longer_refuses_without_waiting():
    """The branch must wait for quiet, not send the force hint and stop."""
    bot = pytest.importorskip("tools.remote.discord_bot",
                              reason="discord.py not installed")
    src = inspect.getsource(bot)
    tree = ast.parse(src)
    branch = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Compare)
                and isinstance(node.left, ast.Name) and node.left.id == "cmd"
                and any(isinstance(c, ast.Constant) and c.value == "start"
                        for c in node.comparators)):
            branch = node
    assert branch is not None, "the !start command is gone"
    text = ast.unparse(tree)
    assert "wait_until_idle" in text, (
        "!start no longer waits for the machine to go quiet"
    )
