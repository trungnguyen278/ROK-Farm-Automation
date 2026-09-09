"""Remote control for the gem farm, over Discord.

Why this exists: checking on a run meant either sitting at the machine or
spending Claude tokens on a remote session. This is a plain local process --
free to run, talks to nothing but Discord's gateway, and exposes a small fixed
set of verbs.

It is a SWITCH AND A WINDOW, not a brain. It cannot diagnose a wedged farm and
it does not try; watchdog2.py still owns restarts. Everything !status prints is
a summary of the log, not a judgement that the run is healthy.

Process discovery is stateless -- the farm and watchdog are found by scanning
command lines, so the bot can be restarted at any time and still control a run
it did not launch.

Setup: see tools/remote/README.md
Run:   .venv\\Scripts\\python tools\\remote\\discord_bot.py
"""

from __future__ import annotations

import asyncio
import ctypes
import io
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT = Path(r"D:\ROK Farm Automation")
sys.path.insert(0, str(PROJECT))

import discord
from discord.ext import tasks
import psutil

PYTHON = PROJECT / ".venv" / "Scripts" / "python.exe"
OVERNIGHT = PROJECT / "tools" / "dev" / "overnight"
FARM_SCRIPT = OVERNIGHT / "farm_full.py"
WD_SCRIPT = OVERNIGHT / "watchdog2.py"
REPORT_SCRIPT = OVERNIGHT / "report.py"
LOGDIR = PROJECT / "logs" / "overnight"
FARM_LOG = LOGDIR / "farm_run.log"
WD_LOG = LOGDIR / "watchdog.log"
BOT_LOG = LOGDIR / "discord_bot.log"
SHOTS = PROJECT / "screenshots" / "gem_farm_test"

SERIAL_PORT = "COM13"
# Below this many seconds of input idleness, assume a human is at the machine.
# Starting the farm then means the ESP32 fights the player for the mouse.
HUMAN_IDLE_GUARD = 300.0
WATCH_POLL = 60.0


# --------------------------------------------------------------------------
# config

