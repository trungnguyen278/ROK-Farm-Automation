"""When the farm is allowed to keep the account online.

2026-09-14 the game reclaimed 3,006 gems -- almost exactly everything the farm
gathered on 09-13 (+3,009 on the gem counter, 00:03-21:02 local; +3,106 over
the UTC day). The operator's reading: the account was online too long. At least
about 8 hours a day have to be offline, their own play counts toward it, and on
09-13 they played through the farm's breaks -- the farm ran 00:02-13:05 and
17:53-21:26, 17 sessions, some 15h23m, and the gaps were theirs.

The scheduled session break was taken out of the runner (the note is still
there) because quitting the client between gathers already logs out a great
deal: 458 minutes of a 609-minute run on 2026-09-09. That measurement was
right and it did not help. Those 458 minutes were 21 stretches averaging 22
minutes, and what the game appears to want is one long absence, not many short
ones.

So the farm keeps a WINDOW. Outside it the farm closes the client and stops,
the watchdog does not relaunch it, and a remote start is refused.
"""

from __future__ import annotations

from datetime import datetime

from rok_farm import config

# No way round it. There was one -- do_start(force=True) handed the farm and
# its watchdog an environment variable that opened the window -- and on the
# night of 2026-09-23/24 every restart after a test went through it: the farm
# ran 00:45-07:55, the account was online 17.1 h of the UTC day, and the next
# audit blocked its marches for 12 h ("dung phan mem ben thu ba de vi pham quy
# tac"). Hours outside the window are a config change, made on purpose.


def _hour(now: datetime | None = None) -> float:
    now = now or datetime.now()
    return now.hour + now.minute / 60.0 + now.second / 3600.0


def seconds_left(now: datetime | None = None) -> float:
    """Seconds the window still has to run; 0.0 when it is already shut."""
    start = float(config.RUN_WINDOW_START_H)
    end = float(config.RUN_WINDOW_END_H)
    if start == end:                      # configured to cover the whole day
        return 24 * 3600.0
    h = _hour(now)
    inside = start <= h < end if start < end else (h >= start or h < end)
    if not inside:
        return 0.0
    return ((end - h) % 24) * 3600.0


def in_window(now: datetime | None = None) -> bool:
    """Is the clock inside the hours the farm may keep the account online?"""
    return seconds_left(now) > 0


def window_label() -> str:
    return (f"{int(config.RUN_WINDOW_START_H):02d}:00-"
            f"{int(config.RUN_WINDOW_END_H):02d}:00")


def offline_hours() -> float:
    """Hours a day the window leaves the account alone."""
    start = float(config.RUN_WINDOW_START_H)
    end = float(config.RUN_WINDOW_END_H)
    open_h = (end - start) % 24
    if start == end:
        open_h = 24.0
    return 24.0 - open_h
