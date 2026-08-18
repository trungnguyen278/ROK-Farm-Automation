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

sys.path.insert(0, r"d:\ROK Farm Automation")

LOGDIR = Path(r"d:\ROK Farm Automation\logs\overnight")
HERE = Path(__file__).resolve().parent
FARM_LOG = LOGDIR / "farm_run.log"
WD_LOG = LOGDIR / "watchdog.log"

CONSEC_FAIL_LIMIT = 14
RESTART_LIMIT = 5
# The march wait is a DESIGNED 15-minute silence ('alt-tab away, waiting
# for troops to return (cap 15min)'). A 900s limit equalled it exactly and
# killed a perfectly healthy farm at the boundary; give it real headroom.
SILENT_LIMIT = 1500
STUCK_MINUTES = 75          # no mine started or finished for this long
SUMMARY_EVERY = 180         # every 3 min: the recurring faults move fast
ORACLE_EVERY = 300          # 12/hr, inside this watchdog's own 20/hr budget
POLL = 15
RETRY_ALERT = 3             # attempts on one mine before it reads as circling

FARM_PID = int(sys.argv[1])
DEADLINE = datetime.strptime(sys.argv[2], "%Y-%m-%d %H:%M") if len(sys.argv) > 2 else None

PATTERNS = {
    "mine_done":    r"Mine \d+ DONE",
    "mine_failed":  r"Mine \d+ FAILED",
    "empty_scan":   r"no icons",
    "scan_giveup":  r"consecutive empty scans",
    "fog_bail":     r"FOG \(out of kingdom\)",
    "clf_reject":   r"Classifier reject|Classifier REJECT",
    "color_reject": r"Color reject|color REJECT",
    "gather_miss":  r"gather_btn not found",
    "refused":      r"Refusing click",
    "march_sent":   r"March sent",
    "restart":      r"Restarting the game",
    "world_fail":   r"Not on world map after toggling",
    "recovery":     r"attempting recovery",
    "skip_clicked": r"Skip already-clicked icon",
    "occupied":     r"occupied \(",
}


def max_attempt_index(text, tail_chars=6000):
    """Highest per-mine attempt number seen recently.

    The flow prints "[3] gather_btn ..." where the bracket is the attempt
    counter within one mine, so a high number means it kept going back to the
    same area -- the circling the player spotted by eye. Only the tail is
    scanned so an old spike does not shadow the current state.
    """
    hits = re.findall(r"\[(\d+)\] (?:gather_btn|re-check|after mine click)",
                      text[-tail_chars:])
    return max((int(h) for h in hits), default=0)


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
PYTHON = r"d:\ROK Farm Automation\.venv\Scripts\python.exe"
FARM_SCRIPT = str(HERE / "farm_full.py")


def kill_farm(reason):
    log(f"!! HALTING FARM: {reason}")
    try:
        subprocess.run(["taskkill", "/PID", str(FARM_PID), "/F", "/T"],
                       capture_output=True, timeout=30)
    except Exception as e:
        log(f"   taskkill failed: {e}")


def restart_farm(reason):
    """Stop a farm that is not working, then bring it straight back.

    Halting alone was the wrong primitive: the first wrong halt (a designed
    15-minute quiet phase read as a hang) left the farm dead for six hours
    because nothing restarted it. A supervisor that can only kill turns any
    false positive into a lost night, so it now relaunches and keeps watching,
    with a cap so a genuine loop cannot bounce forever.
    """
    global FARM_PID, supervisor_restarts, last_size, last_change
    global last_progress_at, last_done_at
    supervisor_restarts += 1
    kill_farm(reason)
    if supervisor_restarts > MAX_SUPERVISOR_RESTARTS:
        log(f"   {supervisor_restarts - 1} restarts already -- not restarting again")
        return False
    time.sleep(5)
    try:
        proc = subprocess.Popen([PYTHON, FARM_SCRIPT],
                                cwd=r"d:\ROK Farm Automation",
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        log(f"   relaunch failed: {e}")
        return False
    FARM_PID = proc.pid
    log(f"   farm relaunched as pid={FARM_PID} "
        f"(supervisor restart {supervisor_restarts}/{MAX_SUPERVISOR_RESTARTS})")
    time.sleep(20)                      # let it write its first lines
    last_size = -1
    last_change = time.time()
    last_progress_at = time.time()
    last_done_at = time.time()
    return True


def counts(text):
    return {k: len(re.findall(p, text)) for k, p in PATTERNS.items()}


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

        if _oracle is None:
            from rok_farm.vision_llm import build_oracle
            _oracle = build_oracle(None, None)
        if not _oracle.enabled:
            return "oracle unavailable"
        v = _oracle.classify_state(frame)
        if v is None:
            return "oracle gave no answer (budget/timeout)"
        return (f"view={v.view} overlay={v.overlay} covers_hud={v.covers_hud} "
                f"conf={v.confidence:.2f} via {v.source}")
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
last_size = -1
last_change = time.time()
last_summary = time.time()
last_oracle = 0.0
last_done_at = time.time()
last_progress_at = time.time()
prev_progress_done = prev["mine_done"]
prev_progress_failed = prev["mine_failed"]
serial_flagged = False
last_retry_alert = 0
restart_seen = 0
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

    size = len(text)
    if size != last_size:
        last_size, last_change = size, time.time()
    elif time.time() - last_change > SILENT_LIMIT:
        restarted = restart_farm(f"no log output for {int(time.time()-last_change)}s (hung)")
        if restarted:
            continue
        break

    cur = counts(text)
    if cur["mine_done"] > prev["mine_done"]:
        last_done_at = time.time()

    # consecutive failures (tail run of FAILED with no DONE after it)
    events = re.findall(r"Mine \d+ (FAILED|DONE)", text)
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

    if cur["restart"] > restart_seen:
        restart_seen = cur["restart"]
        restart_times.append(time.time())
        log(f"game restart #{restart_seen}")
    recent = [t for t in restart_times if t > time.time() - 3600]
    if len(recent) >= RESTART_LIMIT:
        kill_farm(f"{len(recent)} game restarts within an hour")
        break

    # A dead command channel is the failure this missed the first time: the
    # farm stayed alive, the capture thread kept logging, but nothing clicked
    # again. Watch for the serial exception directly -- it is unambiguous.
    if re.search(r"SerialException|Serial lost during|Access is denied", text):
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
    retries = max_attempt_index(text)
    if retries >= RETRY_ALERT and retries > last_retry_alert:
        last_retry_alert = retries
        log(f"!! {retries} attempts within one mine -- check it is not circling "
            f"the same node")

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
