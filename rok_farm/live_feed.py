"""The farm, live: its log turned into what it is doing now and the events
worth telling -- for the Discord bot's live panel and its alerts.

The panel is one message the bot edits in place: what the farm is doing this
moment, today's counts, the last few events. An alert is a message of its
own, for what someone should look at: a mine that failed (with the reason and
the frame the farm saved), the farm stopping, the watchdog, a locked screen.

It replaced a feed that posted raw log lines in a code block every twenty
seconds. The operator, 2026-09-29: those lines look ugly; show what the farm
is doing, failures included, and make it look professional.

Kept free of Discord: the bot turns the specs here into embeds, exactly as it
does for reports.py.
"""

from __future__ import annotations

import re
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path

from rok_farm import reports

ANSI = re.compile(r"\x1b\[[0-9;]*m")
STAMP = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
GUTTER = re.compile(r"^\s*\[(?:INFO|PASS|WARN|FAIL|DEBUG| -- )\]\s*")

# Icons as escapes so the source stays ASCII.
I_FARM, I_DOWN, I_WAIT, I_AP = "\U0001F7E2", "\U0001F534", "\u23F3", "\U0001F525"
I_DONE, I_FAIL, I_MARCH, I_RESTART = "\u2705", "\u274C", "\U0001F6A9", "\U0001F501"
I_START, I_STOP, I_WARN, I_TRAIN = "\u25B6\uFE0F", "\u23F9\uFE0F", "\u26A0\uFE0F", "\u2694\uFE0F"
I_LOCK, DOT = "\U0001F512", "\u00B7"

MINE = re.compile(r"\*\*\* MINE (\d+) \*\*\*")
STEP = re.compile(r"--- \[m(\d+)\] (?:Step \d+: )?(.+?) ---")
CITY_IDLE = re.compile(r"--- \[city_idle\] Return to city ---")
SCAN = re.compile(r"Scan\s+(\d+)/(\d+):")
MARCHED = re.compile(r"Marched to (\d+):(\d+) \(\d+ deposit")
HOME_IN = re.compile(r"March time .*home in ~(\d+)m")
DONE = re.compile(r"Mine (\d+) DONE")
FAILED = re.compile(r"Mine (\d+) FAILED")
FAIL_WHY = re.compile(r"\[FAIL\]\s*(.+)")
EMPTY_WHY = re.compile(r"(\d+) consecutive empty scans")
SKIPPED = re.compile(r"Mine (\d+) skipped: (.+)")
WAIT = re.compile(r"Troops home in ~([\d.]+)(min|s) -- (quitting the client, back in "
                  r"~(\d+)min|alt-tab out for ([\d.]+)min|staying on the game screen "
                  r"for ([\d.]+)min|shorter than)")
VIGIL = re.compile(r"Phase: alt-tab away, waiting for troops to return \(cap (\d+)min\)")
STILL_OUT = re.compile(r"Still out, (\d+) min to go")
RESTART = re.compile(r"Game restart: (.+)")
AP_START = re.compile(r"AP burn started: dwell (\d+)s")
AP_OVER = re.compile(r"AP dwell over")
TRAINED = re.compile(r"training: (\d+) batch\(es\) started")
QUEUE = re.compile(r"Queue(?:\s+likely)?\s*(?:full\s*\(|reconciled:|:)\s*(\d+)/(\d+)"
                   r"|nothing out: 0/(\d+)")
GEMS = re.compile(r"Gems now (\d+) \(")
FARM_START = re.compile(r"=== farm start")
FARM_EXIT = re.compile(r"FARM EXITED")
WATCHDOG = re.compile(r"WATCHDOG: (.+)")
LOCKED = re.compile(r"Windows (?:is )?still locked|Windows is locked")
MAINTENANCE = re.compile(r"maintenance: (.+)")

STEP_WORDS = {
    "Ensure world map @ icon-zoom": "heading out to the world map",
    "Scan + verify gem mines": "scanning for gems",
    "Click Gather": "opening the deposit",
    "Troop + March": "sending the march",
    "Stay on world map, re-zoom": "zooming back out",
    "Return to city": "back to the city",
}
WAIT_EVENT_MIN = 3.0
WAIT_HOW = {"quitting": "client closed", "alt-tab": "alt-tabbed out",
            "staying": "on the game screen", "shorter": "in place",
            "vigil": "alt-tabbed, until the troops-home notice"}