def load_env(path):
    """Minimal .env reader. Avoids adding python-dotenv for six lines of work."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        # Pasting a whole "KEY=value" line onto a template that already ends in
        # "KEY=" leaves the name doubled. Discord then answers 401 with a token
        # whose shape still looks plausible, so strip it rather than debug it.
        if val.startswith(key + "="):
            val = val[len(key) + 1:].strip()
        os.environ.setdefault(key, val)


load_env(PROJECT / ".env")

def as_int(name):
    """Read a numeric id, or 0 if it is absent or not a number."""
    raw = (os.environ.get(name, "") or "").strip()
    return int(raw) if raw.isdigit() else 0


TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
CHANNEL_ID = as_int("DISCORD_CHANNEL_ID")

# The owner may be given either way round. "Copy User ID" and "Copy Username"
# sit next to each other in the same right-click menu and the first setup
# pasted the username, so accept both rather than crash on it. Usernames are
# globally unique under Discord's handle system, so either is a real identity;
# the id is the more durable one because a handle can be changed.
_owner_raw = (os.environ.get("DISCORD_OWNER_ID", "") or "").strip().lstrip("@")
OWNER_ID = int(_owner_raw) if _owner_raw.isdigit() else 0
OWNER_NAME = "" if _owner_raw.isdigit() else _owner_raw.lower()


def is_owner(user):
    if OWNER_ID:
        return user.id == OWNER_ID
    if OWNER_NAME:
        return (user.name or "").lower() == OWNER_NAME
    return False


def blog(msg):
    """ASCII-only stdout (Windows cp1252 crashes on anything else), UTF-8 file."""
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    try:
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)
    except Exception:
        pass
    try:
        LOGDIR.mkdir(parents=True, exist_ok=True)
        with BOT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------
# processes

def find_procs(needle):
    out = []
    for p in psutil.process_iter(["name", "cmdline", "create_time"]):
        try:
            name = (p.info["name"] or "").lower()
            if "python" not in name:
                continue
            if needle in " ".join(p.info["cmdline"] or []):
                out.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return out


def farm_procs():
    return find_procs("farm_full.py")


def wd_procs():
    return find_procs("watchdog2.py")


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


def release_hid():
    """Turn off the ESP32's idle micro-jitter and let go of the port.

    _tab_out() switches jitter ON while the bot is tabbed away. Killing the
    farm mid-jitter leaves the board nudging the pointer, which is intolerable
    when the human wants their machine back -- so every stop comes through here.
    """
    try:
        from serial_comm.connection import SerialConnection
        from serial_comm.command_buffer import CommandBuffer
    except Exception as e:
        return f"HID: import failed ({type(e).__name__})"
    conn = SerialConnection(port=SERIAL_PORT)
    try:
        if not conn.connect():
            return "HID: could not open the board (unplugged, or still held)"
        cmd = CommandBuffer(conn)
        cmd.start()
        cmd.send("IDLE", "0")
        cmd.stop()
        conn.disconnect()
        return "HID: idle jitter OFF, port released"
    except Exception as e:
        try:
            conn.disconnect()
        except Exception:
            pass
        return f"HID: release failed ({type(e).__name__}: {e})"


# --------------------------------------------------------------------------
# log reading

ANSI = re.compile(r"\x1b\[[0-9;]*m")
TS = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
# Capture-thread chatter runs forever regardless of whether the flow is making
# progress, so it is not evidence of life and never the "last interesting line".
NOISE = re.compile(r"(capture\.screen_capture|vision\.template_cache|"
                   r"\[DEBUG  \]|Queue OCR \(try)")

STAT = {
    "done":       re.compile(r"Mine \d+ DONE"),
    "failed":     re.compile(r"Mine \d+ FAILED"),
    "march":      re.compile(r"March sent"),
    "march_fail": re.compile(r"March did NOT fire"),
    "fog":        re.compile(r"FOG \(out of kingdom\)"),
    "fog_saved":  re.compile(r"Fog vanished on re-check"),
    "empty":      re.compile(r"no icons"),
    "restart":    re.compile(r"Restarting the game: (?!waiting )"),
    "recovery":   re.compile(r"attempting recovery"),
}
# The flow prints the queue five different ways. Matching only "Queue: N/M"
# made status report 4/5 for a burst the log had already reconciled to 5/5.
# "Queue OCR (try 1/3)" is a retry counter, not a queue, and must NOT match.
QUEUE = re.compile(
    r"Queue(?:\s+likely)?\s*(?:full\s*\(|reconciled:|reconcile:|:)\s*(\d+)/(\d+)")

# A logger line: "2026-09-09 08:25:42,147 [INFO   ] gem_farm_test: ...".
# Nearly every event is written twice -- once by the logger and once by the
# pretty printer -- so the feed keeps only the pretty half. Dropping the logger
# half halves the traffic and loses nothing: where both exist the pretty
# wording is the fuller one ("Troops home in ~25min -- too long to sit here"
# against "Computed wait 1387s -> quit+relaunch").
LOGPFX = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ \[\w+\s*\] [\w.]+: ")

# What counts as progress worth pushing to the phone. Deliberately not every
# INFO line -- scan chatter and click coordinates would bury the events that
# actually say what the farm is doing.
FEED = re.compile(
    r"Mine \d+ (?:DONE|FAILED)"
    r"|March sent|March did NOT fire"
    r"|Queue(?:\s+likely)?\s*(?:full\s*\(|reconciled:|:)\s*\d+/\d+"
    r"|March time .*est\. gather"
    r"|Troops home in"
    r"|Staying out for|Still out, \d+ min to go"
    r"|Wait check:"
    r"|Restarting the game"
    r"|FOG \(out of kingdom\)|Retreating inland|Fog vanished on re-check"
    r"|consecutive empty scans"
    r"|attempting recovery|Client vanished"
    r"|Phase: "
    r"|farm start|FARM EXITED"
)


def feed_clean(line):
    """Strip colour codes and the pretty printer's own [TAG] gutter."""
    s = ANSI.sub("", line).rstrip()
    return re.sub(r"^\s*\[(?:INFO|PASS|WARN|FAIL|DEBUG)\]\s*", "", s).strip()
