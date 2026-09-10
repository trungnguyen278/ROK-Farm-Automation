"""Overnight watchdog v2: report the recurring problems, not just the fatal ones.

v1 only counted mine DONE/FAILED, restarts and silence, so the things that
actually happen all night -- empty scans, classifier/colour rejects, gather
misses -- were invisible. This tallies them and prints a delta every
SUMMARY_EVERY seconds, and every ORACLE_EVERY seconds it screenshots the client
and asks the project's own vision oracle what is on screen, so a bot wedged on a
popup is visible as a state, not inferred from log silence.

Halt conditions stay above the farm's own self-healing (recovery at 3 fails,
client restart at 8) so it gets to fix itself first.
"""
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from rok_farm import PROJECT_ROOT, roles, session_control as sc
from tools.dev.overnight.logscan import (circling_evidence, counts,
                                         current_run, flow_size)

LOGDIR = PROJECT_ROOT / "logs" / "overnight"
FARM_LOG = LOGDIR / "farm_run.log"
WD_LOG = LOGDIR / "watchdog.log"

CONSEC_FAIL_LIMIT = 14
RESTART_LIMIT = 5
# The march wait is a DESIGNED 15-minute silence ('alt-tab away, waiting
# for troops to return (cap 15min)'). A 900s limit equalled it exactly and
# killed a perfectly healthy farm at the boundary; give it real headroom.
SILENT_LIMIT = 1500
STUCK_MINUTES = 75          # no mine started or finished for this long
# Reporting cadence, NOT detection cadence -- POLL below stays at 15s, so a hang
# is still caught within seconds. These only control how often the watchdog
# TALKS. Dropped from 3min/5min once the run went hours without a fault: at that
# error rate a summary every 3 minutes is noise that hides the lines that matter,
# and the 5-minute oracle burned real API budget (it was already hitting
# OpenRouter 429s). Raise the frequency again if faults start clustering.
SUMMARY_EVERY = 3600        # hourly summary
ORACLE_EVERY = 3600         # hourly screen check (was 12/hr)
POLL = 15
# How long before the same circling evidence is worth saying again. The old
# alert used a high-water mark that was never reset, so once it had seen a 7
# it went silent for the rest of the run -- an alert that disarms itself
# permanently after one busy hour.
RETRY_COOLDOWN = 900

FARM_PID = int(sys.argv[1])
DEADLINE = datetime.strptime(sys.argv[2], "%Y-%m-%d %H:%M") if len(sys.argv) > 2 else None

def log(msg):
    line = f"{datetime.now():%H:%M:%S}  {msg}"
    print(line, flush=True)
    with WD_LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def farm_alive():
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {FARM_PID}", "/NH"],
                             capture_output=True, text=True, timeout=20).stdout
        return str(FARM_PID) in out
    except Exception:
        return True


MAX_SUPERVISOR_RESTARTS = 6
supervisor_restarts = 0



def kill_farm(reason):
    """Kill every farm process, not just the pid we happen to remember.

    farm_full.py re-execs itself, so a run is two processes, and the pid a
    detached launch hands back is not reliably the parent. Killing one of the
    pair leaves the other alive, and the next relaunch then runs a SECOND farm
    on top of it -- two bots sharing one client, which is worse than none.
    Ask the project's own matcher who is running instead of guessing.
    """
    log(f"!! HALTING FARM: {reason}")
    pids = {FARM_PID}
    try:
        pids |= {p.pid for p in sc.farm_procs()}
    except Exception as e:
        log(f"   could not enumerate farm processes: {e}")
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                           capture_output=True, timeout=30)
        except Exception as e:
            log(f"   taskkill {pid} failed: {e}")


