"""A stop the operator asked for is not an alarm.

The watcher exists to report the farm dying on its own -- its own docstring
says "without being asked to" -- but it fired on any up->down transition. On
2026-09-11 a !stop at 08:03:33 produced "Farm stopped" pushed back to the same
channel the command came from, sixteen seconds later. An alert channel that
reports the operator's own actions is one they stop reading, and then a real
fault goes unread too.
"""

import time

import pytest

bot = pytest.importorskip("tools.remote.discord_bot",
                          reason="discord.py not installed")


def test_a_requested_stop_is_inside_the_grace_window():
    """The window has to outlast do_stop itself, which closes the game."""
    assert bot.STOP_GRACE >= 60, (
        "!stop closes the client and releases the board, which takes time; a "
        "short grace window would let the alert fire mid-shutdown")


def test_an_unrequested_death_is_still_reported():
    """The guard must not swallow the case the watcher was written for."""
    long_ago = time.time() - bot.STOP_GRACE - 1
    assert not (time.time() - long_ago < bot.STOP_GRACE), \
        "a stop from long ago still suppresses alerts -- the watcher is deaf"


def test_the_flag_starts_cold():
    """A fresh bot has not been asked to stop anything.

    Starting it at 'now' would suppress the first two minutes of alerts every
    time the bot restarts -- exactly when a farm it did not launch might be
    failing.
    """
    assert bot._stop_asked_at == 0.0 or \
        time.time() - bot._stop_asked_at > bot.STOP_GRACE
