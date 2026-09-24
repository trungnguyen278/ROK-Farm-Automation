"""Gems the farm brings in an hour, by hour of the day -- spending left out.

The numbers come from rok_farm.reports.gem_rate (the Discord bot's !stats
uses the same): rises of the HUD gem balance between readings of a running
farm, never the falls (the operator spending, or the game taking some back).

    .venv\\Scripts\\python tools\\dev\\gem_rate.py [--since "2026-09-23"]
                                                  [--png chart.png]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rok_farm import reports  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-09-11")
    ap.add_argument("--until", default=None)
    ap.add_argument("--png", default=None, help="also write the bar chart here")
    args = ap.parse_args()

    r = reports.gem_rate(args.since, args.until)
    print(f"since {args.since}: {r.gems:.0f} gems in {r.hours:.1f} h of running "
          f"farm = {r.rate:.0f} gems/h")
    print("\nhour  run-h   gems   gems/h   marched-for")
    for h in range(24):
        g, s = r.hour.get(h, (0.0, 0.0))
        if s < 60:
            continue
        print(f" {h:02d}  {s / 3600:5.1f}  {g:5.0f}   {g / (s / 3600):6.0f}"
              f"   {r.marched.get(h, 0):6.0f}")
    print("\nband              run-h   gems   gems/h")
    for name, lo, hi in reports.BANDS:
        g, hrs = r.band(lo, hi)
        if hrs > 0:
            print(f" {name} {lo:02d}-{hi:02d}".ljust(18) + f"{hrs:5.1f}  {g:5.0f}"
                  f"   {g / hrs:6.0f}")
    print("\nday         run-h   gems   gems/h")
    for day, (g, s) in sorted(r.day.items()):
        if s > 600:
            print(f" {day}  {s / 3600:5.1f}  {g:5.0f}   {g / (s / 3600):6.0f}")
    print(f"\nfalls (spending or taken back), not counted: {len(r.falls)}, "
          f"total {sum(d for _, d in r.falls)}")
    for when, d in sorted(r.falls, key=lambda f: f[1])[:8]:
        print(f"   {when}  {d}")
    print(f"rises over {reports.MAX_RISE} (rewards/misreads), not counted: "
          f"{len(r.odd)}")
    for when, d in r.odd[:8]:
        print(f"   {when}  +{d}")
    if args.png:
        Path(args.png).write_bytes(reports.rate_chart(r))
        print(f"\nchart: {args.png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
