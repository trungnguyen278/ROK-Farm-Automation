"""What the watchdog reads out of the farm log, checked against the real log.

These were unreachable by any test until they were split out of watchdog2,
which supervises a live farm the moment it is imported. Every defect in them so
far had to be found by watching production.
"""


import pytest

from rok_farm import PROJECT_ROOT
from tools.dev.overnight import logscan

FARM_LOG = PROJECT_ROOT / "logs" / "overnight" / "farm_run.log"


@pytest.fixture(scope="module")
def real_log():
    if not FARM_LOG.is_file() or FARM_LOG.stat().st_size < 10_000:
        pytest.skip("no substantial farm log on this machine")
    return FARM_LOG.read_text(encoding="utf-8", errors="replace")


def test_planned_quits_are_not_counted_as_fault_restarts():
    """The farm quits its own client between gathers, by design.

    Counting those would trip the five-restarts-per-hour halt on a perfectly
    healthy run, which is why the pattern carries a negative lookahead.
    """
    text = ("WARNING: Restarting the game: waiting 9min for troops\n"
            "WARNING: Restarting the game: recovery after 3 failures\n")
    assert logscan.counts(text)["restart"] == 1


def test_capture_chatter_is_not_evidence_of_life():
    """A daemon thread logs forever whether or not the flow is progressing."""
    noise = ("2026-01-01 00:00:00,000 [INFO   ] capture.screen_capture: "
             "Window 'Rise of Kingdoms' not found\n") * 50
    assert logscan.flow_size(noise) == 0
    assert logscan.flow_size(noise + "  [INFO] Mine 1 DONE\n") > 0


def test_current_run_stops_at_the_newest_start_banner():
    text = ("=== farm start one\nMine 1 FAILED\n"
            "=== farm start two\nMine 2 DONE\n")
    run = logscan.current_run(text)
    assert "Mine 2 DONE" in run and "Mine 1 FAILED" not in run


def test_current_run_survives_a_log_with_no_banner():
    assert logscan.current_run("Mine 1 DONE\n") == "Mine 1 DONE\n"


def test_circling_fires_when_the_same_node_is_clicked_twice():
    text = ("  [1] Clicking icon conf=0.880 at (400, 300) -> screen (1,1)\n"
            "  [2] Clicking icon conf=0.881 at (410, 305) -> screen (1,1)\n")
    why = logscan.circling_evidence(text)
    assert why and "same node" in why


def test_circling_ignores_successive_attempts_on_different_nodes():
    """The ordinary business of skipping occupied mines, not ban-shaped."""
    text = ("  [1] Clicking icon conf=0.880 at (400, 300) -> screen (1,1)\n"
            "  [2] Clicking icon conf=0.881 at (900, 700) -> screen (1,1)\n")
    assert logscan.circling_evidence(text) is None


def test_circling_ignores_a_gap_in_the_attempt_sequence():
    """[1] then [1] is two different mines, not one mine clicked twice."""
    text = ("  [1] Clicking icon conf=0.880 at (400, 300) -> screen (1,1)\n"
            "  [1] Clicking icon conf=0.881 at (402, 301) -> screen (1,1)\n")
    assert logscan.circling_evidence(text) is None


def test_an_unprecedented_attempt_count_still_alerts():
    text = "".join(f"  [{i}] gather_btn conf=0.0\n" for i in range(1, 9))
    why = logscan.circling_evidence(text)
    assert why and "attempts within one mine" in why


def test_the_alert_does_not_fire_on_the_whole_recorded_history(real_log):
    """The point of the rewrite: the old rule fired on ordinary play.

    It alerted on the attempt COUNT, and 160 of ~1400 readings reach 3 or more
    -- roughly every eleventh -- while not one pair of consecutive attempts in
    the entire log ever clicked the same place. Scanned in overlapping windows
    the size the watchdog actually uses, so this is the real firing rate.
    """
    step = logscan.TAIL // 2
    windows = [real_log[i:i + logscan.TAIL]
               for i in range(0, len(real_log), step)]
    fired = [w for w in windows if logscan.circling_evidence(w)]

    old_fired = sum(1 for w in windows if logscan.max_attempt_index(w) >= 3)
    assert old_fired > 0, "the old rule never fired here; nothing is being proved"
    assert not fired, (
        f"new rule fired on {len(fired)} of {len(windows)} windows of real "
        f"play (old rule: {old_fired})")


