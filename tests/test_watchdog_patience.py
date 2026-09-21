"""The watchdog must not kill a farm that is waiting on purpose.

Measured over 1,154 mine-to-mine gaps: median 1.6 min, p95 26.4, p99 43.1,
max 180.7. STUCK_MINUTES is 50, so the threshold sits just above the 99th
percentile of ordinary behaviour -- and the operator says plainly that some
waits run to about 45 minutes.

The stuck clock is reset by lines where the farm says it is waiting on
purpose, and that list had only two entries, both from the quit path. The
action-point run added a 15-25 minute dwell today and was never added to it,
so half the budget could go by with the farm demonstrably alive.

A phrase belongs on that list only if a STUCK farm cannot produce it over and
over; otherwise the detector can never fire, which has happened here before.
"""

import re

import pytest

from tools.dev.overnight.logscan import PATTERNS, counts


def scan(text):
    return counts(text)["planned_wait"]


def test_the_quit_wait_still_counts():
    assert scan("  [INFO] Staying out for 5.4 min\n") == 1
    assert scan("  [INFO] Still out, 3 min to go\n") == 1


def test_the_barbarian_dwell_counts():
    """15-25 minutes of a 50-minute budget, brand new today."""
    assert scan("  [INFO] AP burn running -- staying in for 22.8min,\n") == 1
    assert scan("gem_farm_test: AP dwell 1121s in: queue 1/5\n") == 1


def test_the_dwell_keeps_proving_it_is_alive():
    """It repeats every 70-140s while the run is on, so the clock keeps
    resetting for exactly as long as the run really lasts."""
    log = "".join(f"gem_farm_test: AP dwell {n}s in: queue 3/5\n"
                  for n in (106, 195, 327, 427, 565))
    assert scan(log) == 5


def test_an_ordinary_mine_does_not_look_like_a_planned_wait():
    """The clock has to run during real work, or nothing is ever caught."""
    log = ("gem_farm_test: Mine 3 DONE (total: 7)\n"
           "gem_farm_test: Queue reconcile: 5/5 full\n"
           "gem_farm_test: Gems now 79053\n")
    assert scan(log) == 0


def test_the_gather_wait_is_deliberately_left_out():
    """"Phase: alt-tab away" happens every single cycle. A farm circling
    between city and wait without finishing anything would produce it for
    ever and hold the clock at zero -- which is how the detector was made
    unable to fire once already."""
    assert scan("  [INFO] Phase: alt-tab away, waiting for troops to return\n") == 0


def test_the_watchdog_no_longer_erases_its_own_history():
    import inspect
    from pathlib import Path
    src = Path("tools/dev/overnight/watchdog2.py").read_text(encoding="utf-8")
    assert 'WD_LOG.write_text("", encoding="utf-8")' not in src, (
        "the watchdog is wiping its log again -- six starts in a day left a "
        "three-line file and no way to audit a single restart")
