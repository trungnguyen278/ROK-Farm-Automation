"""How much of each day was the game client actually up?

Not the click stream -- an alt-tab wait produces no clicks but leaves the
client running and connected, which is exactly the case the rest rule is
about. The signal used here is the farm's own quit decisions and the moment it
next sees a window.

  "-> quit+relaunch" / "quit spacing"   the farm decided to close the client
  "Found window 'Rise of Kingdoms'"     a window exists again

Offline = from a quit line to the next Found window. Everything else the
account is connected, including every alt-tab.
"""
import collections
import datetime
import glob
import re

TS = r"^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d)"
QUIT = re.compile(TS + r".*(quit\+relaunch|quit spacing|Restarting the game|"
                       r"Game restart|ending the AP run)")
SEEN = re.compile(TS + r".*Found window 'Rise of Kingdoms'")
ANY = re.compile(TS)


def when(m):
    return datetime.datetime.strptime(m.group(1) + " " + m.group(2),
                                      "%Y-%m-%d %H:%M:%S")


events = []
for f in sorted(glob.glob("logs/gem_farm_test_*.log")):
    try:
        fh = open(f, encoding="utf-8", errors="replace")
    except OSError:
        continue
    with fh:
        for line in fh:
            if "discord." in line:
                continue
            m = QUIT.match(line)
            if m:
                events.append((when(m), "quit"))
                continue
            m = SEEN.match(line)
            if m:
                events.append((when(m), "seen"))
events.sort()

offline = collections.defaultdict(float)
quits = collections.Counter()
first = {}
last = {}
pending = None
for t, kind in events:
    day = t.strftime("%Y-%m-%d")
    first.setdefault(day, t)
    last[day] = t
    if kind == "quit":
        if pending is None:
            pending = t
            quits[day] += 1
    elif pending is not None:
        gap = (t - pending).total_seconds() / 3600.0
        if 0 < gap < 3.0:          # a sane relaunch, not an overnight stop
            offline[pending.strftime("%Y-%m-%d")] += gap
        pending = None

print("%-12s %7s %7s %8s %9s   %s" %
      ("day", "span h", "quits", "off h", "online h", "outcome"))
KNOWN = {"2026-09-13": "reclaim 3,006", "2026-09-16": "warning",
         "2026-09-17": "CLEAN", "2026-09-18": "warning + 2,708"}
for day in sorted(first):
    span = (last[day] - first[day]).total_seconds() / 3600.0
    if span < 1.0:
        continue
    off = offline.get(day, 0.0)
    print("%-12s %7.1f %7d %8.1f %9.1f   %s"
          % (day, span, quits[day], off, max(0.0, span - off),
             KNOWN.get(day, "")))
