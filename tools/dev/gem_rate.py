"""Gems the farm brings in an hour, by hour of the day -- spending left out.

Reads the farm log's "Gems now N" lines (the account balance off the HUD,
read after armies come home). Between two readings of the same run (no
"Gem counter starts" between them, less than MAX_GAP_MIN apart):

  * a rise is gems brought home -- counted, unless it is larger than
    MAX_RISE (a march carries 10-20; bigger rises are rewards, purchases or
    a misread -- listed, not counted);
  * a fall is the operator spending, or the game taking some back -- never
    counted against the farm, only listed.

Time counted is the time between readings of a running farm, so hours the
farm was stopped do not dilute the rate. A rise is put in the hour its
reading falls in, with the time since the reading before it.

The deploy panel's "load=N" (gems the deposit held when the army was sent)
is summed by the hour of the march as a second, OCR-independent measure.

    .venv\\Scripts\\python tools\\dev\\gem_rate.py [--since "2026-09-11"]
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "logs" / "overnight" / "farm_run.log"
MAX_GAP_MIN = 45
MAX_RISE = 120

TS = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
NOW = re.compile(r"Gems now (\d+)")
START = re.compile(r"Gem counter starts at (\d+)")
LOAD = re.compile(r"Deploy panel: march=\d+s .*load=(\d+)")
BANDS = [("night 00-06", 0, 6), ("morning 06-12", 6, 12),
         ("afternoon 12-18", 12, 18), ("evening 18-24", 18, 24)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-09-11")
    ap.add_argument("--log", default=str(LOG))
    args = ap.parse_args()

    gain = defaultdict(float)      # hour of day -> gems
    secs = defaultdict(float)      # hour of day -> seconds of running farm
    loads = defaultdict(float)     # hour of day -> gems marched for
    by_day = defaultdict(lambda: [0.0, 0.0])
    falls, odd = [], []
    last = None                    # (t, balance)
    for line in open(args.log, encoding="utf-8", errors="replace"):
        m = TS.match(line)
        if not m or m.group(1) < args.since:
            continue
        t = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
        hour = int(m.group(1)[11:13])
        if START.search(line):
            last = (t, int(START.search(line).group(1)))
            continue
        lm = LOAD.search(line)
        if lm and int(lm.group(1)) <= 100:
            loads[hour] += int(lm.group(1))
            continue
        nm = NOW.search(line)
        if not nm:
            continue
        bal = int(nm.group(1))
        if last is not None and 0 < t - last[0] <= MAX_GAP_MIN * 60:
            d = bal - last[1]
            dt = t - last[0]
            secs[hour] += dt
            by_day[m.group(1)[:10]][1] += dt
            if 0 < d <= MAX_RISE:
                gain[hour] += d
                by_day[m.group(1)[:10]][0] += d
            elif d > MAX_RISE:
                odd.append((m.group(1), d))
            elif d < 0:
                falls.append((m.group(1), d))
        last = (t, bal)

    tot_g = sum(gain.values())
    tot_h = sum(secs.values()) / 3600
    print(f"since {args.since}: {tot_g:.0f} gems in {tot_h:.1f} h of running farm"
          f" = {tot_g / max(tot_h, 1e-9):.0f} gems/h")
    print("\nhour  run-h   gems   gems/h   marched-for")
    for h in range(24):
        if secs[h] < 60:
            continue
        hrs = secs[h] / 3600
        print(f" {h:02d}  {hrs:5.1f}  {gain[h]:5.0f}   {gain[h] / hrs:6.0f}   {loads[h]:6.0f}")
    print("\nband              run-h   gems   gems/h")
    for name, lo, hi in BANDS:
        g = sum(gain[h] for h in range(lo, hi))
        s = sum(secs[h] for h in range(lo, hi)) / 3600
        if s > 0:
            print(f" {name:16s} {s:5.1f}  {g:5.0f}   {g / s:6.0f}")
    print("\nday         run-h   gems   gems/h")
    for day in sorted(by_day):
        g, s = by_day[day]
        if s > 600:
            print(f" {day}  {s / 3600:5.1f}  {g:5.0f}   {g / (s / 3600):6.0f}")
    print(f"\nfalls (spending or taken back), not counted: {len(falls)}, "
          f"total {sum(d for _, d in falls)}")
    for when, d in sorted(falls, key=lambda f: f[1])[:8]:
        print(f"   {when}  {d}")
    print(f"rises over {MAX_RISE} (rewards/misreads), not counted: {len(odd)}")
    for when, d in odd[:8]:
        print(f"   {when}  +{d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
