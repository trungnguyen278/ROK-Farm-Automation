"""Start, stop and inspect a farming session -- without Discord in the picture.

This is the switchboard that both the Discord bot and the packaged app's menu
drive, so the two cannot drift apart. Everything here is plain Python and
psutil: no gateway, no token, no async.

The behaviours worth not losing to a second implementation:

  * discovery is stateless -- a farm is found by scanning command lines, not a
    remembered pid, so a controller can be restarted at any time and still
    stop a run it did not start
  * a farm is spawned DETACHED, so killing the controller's process tree
    cannot take a live run down with it
  * stopping ALWAYS releases the board. Killing the farm without turning the
    ESP32's idle jitter off leaves it nudging a pointer the human is trying to
    use -- the first thing anyone notices
  * the client is closed with ALT+F4 through the HID, never taskkill, because
    a hard kill reads as a crash
"""

from __future__ import annotations

import ctypes
import random
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil

from rok_farm import PROJECT_ROOT as PROJECT
from rok_farm import roles

LOGDIR = PROJECT / "logs" / "overnight"

# The board's COM number is assigned by Windows and changes across reboots and
# re-plugs, so it is detected, not configured. SerialConnection(port=None)
# finds the CH340 bridge by its VID:PID.
SERIAL_PORT = None

# Below this many seconds of input idleness, assume a human is at the machine.
# Starting the farm then means the ESP32 fights the player for the mouse.
HUMAN_IDLE_GUARD = 300.0

# !start used to be refused outright when the machine had been touched inside
# HUMAN_IDLE_GUARD -- which is always, because typing the command IS touching
# it. Measured over every !start in the Discord log: 15 plain ones, 11 of them
# followed by "!start force" 6-26 seconds later and the farm only coming up
# after the force; the other four started nothing. Plain !start has never once
# worked. Meanwhile those eleven forced starts ran with the operator's hands
# off the keyboard for a matter of seconds and none of them fought anyone for
# the mouse.
#
# So the question is not "was the machine used recently" but "has the operator
# stepped away since asking". Wait for that instead of refusing.
START_SETTLE_S = 30.0        # quiet for this long counts as stepped away
START_SETTLE_WAIT_S = 180.0  # how long to keep waiting for that quiet
# How long to watch the idle clock before deciding it tells us nothing, and the
# ceiling under which it counts as pinned. Measured on this machine with the
# farm stopped and the board's jitter off: 14 samples over 28 seconds, highest
# 1.3s.
IDLE_CLOCK_PROBE_S = 12.0
IDLE_CLOCK_DEAD_S = 2.0


def wait_until_idle(settle_s=START_SETTLE_S, give_up_after=START_SETTLE_WAIT_S):
    """Block until nobody has touched the machine for `settle_s`.

    Returns True once it is quiet, False if it never went quiet in time. An
    unavailable idle reading (-1) counts as quiet: the guard must not be able
    to block a start on a machine it cannot measure.
    """
    deadline = time.time() + give_up_after
    started = time.time()
    seen_max = 0.0
    while True:
        idle = idle_seconds()
        seen_max = max(seen_max, idle)
        if idle < 0 or idle >= settle_s:
            return True
        # Some machines never go quiet at all. This one is a laptop: Windows
        # lists a touchpad, an I2C HID device and several mice, and one of them
        # nudges the input clock every fraction of a second, so it has never
        # been seen above 1.3s even with the farm stopped and the board's
        # jitter off. Waiting for 30s of silence there is waiting forever, and
        # a guard that can never pass is worse than no guard: 2026-09-21 the
        # operator sent !start, was told "still in use" three minutes later,
        # and was not touching the machine at all.
        if time.time() - started >= IDLE_CLOCK_PROBE_S and seen_max < IDLE_CLOCK_DEAD_S:
            logger_msg = ("idle clock never rose above %.1fs in %.0fs -- this "
                          "machine always reports input, so the quiet check "
                          "cannot measure anything; starting anyway")
            _print_log(logger_msg % (seen_max, IDLE_CLOCK_PROBE_S))
            return True
        if time.time() >= deadline:
            return False
        time.sleep(min(2.0, max(0.5, settle_s - idle)))


def _print_log(msg):
    print(msg, flush=True)


# Controllers point this at their own log (the bot writes to discord_bot.log).
# A module global rather than an argument threaded through every call: these
# are all one-controller-per-process.
blog = _print_log


def set_logger(fn):
    """Send this module's notes to `fn` instead of stdout."""
    global blog
    blog = fn


# --------------------------------------------------------------------------
# processes

