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
import subprocess
import sys
import time
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
    if hwnd is None or not focus_window(hwnd):
        taskkill("MASS.exe")
        return "Game: could not focus it, so ALT+F4 would hit the wrong window -- killed instead."

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
        cmd.send("IDLE", "0")
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
    """
    before = {p.pid for p in find_procs(role)}
    subprocess.Popen(
        ["cmd", "/c", "start", "", "/b", *roles.command(role, *args)],
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
    if farm_procs():
        return "Farm is already running -- !stop first."
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
    blog(" | ".join(lines))
    return "\n".join(lines)


def do_report():
    try:
        r = subprocess.run(roles.command("report"), cwd=str(PROJECT),
                           capture_output=True, text=True, timeout=120)
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
!start           start farm + watchdog
!start solo      start the farm with no watchdog
!start force     start even if someone is using the machine
!stop            stop farm + watchdog, close the game, ESP32 jitter off
!stop keep       ...but leave the game running
!help            this
```"""