def epoch(stamp: str) -> float:
    return time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S"))


def hhmm(t: float) -> str:
    return time.strftime("%H:%M", time.localtime(t))


@dataclass
class Event:
    t: float
    kind: str               # done failed march wait restart ap train start exit warn
    text: str
    mine: int | None = None
    detail: str = ""
    alert: bool = False     # worth a message of its own
    since: float | None = None      # a failed mine: when it began (its frames)


@dataclass
class LiveState:
    """What the farm is doing, rebuilt from its log one line at a time."""
    stamp: float = 0.0
    run_start: float | None = None
    mine: int | None = None
    mine_start: float | None = None
    step: str | None = None
    scan: tuple | None = None
    queue: tuple | None = None
    wait_how: str | None = None
    wait_until: float | None = None
    ap_until: float | None = None
    gems: int | None = None
    gems_day_start: int | None = None
    day: str = ""
    today: Counter = field(default_factory=Counter)
    events: deque = field(default_factory=lambda: deque(maxlen=12))
    last_march: str | None = None
    home_in: int | None = None       # "home in ~N m", printed before the march
    why: str | None = None
    last_mine: Event | None = None

    def _new_day(self, day: str) -> None:
        self.day = day
        self.today = Counter()
        self.gems_day_start = self.gems

    def _event(self, kind, text, mine=None, detail="", alert=False) -> Event:
        e = Event(self.stamp, kind, text, mine, detail, alert)
        self.events.append(e)
        return e

    def feed(self, raw: str) -> list[Event]:
        """One line of the farm log; the events it produced (usually none)."""
        line = ANSI.sub("", raw).rstrip()
        m = STAMP.match(line)
        if m:
            self.stamp = epoch(m.group(1))
            if m.group(1)[:10] != self.day:
                self._new_day(m.group(1)[:10])
        text = GUTTER.sub("", line)
        out: list[Event] = []

        if FARM_START.search(text):
            self.run_start, self.mine, self.step, self.scan = self.stamp, None, None, None
            self.wait_how = self.wait_until = self.ap_until = None
            out.append(self._event("start", f"{I_START} Farm started"))
        elif FARM_EXIT.search(text):
            out.append(self._event("exit", f"{I_STOP} Farm exited", alert=True))
        elif (m := MINE.search(text)):
            self.mine, self.mine_start = int(m.group(1)), self.stamp
            self.step, self.scan, self.why = "starting", None, None
            self.wait_how = self.wait_until = None
        elif (m := STEP.search(text)):
            self.step = STEP_WORDS.get(m.group(2), m.group(2))
            if self.step != "scanning for gems":
                self.scan = None
        elif CITY_IDLE.search(text):
            self.step, self.scan = "in the city, troops out", None
        elif (m := SCAN.search(text)):
            self.scan = (int(m.group(1)), int(m.group(2)))
        elif (m := HOME_IN.search(text)):
            self.home_in = int(m.group(1))
        elif (m := MARCHED.search(text)):
            self.last_march = f"{m.group(1)}:{m.group(2)}"
            self.today["marches"] += 1
            home = f" {DOT} home in ~{self.home_in} min" if self.home_in else ""
            self.home_in = None
            out.append(self._event("march", f"{I_MARCH} March to {self.last_march}{home}",
                                   self.mine))
        elif (m := DONE.search(text)):
            n = int(m.group(1))
            self.today["done"] += 1
            where = f" {DOT} {self.last_march}" if self.last_march else ""
            e = self._event("done", f"{I_DONE} Mine {n} done{where}", n)
            self.last_mine = e
            out.append(e)
        elif (m := FAIL_WHY.search(line)):
            self.why = m.group(1).strip()
        elif (m := EMPTY_WHY.search(text)):
            self.why = f"{m.group(1)} empty scans in a row"
        elif (m := SKIPPED.search(text)):
            self.why = m.group(2).strip()
        elif (m := FAILED.search(text)):
            n = int(m.group(1))
            self.today["failed"] += 1
            e = self._event("failed", f"{I_FAIL} Mine {n} failed", n,
                            detail=self.why or "no reason in the log", alert=True)
            e.since = self.mine_start
            self.last_mine = e
            out.append(e)
        elif (m := WAIT.search(text)):
            how = m.group(3).split()[0]
            if m.group(4):
                mins = float(m.group(4))
            elif m.group(5) or m.group(6):
                mins = float(m.group(5) or m.group(6))
            else:
                mins = float(m.group(1)) / (60.0 if m.group(2) == "s" else 1.0)
            self.wait_how = WAIT_HOW.get(how, how)
            self.wait_until = self.stamp + mins * 60
            self.step, self.scan = None, None
            # A minute or two between mines is not news; it only pushed the
            # events worth reading out of the panel's short list.
            if mins >= WAIT_EVENT_MIN:
                out.append(self._event("wait", f"{I_WAIT} Waiting ~{mins:.0f} min "
                                               f"({self.wait_how})"))
        elif (m := VIGIL.search(text)):
            self.wait_how = WAIT_HOW["vigil"]
            self.wait_until = self.stamp + int(m.group(1)) * 60
            self.step, self.scan = None, None
        elif (m := STILL_OUT.search(text)):
            self.wait_until = self.stamp + int(m.group(1)) * 60
        elif (m := RESTART.search(text)):
            self.today["restarts"] += 1
            out.append(self._event("restart", f"{I_RESTART} Client restart: "
                                              f"{m.group(1).strip()}"))
        elif (m := AP_START.search(text)):
            self.ap_until = self.stamp + int(m.group(1))
            self.today["ap"] += 1
            out.append(self._event("ap", f"{I_AP} AP burn, ~{int(m.group(1)) // 60} min "
                                         f"on screen"))
        elif AP_OVER.search(text):
            self.ap_until = None
        elif (m := TRAINED.search(text)):
            out.append(self._event("train", f"{I_TRAIN} Training: {m.group(1)} "
                                            f"batch(es) started"))
        elif (m := QUEUE.search(text)):
            self.queue = ((int(m.group(1)), int(m.group(2))) if m.group(1)
                          else (0, int(m.group(3))))
        elif (m := GEMS.search(text)):
            self.gems = int(m.group(1))
            if self.gems_day_start is None:
                self.gems_day_start = self.gems
        elif (m := WATCHDOG.search(text)):
            out.append(self._event("warn", f"{I_WARN} Watchdog: {m.group(1).strip()}",
                                   alert=True))
        elif LOCKED.search(text):
            out.append(self._event("warn", f"{I_LOCK} {text.strip()}", alert=True))
        elif (m := MAINTENANCE.search(text)) and "clock is out" not in text:
            out.append(self._event("warn", f"{I_WARN} Maintenance: {m.group(1).strip()}"))
        return out