def restart_farm(reason):
    """Stop a farm that is not working, then bring it straight back.

    Halting alone was the wrong primitive: the first wrong halt (a designed
    15-minute quiet phase read as a hang) left the farm dead for six hours
    because nothing restarted it. A supervisor that can only kill turns any
    false positive into a lost night, so it now relaunches and keeps watching,
    with a cap so a genuine loop cannot bounce forever.
    """
    global FARM_PID, supervisor_restarts, last_size, last_change
    global last_progress_at
    supervisor_restarts += 1
    kill_farm(reason)
    if supervisor_restarts > MAX_SUPERVISOR_RESTARTS:
        log(f"   {supervisor_restarts - 1} restarts already -- not restarting again")
        return False
    time.sleep(5)
    # Detached, not a child. A plain Popen made the farm a child of the
    # watchdog, so tree-killing the watchdog -- to restart it, to load new
    # code, by any supervisor above it -- silently took the running farm with
    # it. The bot hit exactly this and grew spawn_detached; the watchdog was
    # left spawning the old way.
    try:
        pid = sc.spawn_detached("farm")
    except Exception as e:
        log(f"   relaunch failed: {e}")
        return False
    if pid is None:
        log("   relaunch produced no farm process")
        return False
    FARM_PID = pid
    log(f"   farm relaunched as pid={FARM_PID} "
        f"(supervisor restart {supervisor_restarts}/{MAX_SUPERVISOR_RESTARTS})")
    time.sleep(20)                      # let it write its first lines
    last_size = -1
    last_change = time.time()
    last_progress_at = time.time()
    return True


# --- optional: ask the project's oracle what the screen shows ---
_oracle = None
_grab_err_logged = False


def screen_state():
    """Return a short description of the client's current screen, or a reason."""
    global _oracle, _grab_err_logged
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
        import numpy as np
        import mss
        import win32gui
        import win32process
        import psutil

        hits = []

        def cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            if "rise of kingdoms" not in win32gui.GetWindowText(hwnd).lower():
                return
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                if psutil.Process(pid).name().lower() != "mass.exe":
                    return
            except Exception:
                return
            l, t, r, b = win32gui.GetClientRect(hwnd)
            ox, oy = win32gui.ClientToScreen(hwnd, (0, 0))
            hits.append((ox, oy, r - l, b - t))

        win32gui.EnumWindows(cb, None)
        if not hits:
            return "game window not present"
        ox, oy, w, h = hits[0]
        with mss.mss() as sct:
            shot = sct.grab({"left": ox, "top": oy, "width": w, "height": h})
        frame = np.array(shot, dtype=np.uint8)[:, :, :3]
        grabbed_at = time.time()

        if _oracle is None:
            from rok_farm.vision_llm import build_oracle
            _oracle = build_oracle(None, None)
        if not _oracle.enabled:
            return "oracle unavailable"
        v = _oracle.classify_state(frame)
        age = time.time() - grabbed_at
        if v is None:
            return f"oracle gave no answer (budget/timeout, {age:.0f}s spent)"
        # Say how old the FRAME is, not just what was in it. The provider chain
        # can burn minutes on 429s and 504s before an answer lands, and a line
        # stamped with the completion time reads as "this is the screen now".
        # On 2026-08-18 it reported a healthy city view at 07:30:19 from a frame
        # grabbed at 07:27:13 -- the client had already been dead for 2 minutes.
        stale = "  <-- STALE" if age > 60 else ""
        return (f"view={v.view} overlay={v.overlay} covers_hud={v.covers_hud} "
                f"conf={v.confidence:.2f} via {v.source} "
                f"(frame {age:.0f}s old){stale}")
    except Exception as e:
        if not _grab_err_logged:
            _grab_err_logged = True
            return f"screen check failed: {type(e).__name__}: {e}"
        return "screen check failed"


WD_LOG.write_text("", encoding="utf-8")
log(f"watchdog v2 up: farm pid={FARM_PID}, deadline={DEADLINE}")
log(f"halt on: {CONSEC_FAIL_LIMIT} consec fails / {RESTART_LIMIT} restarts per hr "
    f"/ {SILENT_LIMIT}s silence / {STUCK_MINUTES}min with no mine")

prev = counts(FARM_LOG.read_text(encoding="utf-8", errors="replace")
              if FARM_LOG.exists() else "")
