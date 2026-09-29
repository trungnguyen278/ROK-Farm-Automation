"""The live panel and its alerts, read out of the farm log.

2026-09-29, the operator: the raw log lines the bot posted look ugly; show
what the farm is doing in real time, failures included, and make it look
professional.
"""

import os
import time

from rok_farm import live_feed as lf

# A slice of a real run, in the shapes the farm writes (console lines have no
# timestamp of their own).
LOG = """\
2026-09-29 14:06:15,000 [INFO   ] gem_farm_test: === farm start 2026-09-29 14:06:15 ===
2026-09-29 14:06:27,000 [INFO   ] gem_farm_test: Gems now 102415 (+0 since start)
  *** MINE 1 ***
--- [m1] Step 1: Ensure world map @ icon-zoom ---
--- [m1] Step 2: Scan + verify gem mines ---
  [ -- ] Scan  3/60: no icons (spd=4.5x, empty=3)
  [INFO] Queue: 4/5, 1 slot(s) free
  [INFO] March time 1m47s, gather bonus [105.0, 72.5] -> est. gather 15m, home in ~18m
  [INFO] Marched to 573:638 (33 deposit(s) this session)
  Mine 1 DONE (total: 5)
  *** MINE 2 ***
2026-09-29 14:10:00,000 [INFO   ] gem_farm_test: x
--- [m2] Step 2: Scan + verify gem mines ---
  [WARN] 18 consecutive empty scans -- restarting from city
  Mine 2 FAILED
  *** MINE 3 ***
  [FAIL] Deploy panel never opened after Gather -- not firing the chain into the map
  Mine 3 FAILED
2026-09-29 14:20:00,000 [INFO   ] gem_farm_test: Gems now 102430 (+15 since start)
  [INFO] Troops home in ~12.4min -- alt-tab out for 13.0min
"""


def fed(text=LOG):
    s = lf.LiveState()
    events = [e for line in text.splitlines() for e in s.feed(line)]
    return s, events


def test_the_counts_of_the_day():
    s, _ = fed()
    assert (s.today["marches"], s.today["done"], s.today["failed"]) == (1, 1, 2)
    assert s.gems == 102430 and s.gems_day_start == 102415


def test_a_failure_carries_its_reason():
    _, events = fed()
    fails = [e for e in events if e.kind == "failed"]
    assert [e.mine for e in fails] == [2, 3]
    assert fails[0].detail == "18 empty scans in a row"
    assert fails[1].detail.startswith("Deploy panel never opened")
    assert all(e.alert for e in fails), "a failed mine gets a message of its own"


def test_a_reason_does_not_leak_into_the_next_mine():
    text = LOG.replace("  [FAIL] Deploy panel never opened after Gather -- not "
                       "firing the chain into the map\n", "")
    _, events = fed(text)
    third = [e for e in events if e.kind == "failed"][-1]
    assert third.detail == "no reason in the log"


def test_a_march_names_its_deposit_and_when_it_is_home():
    _, events = fed()
    march = next(e for e in events if e.kind == "march")
    assert "573:638" in march.text and "home in ~18 min" in march.text
    done = next(e for e in events if e.kind == "done")
    assert "573:638" in done.text


def test_what_it_is_doing_now():
    s, _ = fed(LOG.split("  Mine 1 DONE")[0])
    assert (s.mine, s.step, s.scan, s.queue) == (1, "scanning for gems", (3, 60), (4, 5))
    spec = lf.panel_spec(s, True, True, time.time())
    assert "Mine 1" in spec["title"] and "scanning for gems (3/60)" in spec["title"]


def test_a_wait_is_the_state_until_it_is_over():
    s, events = fed()
    assert s.wait_how == "alt-tabbed out"
    now = s.stamp + 5 * 60
    spec = lf.panel_spec(s, True, True, now)
    assert "Waiting for the troops" in spec["title"] and "~8 min left" in spec["title"]
    assert events[-1].kind == "wait"


def test_a_short_wait_is_state_not_an_event():
    s, events = fed(LOG.replace("~12.4min -- alt-tab out for 13.0min",
                                "~1.2min -- alt-tab out for 1.5min"))
    assert s.wait_how == "alt-tabbed out"
    assert events[-1].kind != "wait", "a minute's wait crowded out the news"


def test_down_is_down_whatever_the_log_says():
    s, _ = fed()
    spec = lf.panel_spec(s, False, False, time.time())
    assert "not running" in spec["title"]


def test_the_panel_lists_the_newest_first():
    s, _ = fed()
    recent = dict((n, v) for n, v, _i in lf.panel_spec(s, True, True, s.stamp)["fields"])["Recent"]
    lines = recent.splitlines()
    assert "Waiting" in lines[0] and "Farm started" in lines[-1]


def test_the_watchdog_and_the_lock_screen_reach_the_channel():
    """They used to depend on the old feed's filter (test_watchdog_can_speak,
    test_lock_screen); now on the live parser, which must alert on both."""
    s = lf.LiveState()
    wd = s.feed("  [WARN] WATCHDOG: 8 consecutive mine failures")
    lock = s.feed("  [WARN] Windows is locked -- pressing ENTER")
    assert wd and wd[0].alert and "8 consecutive mine failures" in wd[0].text
    assert lock and lock[0].alert


def test_today_starts_from_the_log_not_from_zero():
    s = lf.LiveState()
    lf.replay(s, "2026-09-28 10:00:00,000 [INFO   ] gem_farm_test: x\n"
                 "  Mine 9 DONE (total: 1)\n" + LOG, "2026-09-29")
    assert s.today["done"] == 1, "yesterday's mine counted as today's"


def test_the_failure_frame_is_the_telling_one(tmp_path):
    begin = time.time() - 100
    for name, age in [("m2_scan_05_101010.png", 50), ("m2_NO_CANDIDATES_101112.png", 60),
                      ("m2_scan_06_101213.png", 40), ("m2_scan_01_090909.png", 5000)]:
        p = tmp_path / name
        p.write_bytes(b"png")
        os.utime(p, (time.time() - age, time.time() - age))
    assert lf.failure_frame(2, begin, tmp_path).name == "m2_NO_CANDIDATES_101112.png"
    assert lf.failure_frame(7, begin, tmp_path) is None


def test_an_old_run_s_frame_is_not_this_mine_s(tmp_path):
    """Mine numbers restart every run."""
    p = tmp_path / "m2_NO_CANDIDATES_080000.png"
    p.write_bytes(b"png")
    os.utime(p, (time.time() - 9000, time.time() - 9000))
    assert lf.failure_frame(2, time.time() - 100, tmp_path) is None


def test_an_alert_for_a_failed_mine():
    s, events = fed()
    e = [e for e in events if e.kind == "failed"][0]
    spec = lf.alert_spec(e, s, "fail.png")
    assert "Mine 2 failed" in spec["title"] and spec["image"] == "fail.png"
    assert spec["description"] == "18 empty scans in a row"


def test_the_title_does_not_lag_behind_a_finished_mine():
    """"Mine 28 . sending the march" stayed up after it was done."""
    s, _ = fed(LOG.split("  *** MINE 2 ***")[0])
    assert s.step == "done"
    assert "Mine 1" in lf.panel_spec(s, True, True, s.stamp)["title"]