def replay(state: LiveState, text: str, since_day: str) -> None:
    """Feed a stretch of the log to rebuild the state at startup; the caller
    sends no alerts for what it returns. Lines before `since_day`
    (YYYY-MM-DD) are skipped, so the counts are that day's."""
    started = False
    for raw in text.splitlines():
        if not started:
            m = STAMP.match(ANSI.sub("", raw))
            if not m or m.group(1)[:10] < since_day:
                continue
            started = True
        state.feed(raw)


# --------------------------------------------------------------------------
# what the bot shows

def _mins_left(until: float | None, now: float) -> str:
    if until is None:
        return ""
    left = max(0.0, until - now) / 60.0
    return f", ~{left:.0f} min left" if left >= 1 else ", any moment"


def panel_spec(s: LiveState, farm_up: bool, watchdog_up: bool, now: float) -> dict:
    """The live panel: the state leads, in the title and its colour."""
    if not farm_up:
        title, colour = f"{I_DOWN} Farm is not running", reports.COLOUR_BAD
    elif s.ap_until and s.ap_until > now:
        title = f"{I_AP} Burning AP{_mins_left(s.ap_until, now)}"
        colour = reports.COLOUR_WAIT
    elif s.wait_until and s.wait_until > now - 120:
        title = f"{I_WAIT} Waiting for the troops{_mins_left(s.wait_until, now)}"
        colour = reports.COLOUR_WAIT
    elif s.mine is not None:
        scan = f" ({s.scan[0]}/{s.scan[1]})" if s.scan else ""
        title = f"{I_FARM} Mine {s.mine} {DOT} {s.step or 'working'}{scan}"
        colour = reports.COLOUR_OK
    else:
        title, colour = f"{I_FARM} Farm is up", reports.COLOUR_OK

    head = []
    if s.run_start:
        head.append(f"Run since **{hhmm(s.run_start)}**")
    if s.queue:
        head.append(f"queue **{s.queue[0]}/{s.queue[1]}**")
    if s.gems is not None:
        day = (f" ({s.gems - s.gems_day_start:+,} today)"
               if s.gems_day_start is not None else "")
        head.append(f"gems **{s.gems:,}**{day}")
    desc = f" {DOT} ".join(head)
    if farm_up and s.wait_how and s.wait_until and s.wait_until > now - 120 \
            and not (s.ap_until and s.ap_until > now):
        desc += f"\nWaiting {s.wait_how}."
    if farm_up and not watchdog_up:
        desc += f"\n{I_WARN} No watchdog: nothing restarts the farm if it wedges."

    t = s.today
    tried = t["done"] + t["failed"]
    pct = f" ({100.0 * t['done'] / tried:.0f}%)" if tried else ""
    fields = [("Today", f"**{t['marches']}** marches {DOT} **{t['done']}** done "
                        f"{DOT} {t['failed']} failed{pct}", True)]
    if s.last_mine is not None:
        e = s.last_mine
        extra = f": {e.detail}" if e.kind == "failed" else ""
        fields.append(("Last mine", f"{e.text}{extra} {DOT} {hhmm(e.t)}", True))
    recent = [e for e in s.events][-8:]
    if recent:
        lines = [f"`{hhmm(e.t)}` {e.text}" + (f" {DOT} *{e.detail[:70]}*"
                                             if e.kind == "failed" else "")
                 for e in reversed(recent)]
        fields.append(("Recent", "\n".join(lines)[:1024], False))
    return {"title": title, "description": desc, "colour": colour,
            "fields": fields, "image": None,
            "footer": "Live panel, refreshed as the farm works"}


