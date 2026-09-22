"""Pair each deposit with the march time that followed it, and find home."""
import re, datetime
import numpy as np
from pathlib import Path

TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
DEP = re.compile(r"Marched to deposit 4096 (\d+):(\d+)")
MT = re.compile(r"March time (?:(\d+)m)?(\d+)s")

last = None
pend = None
pairs = []
with Path("logs/overnight/farm_run.log").open(encoding="utf-8", errors="replace") as fh:
    for line in fh:
        m = TS.match(line)
        if m:
            last = datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        d = DEP.search(line)
        if d:
            pend = (int(d.group(1)), int(d.group(2)), last)
            continue
        t = MT.search(line)
        if t and pend:
            secs = int(t.group(1) or 0) * 60 + int(t.group(2))
            if pend[2] and pend[2] >= datetime.datetime(2026, 9, 20):
                pairs.append((pend[0], pend[1], secs, pend[2]))
            pend = None

print("deposit/march-time pairs: %d" % len(pairs))
xs = np.array([p[0] for p in pairs]); ys = np.array([p[1] for p in pairs])
ts = np.array([p[2] for p in pairs]) / 60.0

# Home: the shortest marches must start next to the city.
quick = ts < 3.0
print("marches under 3 min: %d" % quick.sum())
if quick.sum() >= 5:
    hx, hy = np.median(xs[quick]), np.median(ys[quick])
    print("  their deposits centre on %.0f:%.0f  -- that is home's neighbourhood" % (hx, hy))
    d = np.hypot(xs - hx, ys - hy)
    print("")
    print("%-14s %6s %9s" % ("distance", "n", "median march"))
    for lo, hi in [(0,30),(30,60),(60,100),(100,160),(160,240),(240,10**9)]:
        sel = (d >= lo) & (d < hi)
        if sel.sum():
            print("%4d - %4d tiles %6d %8.1f min" % (lo, min(hi,999), sel.sum(), np.median(ts[sel])))
    print("")
    for lim in (60, 100, 140, 180):
        sel = d > lim
        print("  beyond %3d tiles: %3d marches (%.0f%%), median %.1f min"
              % (lim, sel.sum(), 100*sel.mean(), np.median(ts[sel]) if sel.sum() else 0))