# Two baselines, because they answer different questions. `prev` is the HOURLY
# summary baseline and only moves once an hour. `poll_prev` is last poll, and
# is the only correct thing to compare against when asking "did something new
# just happen" -- see the edge detection below.
poll_prev = dict(prev)
last_size = -1
last_change = time.time()
last_summary = time.time()
last_oracle = 0.0
last_progress_at = time.time()
prev_progress_done = prev["mine_done"]
prev_progress_failed = prev["mine_failed"]
serial_flagged = False
last_retry_alert = 0.0
# Baselined, like every other counter here. The farm log is append-mode on
# purpose, so counts() returns totals over EVERY run in the file; starting this
# at 0 meant the first poll saw the whole file's history as one fresh restart
# and logged "game restart #5" sixteen seconds after boot, with the farm
# perfectly healthy. Worse, that phantom went into restart_times and counted
# toward the five-per-hour halt. Only restarts seen AFTER we start are ours.
restart_seen = prev["restart"]
restart_times = []

while True:
    time.sleep(POLL)

    if DEADLINE and datetime.now() >= DEADLINE:
        kill_farm(f"deadline {DEADLINE:%H:%M} reached")
        break
    if not farm_alive():
        log("farm process exited on its own")
        break

    try:
        text = FARM_LOG.read_text(encoding="utf-8", errors="replace")
    except Exception:
        continue

    size = flow_size(text)
    if size != last_size:
        last_size, last_change = size, time.time()
    elif time.time() - last_change > SILENT_LIMIT:
        restarted = restart_farm(f"no flow output for {int(time.time()-last_change)}s (hung)")
        if restarted:
            continue
        break

    cur = counts(text)
    # Edge detection against the PREVIOUS POLL. Comparing with `prev` looked
    # right and was silently catastrophic: `prev` is only refreshed by the
    # hourly summary, so one increment made `cur > prev` true on EVERY poll for
    # the rest of the hour. The planned-wait guard below refreshes the stuck
    # clock, and the farm now takes a planned wait every gather cycle -- far
    # more often than hourly -- so the condition was effectively always true
    # and the 75-minute stuck detector could never fire at all. A watchdog that
    # cannot time out is not a watchdog.
    new_planned_wait = cur["planned_wait"] > poll_prev["planned_wait"]
    poll_prev = cur

    # consecutive failures (tail run of FAILED with no DONE after it)
    # Count failures within the CURRENT farm run only. The log is appended
    # across restarts on purpose, so counting over the whole file meant the 14
    # failures that triggered a relaunch were still the newest events a second
    # later -- the freshly started farm had produced none of its own yet. It
    # halted again 40 seconds after coming back, then again, burning all six
    # supervisor restarts in four minutes without the new process ever getting
    # a chance. The start banner is the boundary the log already provides.
    run = current_run(text)
    events = re.findall(r"Mine \d+ (FAILED|DONE)", run)
    consec = 0
    for e in reversed(events):
        if e == "FAILED":
            consec += 1
        else:
            break
    if consec >= CONSEC_FAIL_LIMIT:
        restarted = restart_farm(f"{consec} consecutive mine failures")
        if restarted:
            continue
        break

    if cur["restart"] < restart_seen:
        restart_seen = cur["restart"]      # log truncated under us; re-baseline
    if cur["restart"] > restart_seen:
        restart_seen = cur["restart"]
        restart_times.append(time.time())
        log(f"game restart ({len(restart_times)} since watchdog start)")
    recent = [t for t in restart_times if t > time.time() - 3600]
    if len(recent) >= RESTART_LIMIT:
        # Relaunch, do not merely kill. This branch called kill_farm and broke
        # out of the loop, so a farm that restarted its client too often was
        # killed and left dead -- the exact failure the supervisor exists to
        # prevent, and the one that cost a whole night when a designed quiet
        # period was read as a hang. The consecutive-failure branch above has
        # always relaunched; this one never did.
        #
        # restart_farm carries its own cap, so a genuine loop still stops after
        # MAX_SUPERVISOR_RESTARTS instead of bouncing for ever.
        restart_times.clear()
        if restart_farm(f"{len(recent)} game restarts within an hour"):
            continue
        break

    # A dead command channel is the failure this missed the first time: the
    # farm stayed alive, the capture thread kept logging, but nothing clicked
    # again. Watch for the serial exception directly -- it is unambiguous.
    # Only the RECENT tail. The farm log is append-mode now (deliberately -- a
    # truncating log erases the evidence of why it restarted), so searching the
    # whole file means one serial hiccup hours ago keeps re-raising this alert
    # for the rest of the run, and across every future run too. Boolean searches
    # over a cumulative log are alerts with no expiry date.
    if re.search(r"SerialException|Serial lost during|Access is denied",
                 text[-20000:]):
        if not serial_flagged:
            serial_flagged = True
            log("!! serial error seen in farm log -- command channel may be dead")
        # Only fatal if it never recovers: a reconnect logs further activity.
        if cur["mine_done"] == prev_progress_done and \
                cur["mine_failed"] == prev_progress_failed and \
                time.time() - last_progress_at > 600:
            if restart_farm("serial error and no mine progress for 10 min "
                            "-- command channel did not recover"):
                serial_flagged = False
                continue
            break

    if cur["mine_done"] != prev_progress_done or \
            cur["mine_failed"] != prev_progress_failed:
        prev_progress_done = cur["mine_done"]
        prev_progress_failed = cur["mine_failed"]
        last_progress_at = time.time()

    # Mines cannot start while the client is deliberately closed, so
    # counting "no mines" as a fault during a planned wait measures the
    # wrong thing. This also covers the serial rule, which shares the
    # same clock.
    if new_planned_wait:
        last_progress_at = time.time()

    # Stuck check must NOT require scans to keep growing: a paralysed bot stops
    # producing them entirely, which is precisely the case worth catching.
    idle_min = (time.time() - last_progress_at) / 60.0
    if idle_min > STUCK_MINUTES:
        restarted = restart_farm(f"no mine started or finished for {idle_min:.0f} min "
                  f"-- farm is not progressing")
        if restarted:
            continue
        break

    # Circling one mine is a ban-shaped behaviour, so surface it as soon as it
    # appears rather than waiting for the next summary.
    why = circling_evidence(text)
    if why and time.time() - last_retry_alert > RETRY_COOLDOWN:
        last_retry_alert = time.time()
        log(f"!! possible circling: {why}")

    if time.time() - last_summary >= SUMMARY_EVERY:
        d = {k: cur[k] - prev[k] for k in cur}
        mins = SUMMARY_EVERY // 60
        log(f"[+{mins}min] done={d['mine_done']} failed={d['mine_failed']} "
            f"march={d['march_sent']} | empty={d['empty_scan']} "
            f"giveup={d['scan_giveup']} fog={d['fog_bail']} occupied={d['occupied']} "
            f"skip={d['skip_clicked']} | clf_rej={d['clf_reject']} "
            f"col_rej={d['color_reject']} gather_miss={d['gather_miss']} "
            f"refused={d['refused']} world_fail={d['world_fail']} "
            f"| max_retry={retries} | TOTAL done={cur['mine_done']} "
            f"fail={cur['mine_failed']} empty={cur['empty_scan']} "
            f"fog={cur['fog_bail']}")
        # A burst of empties with nothing to show for it is the pattern that
        # preceded every fruitless loop so far; worth saying out loud.
        if d["empty_scan"] >= 20 and d["mine_done"] == 0:
            log(f"   note: {d['empty_scan']} empty scans and no mine in {mins} min")
        if d["fog_bail"] == 0 and d["empty_scan"] >= 20:
            log("   note: many empty scans but no fog bail -- may be panning "
                "somewhere the detector does not recognise")
        prev = cur
        last_summary = time.time()

    if time.time() - last_oracle >= ORACLE_EVERY:
        last_oracle = time.time()
        log(f"screen: {screen_state()}")

log("watchdog exiting")