def alert_spec(e: Event, s: LiveState, image: str | None = None) -> dict:
    """A message of its own: a failed mine with its reason, or a warning."""
    if e.kind == "failed":
        t = s.today
        fields = [("When", hhmm(e.t), True),
                  ("Today", f"{t['done']} done {DOT} {t['failed']} failed", True)]
        return {"title": f"{I_FAIL} Mine {e.mine} failed",
                "description": e.detail, "colour": reports.COLOUR_BAD,
                "fields": fields, "image": image,
                "footer": "The frame is the last one the farm saved for this mine"
                if image else None}
    return {"title": e.text[:256], "description": e.detail,
            "colour": reports.COLOUR_BAD if e.kind == "exit" else reports.COLOUR_WAIT,
            "fields": [("When", hhmm(e.t), True)], "image": None, "footer": None}


# The frames the flow saves when something is wrong, before any scan frame.
_TELLING = re.compile(r"_[A-Z][A-Z_]+_\d{6}\.png$")


def failure_frame(mine: int, since: float, shots: Path) -> Path | None:
    """The frame to show for a failed mine: the newest diagnostic frame the
    flow saved for it (NO_CANDIDATES, ZOOM_STUCK, ...), else its newest frame.
    Mine numbers restart every run, so only frames since the mine began."""
    if not shots.exists():
        return None
    mine_frames = [p for p in shots.glob(f"m{mine}_*.png")
                   if p.stat().st_mtime >= since - 2]
    if not mine_frames:
        return None
    telling = [p for p in mine_frames if _TELLING.search(p.name)]
    pool = telling or mine_frames
    return max(pool, key=lambda p: p.stat().st_mtime)