def find_procs(role):
    """Every running process for `role` ("farm" / "watchdog" / "bot").

    Discovery is by command line, not a remembered pid, so the bot can be
    restarted at any time and still control a run it did not launch. From
    source those are python processes; packaged they are copies of our own
    exe, which is why the interpreter-name filter has to widen when frozen.
    """
    own = Path(sys.executable).name.lower()
    out = []
    for p in psutil.process_iter(["name", "cmdline", "create_time"]):
        try:
            name = (p.info["name"] or "").lower()
            if "python" not in name and name != own:
                continue
            if roles.matches(role, p.info["cmdline"]):
                out.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return out


def farm_procs():
    return find_procs("farm")


def wd_procs():
    return find_procs("watchdog")


def game_proc():
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower() == "mass.exe":
                return p
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def kill_tree(proc, timeout=15.0):
    try:
        targets = proc.children(recursive=True) + [proc]
    except psutil.Error:
        targets = [proc]
    for p in targets:
        try:
            p.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(targets, timeout=timeout)
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass


class _LastInput(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def idle_seconds():
    """Seconds since the last real input in this session. -1 if unavailable.

    The ESP32 is a genuine HID device, so while the farm runs this is always
    ~0. It only means "is a human here" when the farm is already stopped.
    """
    try:
        lii = _LastInput()
        lii.cbSize = ctypes.sizeof(lii)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return -1.0
        tick = ctypes.windll.kernel32.GetTickCount()
        return ((tick - lii.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:
        return -1.0


def _quit_game_gracefully(cmd):
    """Close the client the way the farm does: focus it, then ALT+F4.

    NOT a process kill. quit_game() in game_process.py puts it plainly -- "a
    hard kill reads as a crash" -- and the point of closing at all is to leave
    the account cleanly logged out, so the next !start relaunches it exactly
    like the farm's own quit-and-wait does. taskkill is the last resort, not
    the method.

    ALT+F4 lands on whatever is in front, so the game has to be focused first;
    without that it would close the window running the bot.
    """
    import win32gui

    from rok_farm.config import QUIT_TIMEOUT
    from rok_farm.game_process import focus_window, taskkill

    g = game_proc()
    if not g:
        return "Game was not running."

    hwnd = None

    def cb(h, _):
        nonlocal hwnd
        if win32gui.IsWindowVisible(h) and \
                "rise of kingdoms" in win32gui.GetWindowText(h).lower():
            hwnd = h

    win32gui.EnumWindows(cb, None)
    focused = hwnd is not None and focus_window(hwnd)
    if hwnd is not None and not focused:
        # The farm's way in (_ensure_game_focused): ALT+TAB on the board, real
        # keys. Windows refuses a detached process the foreground, and on
        # 2026-09-24 18:01 !stop fell through to a kill that left the game
        # running -- the operator: "!stop nhung game khong tat chi tat farm".
        for _ in range(2):
            cmd.send("COMBO", "ALT", "TAB", random.randint(50, 120))
            time.sleep(random.uniform(1.0, 1.8))
            if win32gui.GetForegroundWindow() == hwnd:
                focused = True
                break
    if not focused:
        taskkill("MASS.exe")
        time.sleep(2.0)
        if game_proc() is None:
            return ("Game: could not bring it to the front, so ALT+F4 would hit "
                    "the wrong window -- killed instead.")
        return ("Game is STILL RUNNING: it would not come to the front and the "
                "kill was refused (a client run as administrator?) -- close it "
                "by hand.")

    time.sleep(random.uniform(0.5, 1.2))
    t0 = time.time()
    cmd.send("COMBO", "ALT", "F4", random.randint(50, 120))
    # Poll tightly so this returns the moment the client is gone rather
    # than on a fixed beat: ALT+F4 has closed it on every occasion in the
    # log (no "did not close" line has ever been printed), so the timeout
    # is only a backstop. QUIT_TIMEOUT is the project's own value for this
    # same wait, reused rather than picking a second number for it.
    deadline = time.time() + QUIT_TIMEOUT
    while time.time() < deadline:
        time.sleep(0.4)
        if game_proc() is None:
            return f"Game closed (ALT+F4, {time.time() - t0:.1f}s)."
    taskkill("MASS.exe")
    time.sleep(3.0)
    if game_proc() is not None:
        return (f"Game did not close in {QUIT_TIMEOUT:.0f}s and the kill was "
                f"refused -- it is STILL RUNNING, close it by hand.")
    return f"Game did not close in {QUIT_TIMEOUT:.0f}s -- killed."


def shutdown_board(close_game):
    """Close the client if asked, then leave the ESP32 not touching the mouse.

    One serial session for both: closing the game needs the board (ALT+F4 goes
    through the HID like every other keystroke), and the jitter must go off
    afterwards. _tab_out() switches jitter ON while the bot is tabbed away, and
    a board still nudging the pointer is what the player notices first.
    """
    try:
        from serial_comm.connection import SerialConnection
        from serial_comm.command_buffer import CommandBuffer
    except Exception as e:
        return [f"HID: import failed ({type(e).__name__})"]
    conn = SerialConnection(port=SERIAL_PORT)
    out = []
    try:
        if not conn.connect():
            return ["HID: could not open the board (unplugged, or still held)"]
        cmd = CommandBuffer(conn)
        cmd.start()
        if close_game:
            try:
                out.append(_quit_game_gracefully(cmd))
            except Exception as e:
                out.append(f"Game close failed: {type(e).__name__}: {e}")
        # IDLE 1, not 0. The firmware reads the argument as "suppressed":
        # handle_idle sets idle_suppressed = (param == 1), and idle_noise()
        # returns early only while that flag is true. So IDLE 0 CLEARS the
        # suppression and starts the board nudging the pointer every 0.5-3
        # seconds, which is the opposite of what this line has been printing.
        #
        # The operator found it from the outside on 2026-09-22: with the board
        # plugged in the screen never sleeps after locking, and unplugged it
        # does. Windows' idle clock never rose above 0.7s across two minutes
        # of an untouched machine, so the display timeout could never run
        # down. The docstring at the top of this file has always said stopping
        # must turn the jitter off; only the argument disagreed.
        cmd.send("IDLE", "1")
        cmd.stop()
        conn.disconnect()
        out.append("HID: idle jitter OFF, port released")
        return out
    except Exception as e:
        try:
            conn.disconnect()
        except Exception:
            pass
        return out + [f"HID: release failed ({type(e).__name__}: {e})"]



# --------------------------------------------------------------------------
# actions

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def spawn_detached(role, *args):
    """Launch a role so it outlives this process, and return its real pid.

    An ordinary subprocess is a child, and killing the bot's process tree kills
    it too -- restarting the bot to load new code took a live farm down with it
    once, mid-run. CREATE_BREAKAWAY_FROM_JOB does not help, because the kill
    walks parent->child links rather than the job. `cmd /c start` returns as
    soon as it has launched, so cmd exits and leaves the real process with a
    dead parent: the chain from the bot is broken before anyone follows it.

    The pid `start` hands back is cmd's, so the real one is found by watching
    for a process that was not there before.

    The child gets this process's environment as it is. It used to take extra
    variables, and the only one ever passed opened the run window -- see
    do_start.
    """
    before = {p.pid for p in find_procs(role)}
    subprocess.Popen(
        ["cmd", "/c", "start", "", "/b", *roles.command(role, *args, windowless=True)],
        cwd=str(PROJECT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
    deadline = time.time() + 25.0
    while time.time() < deadline:
        fresh = {p.pid for p in find_procs(role)} - before
        if fresh:
            return min(fresh)
        time.sleep(0.5)
    return None


def do_start(with_watchdog):
    """Start the farm (and its watchdog) -- inside the run window only.

    There is no force. do_start(force=True) used to open the window for the
    farm and its watchdog, and on the night of 2026-09-23/24 every restart
    after a test went through it: 00:45-07:55 online, 17.1 h in the UTC day,
    marches blocked for 12 h by the next audit.
    """
    from rok_farm import run_window

    if farm_procs():
        return "Farm is already running -- !stop first."
    if not run_window.in_window():
        return (f"Outside the run window {run_window.window_label()} -- not "
                f"starting. The account needs its hours off: 3,006 gems were "
                f"reclaimed on 2026-09-14 for being online too much, and a "
                f"night online on 2026-09-23 got its marches blocked.")
    pid = spawn_detached("farm")
    if pid is None:
        return ("Launched the farm but it never appeared in the process list. "
                "Check !log.")
    msg = [f"Farm started (pid {pid}), detached -- it now survives a bot restart."]
    if with_watchdog:
        wd = spawn_detached("watchdog", pid)
        msg.append(f"Watchdog started (pid {wd}), no deadline." if wd
                   else "Watchdog did NOT come up -- nothing is supervising the farm.")
    else:
        msg.append("No watchdog -- nothing will restart it if it wedges.")
    blog(" ".join(msg))
    return " ".join(msg)


def do_stop(close_game=True):
    """Stop the automation. Closes the client too, unless told to keep it.

    Leaving the client logged in after the bot stops is a half-finished state:
    the account sits idle in-game for hours, and the next start then attaches
    to a backgrounded window, which costs the first three mines.
    """
    killed = []
    for p in wd_procs():
        kill_tree(p)
        killed.append(f"watchdog {p.pid}")
    for p in farm_procs():
        kill_tree(p)
        killed.append(f"farm {p.pid}")
    lines = [f"Stopped: {', '.join(killed)}" if killed else "Nothing was running."]
    time.sleep(2)
    lines.extend(shutdown_board(close_game))
    lines.extend(session_summary())
    blog(" | ".join(lines))
    return "\n".join(lines)


def session_summary():
    """What the run actually produced: gems, how long, and the rate.

    Read back out of the farm log rather than held in memory, because the
    process that knew is the one being killed -- and because a controller can
    be started at any time and still summarise a run it did not launch.

    The gem total is the LAST accepted reading minus the first. Rejected
    readings never enter the log as "Gems now", so a clipped OCR read cannot
    inflate or deflate the figure; at worst the end point is a few minutes
    stale, which the elapsed time below is measured against anyway.
    """
    log = LOGDIR / "farm_run.log"
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    marker = "=== farm start "
    run = text[text.rfind(marker):] if marker in text else text
    if not run.strip():
        return []

    gems = [int(g) for g in re.findall(r"Gems now (\d+) \(", run)]
    stamps = re.findall(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ ", run,
                        re.MULTILINE)
    done = len(re.findall(r"Mine \d+ DONE", run))
    failed = len(re.findall(r"Mine \d+ FAILED", run))

    out = []
    hours = None
    if len(stamps) >= 2:
        fmt = "%Y-%m-%d %H:%M:%S"
        span = (datetime.strptime(stamps[-1], fmt)
                - datetime.strptime(stamps[0], fmt)).total_seconds()
        if span > 0:
            hours = span / 3600.0
            h, m = divmod(int(span // 60), 60)
            out.append(f"Ran for {h}h{m:02d}m.")

    if len(gems) >= 2:
        gained = gems[-1] - gems[0]
        # The ACCOUNT's figure, not the farm's output, and the difference is
        # not small: the counter moves for the operator's own play and for
        # marches landing while the client is shut, and with the client now
        # shut for most of a run those are exactly the gaps the operator plays
        # in. 2026-09-16 into 09-17 the counter rose 1,240 overnight with the
        # game closed. Only the mail's gathering reports say who gathered what,
        # so until those are read this number must not be labelled as the bot's.
        line = f"Gems on the account: {gems[0]:,} -> {gems[-1]:,} ({gained:+,})"
        if hours and hours >= 0.05:
            line += f", {gained / hours:,.0f}/h"
        out.append(line)
    elif gems:
        out.append(f"Gems on the account: {gems[0]:,} (only one reading, no total)")

    if done or failed:
        pct = 100.0 * done / (done + failed)
        line = f"Mines: {done} done / {failed} failed ({pct:.0f}%)"
        if hours and hours >= 0.05:
            line += f", {done / hours:.1f} done/h"
        out.append(line)
    return out


def ap_burn_text():
    """One line on the AP burn switch, for !ap and the menu."""
    from rok_farm import ap_burn

    on, at, by = ap_burn.switch_state()
    when = f" (set {datetime.fromtimestamp(at):%Y-%m-%d %H:%M} by {by})" if at else ""
    if on:
        last, fill = ap_burn.last_run()
        ran = (f" Last run {datetime.fromtimestamp(last):%m-%d %H:%M}, bar "
               f"{fill * 100:.0f}%." if last else " It has not run yet.")
        return (f"AP burn is ON{when}: with the bar {ap_burn.AP_BURN_AT * 100:.0f}%+ "
                f"full and a march slot free, the farm sends the game's barbarian "
                f"auto (needs the monthly pass).{ran} `!ap off` turns it off.")
    return (f"AP burn is OFF{when}: the farm leaves the action points alone. "
            f"`!ap on` turns it back on.")


def do_ap_burn(on, by):
    """Flip the switch. A running farm reads it at its next decision."""
    from rok_farm import ap_burn

    ap_burn.set_enabled(on, by)
    blog(f"AP burn switched {'ON' if on else 'OFF'} by {by}")
    return (f"AP burn is now {'ON' if on else 'OFF'}. A running farm picks this "
            f"up at its next look at the bar -- no restart needed.")


def do_report():
    try:
        r = subprocess.run(roles.command("report"), cwd=str(PROJECT),
                           capture_output=True, text=True, timeout=120,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return f"report failed: {type(e).__name__}: {e}"


HELP = """```
!status          farm/watchdog/game state + counters for the current run
!shot            screenshot of the game right now (falls back to newest saved)
!log [n]         last n interesting log lines (default 25, debug stripped)
!report          full run report from report.py
!feed on|off     live progress: mines, marches, queue, gather-time maths
!check           stop waiting and look at the queue now (troops home early)
!ap              AP burn (the game's barbarian auto): on or off
!ap on|off       switch it -- off for an account without the monthly pass
!stats [period]  gems/hour since yesterday; or today, 24h, 7d, 2026-09-23
!map [period]    map book: ground not reached, ground gone over (default today)
!runs            today's runs out of the city, one line each
!run [n]         one run's path, view by view (default: the latest)
!start           start farm + watchdog
!start solo      start the farm with no watchdog
!start force     start even if someone is using the machine
!stop            stop farm + watchdog, close the game, ESP32 jitter off
!stop keep       ...but leave the game running
!help            this
```"""

