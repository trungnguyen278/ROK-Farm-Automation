"""Run from the repo root: .venv/Scripts/python tools/dev/utc_day_stats.py [MM-DD] ["YYYY-MM-DD HH:MM"]
(the second argument lists every farm run of the UTC day starting then)

Per UTC day (local 07:00 -> 07:00, UTC+7): how long the client was up, how
many logins (client starts), quits, waits by kind, and marches -- per account
(map 4096 = main, 3560 = second). From the farm's own per-run logs.

  login   the first "Found window" after the game was not running (a cold
          start, "Window ... not found") or after a quit ("Game restart:")
  quit    "Game restart: ..." (a planned or recovery quit) or a run ending
          with the game closed (the next run found no window)
  up      from a login to the next quit / run end
  waits   "Wait prediction <kind>:" -- one per finished wait, by kind

Operator's own play is invisible here (no farm, no log).
"""
import datetime as dt
import glob
import re
import sys
from collections import Counter, defaultdict

TS = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
UTC = dt.timedelta(hours=7)


def utc_day(t):
    return (t - UTC).strftime("%m-%d")


runs = []
for path in sorted(glob.glob("logs/gem_farm_test_2026*.log")):
    ev = []
    maps = Counter()
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = TS.match(line)
            if not m or "discord." in line:
                continue
            t = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            if "Window 'Rise of Kingdoms' not found" in line:
                ev.append((t, "absent"))
            elif "Found window 'Rise of Kingdoms'" in line:
                ev.append((t, "seen"))
            elif "gem_farm_test: Game restart:" in line:
                ev.append((t, "quit"))
            elif "Marched to deposit" in line:
                ev.append((t, "march"))
                mm = re.search(r"Marched to deposit (\d+) ", line)
                if mm:
                    maps[mm.group(1)] += 1
            elif "Wait prediction " in line:
                kind = line.split("Wait prediction ", 1)[1].split(":", 1)[0]
                ev.append((t, "wait:" + kind))
            elif "#4096" in line or "'4096'" in line:
                maps["4096"] += 1
            elif "#3560" in line or "'3560'" in line:
                maps["3560"] += 1
            ev.append((t, "line"))
    if not any(k == "seen" for _t, k in ev):
        continue                        # not a farm run (bot, watchdog, report)
    acct = "main" if maps["4096"] >= maps["3560"] else "second"
    runs.append((ev[0][0], ev[-1][0], acct, ev))
runs.sort()

stats = defaultdict(Counter)            # (day, acct) -> counters
up_s = defaultdict(float)


def add_up(a, b, acct):
    """Split an up interval over UTC days."""
    while a < b:
        day_end = dt.datetime.combine((a - UTC).date() + dt.timedelta(days=1),
                                      dt.time()) + UTC
        c = min(b, day_end)
        up_s[(utc_day(a), acct)] += (c - a).total_seconds()
        a = c


for i, (start, end, acct, ev) in enumerate(runs):
    state = None                         # None unknown, "up", "down"
    up_since = None
    for t, kind in ev:
        if kind == "absent":
            if state == "up" and up_since:
                add_up(up_since, t, acct)
            state, up_since = "down", None
        elif kind == "seen":
            if state in (None, "down"):
                if state == "down":
                    stats[(utc_day(t), acct)]["logins"] += 1
                state, up_since = "up", t
        elif kind == "quit":
            stats[(utc_day(t), acct)]["quits"] += 1
            if state == "up" and up_since:
                add_up(up_since, t, acct)
            state, up_since = "down", None
        elif kind == "march":
            stats[(utc_day(t), acct)]["marches"] += 1
        elif kind.startswith("wait:"):
            stats[(utc_day(t), acct)][kind] += 1
    if state == "up" and up_since:
        add_up(up_since, end, acct)
        # A run that ends with the game up: the game stayed open if the next
        # run found it already running (no "not found" as it started) -- then
        # the gap between the runs is online too; otherwise the stop closed it.
        nxt = runs[i + 1] if i + 1 < len(runs) else None
        kept = (nxt is not None
                and not any(k == "absent" for _t, k in nxt[3][:60])
                and (nxt[0] - end).total_seconds() < 8 * 3600)
        if kept:
            add_up(end, nxt[0], acct)
        else:
            stats[(utc_day(end), acct)]["quits"] += 1
            stats[(utc_day(end), acct)]["stops"] += 1

OUTCOME = {"09-13": "reclaim 3,006 + warning (letter 09-14 08:52Z)",
           "09-16": "warning (letter 09-17 07:55Z)",
           "09-17": "nothing",
           "09-18": "warning + reclaim 2,708 (letter 09-19)",
           "09-23": "warning + 12 h march ban (letter 09-24 08:52Z)",
           "09-28": "24 h march ban? (letter 09-29 09:51Z)",
           "09-29": "24 h march ban at 09:51Z (09-29 16:51 local)"}
since = sys.argv[1] if len(sys.argv) > 1 else "09-10"
print("UTCday acct   up_h logins quits (stops) in/out_per_h  alt-tab screen quitW inplace  marches  outcome")
for (day, acct) in sorted(set(stats) | set(up_s)):
    if day < since:
        continue
    c = stats[(day, acct)]
    h = up_s[(day, acct)] / 3600.0
    if h < 0.2 and not c["marches"]:
        continue
    rate = (c["logins"] + c["quits"]) / h if h else 0
    print(f"{day}  {acct:6s} {h:5.1f} {c['logins']:6d} {c['quits']:5d} ({c['stops']:2d})"
          f"      {rate:5.1f}      {c['wait:alt-tab']:6d} {c['wait:screen']:6d} "
          f"{c['wait:quit']:5d} {c['wait:in-place']:7d}  {c['marches']:7d}  "
          f"{OUTCOME.get(day, '') if acct == 'main' else ''}")

if len(sys.argv) > 2:
    lo = dt.datetime.strptime(sys.argv[2], "%Y-%m-%d %H:%M")
    hi = lo + dt.timedelta(days=1)
    for start, end, acct, ev in runs:
        if end < lo or start > hi:
            continue
        kinds = Counter(k for _t, k in ev)
        print(f"  run {start:%m-%d %H:%M} -> {end:%m-%d %H:%M} {acct:6s} "
              f"seen {kinds['seen']:4d} absent {kinds['absent']:2d} quits {kinds['quit']:2d} "
              f"marches {kinds['march']:3d} lines {kinds['line']:6d}")