def test_distinct_nodes_are_never_within_the_circling_threshold(real_log):
    """CIRCLE_PX is measured, so it must stay under what play actually does."""
    clicks = [(int(a), int(x), int(y))
              for a, x, y in logscan.CLICK_RE.findall(real_log)]
    gaps = [max(abs(c[1] - p[1]), abs(c[2] - p[2]))
            for p, c in zip(clicks, clicks[1:]) if c[0] == p[0] + 1]
    assert len(gaps) > 100, f"only {len(gaps)} pairs -- too thin to conclude"
    assert min(gaps) > logscan.CIRCLE_PX, (
        f"closest distinct nodes ever clicked were {min(gaps)}px apart, at or "
        f"under the {logscan.CIRCLE_PX}px threshold")


def test_capture_chatter_adds_no_bytes_at_all(real_log):
    """Not "fewer bytes" -- none. One byte per line is enough to defeat it.

    The silence check compares flow_size between polls; anything that grows
    monotonically while the flow is blocked resets the clock. The capture
    thread logs every ~10s forever, so a single residual newline per line was
    the difference between a working timeout and one that could never fire.
    """
    capture_lines = [ln for ln in real_log.splitlines()
                     if "capture.screen_capture" in ln]
    assert len(capture_lines) > 100, "not enough capture lines to conclude"
    for n in (10, 100, len(capture_lines)):
        assert logscan.flow_size("\n".join(capture_lines[:n]) + "\n") == 0, \
            f"{n} pure-capture lines still measured as flow output"


def test_a_refused_foreground_is_not_a_serial_fault():
    """"Access is denied" is a generic Windows error, not a dead command channel.

    On this machine the foreground lock timeout is effectively infinite, so a
    background process can never take focus and SetForegroundWindow is refused
    routinely. The old pattern matched the bare string and so read every one of
    those as the ESP32 link dying -- a rule that can trigger a farm restart.
    """
    foreground = ("2026-09-11 03:57:32,850 [DEBUG  ] gem_farm_test: "
                  "SetForegroundWindow failed: (5, 'SetForegroundWindow', "
                  "'Access is denied.')")
    assert not logscan.SERIAL_FAULT.search(foreground)


def test_real_serial_faults_still_match():
    real = [
        ("2026-09-09 01:05:25,972 [WARNING] serial_comm.command_buffer: "
         "Serial lost during MOVE (attempt 1): Write timeout"),
        ("2026-09-09 01:05:25,972 [ERROR  ] serial_comm.connection: "
         "SerialException: could not open port"),
        # the access denial that DOES matter: the port held by someone else
        ("2026-09-09 01:05:25,972 [ERROR  ] serial_comm.connection: "
         "could not open COM13: Access is denied"),
    ]
    for line in real:
        assert logscan.SERIAL_FAULT.search(line), line


def test_the_scoped_pattern_drops_the_false_positives_in_the_real_log(real_log):
    """Measured, not asserted: 12 of 13 old matches were the foreground lock."""
    import re as _re
    old = _re.compile(r"SerialException|Serial lost during|Access is denied")
    old_hits = [ln for ln in real_log.splitlines() if old.search(ln)]
    new_hits = [ln for ln in real_log.splitlines()
                if logscan.SERIAL_FAULT.search(ln)]
    assert old_hits, "no serial-ish lines in this log; nothing is being proved"
    assert len(new_hits) < len(old_hits), (
        "the scoped pattern matches as much as the old one -- it has not "
        "narrowed anything")
    assert not [ln for ln in new_hits if "SetForegroundWindow" in ln], \
        "a SetForegroundWindow line still reads as a serial fault"


def test_a_dead_client_is_recognised(real_log):
    """The night of 2026-09-11 ended with the farm alive and its client gone.

    Nothing else in this module would have noticed: the log kept growing with
    relaunch attempts, no mine was failing because none could start, and the
    stuck clock had barely begun. It sat wedged until a human stopped it.
    """
    wedged = (
        "  [FAIL] No game window after 180s\n"
        "  [FAIL] Game did not come back up\n"
    )
    assert logscan.counts(wedged)["client_dead"] == 2

    healthy = (
        "  [INFO] Staying out for 9.5 min\n"
        "  [INFO] Client ready after 1.0s (start of mine 2)\n"
        "  [WARN] Restarting the game: waiting 9min for troops\n"
    )
    assert logscan.counts(healthy)["client_dead"] == 0

    # and it really is present in the log that motivated it
    assert logscan.counts(real_log)["client_dead"] >= 1


def test_a_planned_quit_is_not_a_dead_client(real_log):
    """The farm closes its own client constantly and by design."""
    for line in ("  [INFO] Closing the game (ALT+F4)",
                 "  [WARN] Restarting the game: waiting 9min for troops",
                 "  [INFO] Troops home in ~10min -- too long to sit here, quitting"):
        assert logscan.counts(line)["client_dead"] == 0, line