STILL_OUT = re.compile(r"Still out, (\d+) min to go")
STAY_OUT = re.compile(r"Staying out for ([\d.]+) min")


def log_tail(path, chars=600000):
    if not path.exists():
        return ""
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > chars:
            fh.seek(size - chars)
        raw = fh.read()
    return ANSI.sub("", raw.decode("utf-8", errors="replace"))


def current_segment(text):
    """The log since the last farm start banner, plus that start time.

    The log is appended across restarts on purpose, so cumulative counts would
    mix days together. Status is only ever about the run happening now.
    """
    idx = text.rfind("=== farm start ")
    if idx < 0:
        return text, "(start banner older than the tail)"
    m = TS.search(text[idx:idx + 80])
    return text[idx:], m.group(1) if m else "(unknown)"


def last_mine_time(lines):
    """When the most recent mine finished.

    "Mine N DONE" comes from the pretty printer and carries no timestamp of its
    own, so it inherits the last stamped line above it.
    """
    seen, found = None, None
    for ln in lines:
        m = TS.search(ln)
        if m:
            seen = m.group(1)
        if STAT["done"].search(ln) or STAT["failed"].search(ln):
            found = seen
    if not found:
        return None
    try:
        return datetime.strptime(found, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def interesting_tail(lines, n):
    keep = [ln.rstrip() for ln in lines if ln.strip() and not NOISE.search(ln)]
    return keep[-n:]


def uptime_str(proc):
    try:
        secs = time.time() - proc.create_time()
    except psutil.Error:
        return "?"
    h, rem = divmod(int(secs), 3600)
    return f"{h}h{rem // 60:02d}m" if h else f"{rem // 60}m"


def build_status():
    farms, wds = farm_procs(), wd_procs()
    game = game_proc()
    seg, started = current_segment(log_tail(FARM_LOG))
    lines = seg.splitlines()
    c = {k: sum(bool(p.search(ln)) for ln in lines) for k, p in STAT.items()}

    out = ["```"]
    if farms:
        out.append(f"farm     : UP   pid={farms[0].pid}  up {uptime_str(farms[0])}")
    else:
        out.append("farm     : DOWN")
    out.append(f"watchdog : {'UP   pid=' + str(wds[0].pid) if wds else 'DOWN'}")
    out.append(f"game     : {'UP' if game else 'DOWN'}")
    out.append(f"segment  : started {started}")

    attempts = c["done"] + c["failed"]
    rate = f"  ({100.0 * c['done'] / attempts:.0f}% ok)" if attempts else ""
    out.append(f"mines    : {c['done']} done / {c['failed']} failed{rate}")
    out.append(f"marches  : {c['march']} sent, {c['march_fail']} did not fire")
    out.append(f"fog      : {c['fog']} bail(s), {c['fog_saved']} false bail(s) blocked")
    out.append(f"scans    : {c['empty']} empty")
    out.append(f"trouble  : {c['restart']} fault restart(s), {c['recovery']} recovery")

    q = [m for ln in lines for m in [QUEUE.search(ln)] if m]
    if q:
        out.append(f"queue    : last {q[-1].group(1)}/{q[-1].group(2)}")

    last = last_mine_time(lines)
    if last:
        mins = (datetime.now() - last).total_seconds() / 60.0
        out.append(f"last mine: {last:%H:%M:%S}  ({mins:.0f} min ago)")

    # A planned wait produces no mines BY DESIGN. Without this line a healthy
    # 25-minute gather reads as a hang.
    tail_txt = "\n".join(lines[-400:])
    still = STILL_OUT.findall(tail_txt)
    stay = STAY_OUT.findall(tail_txt)
    if still:
        out.append(f"waiting  : planned wait, {still[-1]} min to go "
                   f"(client closed on purpose)")
    elif stay:
        out.append(f"waiting  : planned wait of {stay[-1]} min started")

    tail = interesting_tail(lines, 3)
    if tail:
        out.append("")
        out.append("last lines:")
        for ln in tail:
            out.append("  " + ln[:110])
    out.append("```")
    return "\n".join(out)


# --------------------------------------------------------------------------
# screenshots

def grab_game_window():
    """JPEG of the client's client-area right now, or None if it is not up."""
    try:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
        import cv2
        import mss
        import numpy as np
        import win32gui
        import win32process

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
            return None
        ox, oy, w, h = hits[0]
        with mss.mss() as sct:
            shot = sct.grab({"left": ox, "top": oy, "width": w, "height": h})
        frame = np.array(shot, dtype=np.uint8)[:, :, :3]
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        return buf.tobytes() if ok else None
    except Exception as e:
        blog(f"grab failed: {type(e).__name__}: {e}")
        return None


def newest_saved_shot():
    if not SHOTS.exists():
        return None
    pics = sorted(SHOTS.glob("*.png"), key=lambda p: p.stat().st_mtime)
    return pics[-1] if pics else None


# --------------------------------------------------------------------------
# actions

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def spawn_detached(script, *args):
    """Launch a script so it outlives this process, and return its real pid.

    An ordinary subprocess is a child, and killing the bot's process tree kills
    it too -- restarting the bot to load new code took a live farm down with it
    once, mid-run. CREATE_BREAKAWAY_FROM_JOB does not help, because the kill
    walks parent->child links rather than the job. `cmd /c start` returns as
    soon as it has launched, so cmd exits and leaves the real process with a
    dead parent: the chain from the bot is broken before anyone follows it.

    The pid `start` hands back is cmd's, so the real one is found by watching
    for a process that was not there before.
    """
    name = Path(script).name
    before = {p.pid for p in find_procs(name)}
    subprocess.Popen(
        ["cmd", "/c", "start", "", "/b", str(PYTHON), str(script),
         *(str(a) for a in args)],
        cwd=str(PROJECT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
    deadline = time.time() + 25.0
    while time.time() < deadline:
        fresh = {p.pid for p in find_procs(name)} - before
        if fresh:
            return min(fresh)
        time.sleep(0.5)
    return None


def do_start(with_watchdog):
    if farm_procs():
        return "Farm is already running -- !stop first."
    pid = spawn_detached(FARM_SCRIPT)
    if pid is None:
        return ("Launched the farm but it never appeared in the process list. "
                "Check !log.")
    msg = [f"Farm started (pid {pid}), detached -- it now survives a bot restart."]
    if with_watchdog:
        wd = spawn_detached(WD_SCRIPT, pid)
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
    lines.append(release_hid())
    if close_game:
        g = game_proc()
        if g:
            try:
                kill_tree(g)
                lines.append("Game closed.")
            except Exception as e:
                lines.append(f"Game close failed: {e}")
        else:
            lines.append("Game was not running.")
    blog(" | ".join(lines))
    return "\n".join(lines)


def do_report():
    try:
        r = subprocess.run([str(PYTHON), str(REPORT_SCRIPT)], cwd=str(PROJECT),
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
!start           start farm + watchdog
!start solo      start the farm with no watchdog
!start force     start even if someone is using the machine
!stop            stop farm + watchdog, close the game, ESP32 jitter off
!stop keep       ...but leave the game running
!help            this
```"""


# --------------------------------------------------------------------------
# bot

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

_alert_channel = None
_farm_was_up = False
_feed_on = True
_feed_pos = None

FEED_POLL = 20.0
FEED_MAX_LINES = 14


def read_new_feed_lines():
    """Progress lines appended to the farm log since the last check."""
    global _feed_pos
    if not FARM_LOG.exists():
        return []
    size = FARM_LOG.stat().st_size
    if _feed_pos is None or _feed_pos > size:
        # First look, or the file got shorter (never in append mode, but a
        # hand-deleted log would). Start at the end so the channel does not
        # get a dump of everything that already happened.
        _feed_pos = size
        return []
    if size == _feed_pos:
        return []
    with FARM_LOG.open("rb") as fh:
        fh.seek(_feed_pos)
        raw = fh.read(size - _feed_pos)
    # Leave a trailing partial line for the next pass -- the farm writes line
    # buffered, so a read can land mid-line.
    cut = raw.rfind(b"\n")
    if cut < 0:
        return []
    _feed_pos += cut + 1
    out = []
    for ln in raw[:cut].decode("utf-8", errors="replace").splitlines():
        if LOGPFX.match(ANSI.sub("", ln)):
            continue
        if FEED.search(ln):
            s = feed_clean(ln)
            if s:
                out.append(s)
    return out


@tasks.loop(seconds=FEED_POLL)
async def feeder():
    """Push farm progress to the channel as it happens."""
    if not _feed_on:
        read_new_feed_lines()   # keep the position current, so switching the
        return                  # feed back on does not replay a backlog
    lines = read_new_feed_lines()
    if not lines:
        return
    ch = await alert_target()
    if ch is None:
        return
    extra = max(0, len(lines) - FEED_MAX_LINES)
    if extra:
        lines = lines[-FEED_MAX_LINES:]
    body = "\n".join(ln[:120] for ln in lines)
    if extra:
        body = f"(+{extra} earlier lines skipped)\n" + body
    try:
        await ch.send(f"```\n{body[:1850]}\n```")
    except Exception as e:
        blog(f"feed send failed: {type(e).__name__}: {e}")


async def reply(message, text):
    chunks = [text[i:i + 1900] for i in range(0, len(text), 1900)] or [""]
    for chunk in chunks:
        await message.channel.send(chunk)


@tasks.loop(seconds=WATCH_POLL)
async def watcher():
    """Say something when the farm dies without being asked to.

    The point of remote control is not having to poll from a phone.
    """
    global _farm_was_up
    up = bool(farm_procs())
    if _farm_was_up and not up:
        ch = await alert_target()
        if ch is not None:
            lines = interesting_tail(log_tail(FARM_LOG, 200000).splitlines(), 6)
            body = "\n".join("  " + ln[:110] for ln in lines)
            await ch.send(
                f"**Farm stopped** at {datetime.now():%H:%M:%S}.\n```\n{body}\n```")
            blog("alerted: farm went down")
        else:
            blog("farm went down but no channel to alert in")
    _farm_was_up = up


async def alert_target():
    """The channel unprompted alerts go to, resolved late.

    Resolving once at startup meant a bot that was launched before being
    invited stayed mute forever, because on_ready never fires again. This
    re-checks until it finds the channel.
    """
    global _alert_channel
    if _alert_channel is not None:
        return _alert_channel
    if not CHANNEL_ID:
        return None
    ch = client.get_channel(CHANNEL_ID)
    if ch is None:
        try:
            ch = await client.fetch_channel(CHANNEL_ID)
        except Exception:
            ch = None
    _alert_channel = ch
    return ch


async def announce(why):
    ch = await alert_target()
    if ch is None:
        blog(f"cannot reach the channel yet ({why}) -- invite the bot, "
             f"it will pick the channel up on its own")
        return False
    try:
        await ch.send(f"Bot online, {datetime.now():%H:%M}. `!help` for commands.")
        blog(f"announced in #{getattr(ch, 'name', CHANNEL_ID)} ({why})")
        return True
    except Exception as e:
        blog(f"WARNING: cannot post in the channel: {type(e).__name__}: {e}")
        return False


@client.event
async def on_ready():
    global _farm_was_up
    blog(f"connected as {client.user} (owner={OWNER_ID or OWNER_NAME}, "
         f"channel={CHANNEL_ID or 'any'}, guilds={len(client.guilds)})")
    if not client.guilds:
        app = await client.application_info()
        blog("the bot is in NO server -- open this link to invite it: "
             f"https://discord.com/api/oauth2/authorize?client_id={app.id}"
             "&permissions=101376&scope=bot")
    await announce("startup")
    _farm_was_up = bool(farm_procs())
    read_new_feed_lines()               # anchor at the end of the log
    if not watcher.is_running():
        watcher.start()
    if not feeder.is_running():
        feeder.start()


@client.event
async def on_guild_join(guild):
    blog(f"invited to '{guild.name}' ({guild.id})")
    await announce("just invited")


@client.event
async def on_message(message):
    if message.author.bot:
        return
    content = message.content.strip()
    if not content.startswith("!"):
        return
    # Fail closed. This is an outward-facing control surface for a machine with
    # a physical HID attached; only one account may drive it.
    if not is_owner(message.author):
        blog(f"REFUSED {content[:40]!r} from {message.author} ({message.author.id})")
        return
    if (CHANNEL_ID and message.channel.id != CHANNEL_ID
            and not isinstance(message.channel, discord.DMChannel)):
        return

    parts = content[1:].split()
    if not parts:
        return
    cmd, args = parts[0].lower(), [a.lower() for a in parts[1:]]
    blog(f"cmd: {content[:80]}")

    # With no channel pinned, unprompted alerts go wherever the owner last
    # spoke -- otherwise "the farm died" would have nowhere to land.
    global _alert_channel, _feed_on
    if not CHANNEL_ID:
        _alert_channel = message.channel

    try:
        if cmd in ("help", "h"):
            await reply(message, HELP)

        elif cmd in ("status", "s"):
            await reply(message, await asyncio.to_thread(build_status))

        elif cmd in ("shot", "pic", "live"):
            async with message.channel.typing():
                jpg = await asyncio.to_thread(grab_game_window)
            if jpg:
                await message.channel.send(
                    f"live, {datetime.now():%H:%M:%S}",
                    file=discord.File(io.BytesIO(jpg), "live.jpg"))
            else:
                pic = newest_saved_shot()
                if pic:
                    age = (time.time() - pic.stat().st_mtime) / 60.0
                    await message.channel.send(
                        f"game is not running -- newest saved frame "
                        f"`{pic.name}` ({age:.0f} min old)",
                        file=discord.File(str(pic)))
                else:
                    await reply(message, "No game window and no saved frames.")

        elif cmd == "log":
            n = int(args[0]) if args and args[0].isdigit() else 25
            n = max(1, min(n, 60))
            seg, _ = current_segment(log_tail(FARM_LOG))
            body = "\n".join(ln[:150] for ln in interesting_tail(seg.splitlines(), n))
            await reply(message, f"```\n{body or '(empty)'}\n```")

        elif cmd == "report":
            async with message.channel.typing():
                text = await asyncio.to_thread(do_report)
            await message.channel.send(
                "run report",
                file=discord.File(io.BytesIO(text.encode("utf-8")), "report.txt"))

        elif cmd == "feed":
            if args and args[0] in ("on", "off"):
                _feed_on = args[0] == "on"
            else:
                _feed_on = not _feed_on
            await reply(message,
                        f"progress feed **{'ON' if _feed_on else 'OFF'}** "
                        f"(checks every {FEED_POLL:.0f}s)")

        elif cmd == "start":
            idle = idle_seconds()
            if "force" not in args and 0 <= idle < HUMAN_IDLE_GUARD:
                await reply(message,
                            f"Someone used this machine {idle:.0f}s ago -- the "
                            f"ESP32 would fight them for the mouse.\n"
                            f"Send `!start force` to run anyway.")
            else:
                await reply(message,
                            await asyncio.to_thread(do_start, "solo" not in args))

        elif cmd == "stop":
            async with message.channel.typing():
                await reply(message,
                            await asyncio.to_thread(do_stop, "keep" not in args))

        else:
            await reply(message, f"unknown command `{cmd}` -- try `!help`")
    except Exception as e:
        blog(f"command failed: {type(e).__name__}: {e}")
        await reply(message, f"command failed: `{type(e).__name__}: {e}`")


def main():
    if not TOKEN:
        print("DISCORD_BOT_TOKEN missing -- put it in D:\\ROK Farm Automation\\.env")
        return 1
    if not (OWNER_ID or OWNER_NAME):
        print("DISCORD_OWNER_ID missing -- refusing to start an unlocked "
              "control surface")
        return 1
    if OWNER_NAME:
        print(f"owner locked to the username '{OWNER_NAME}'. A numeric user id "
              f"is more durable (a handle can be changed): Developer Mode ON, "
              f"right-click your name, Copy User ID.")
    blog("starting")
    client.run(TOKEN, log_handler=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
