"""Draw ONE scan run: from leaving the city to coming back to it.

The operator, 2026-09-24: track_map mixes every run together; one run --
out of the city and back -- is what shows whether the path itself is right.
Drawn by rok_farm.reports.run_map (the Discord bot's !run draws the same):
every view numbered in order, S and E, cells green where the run showed new
ground and yellow/orange/red where it went over ground seen in the stale
window before it; sweep targets, marches and the city on top.

    .venv\\Scripts\\python tools\\dev\\run_map.py --list [--since "2026-09-24 07:56"]
    .venv\\Scripts\\python tools\\dev\\run_map.py --run 12        (index from --list)
    .venv\\Scripts\\python tools\\dev\\run_map.py --all --since "2026-09-24 07:56"
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rok_farm import reports  # noqa: E402

OUT = ROOT / "screenshots" / "runs"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=time.strftime("%Y-%m-%d 00:00"))
    ap.add_argument("--run", type=int, default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--stale-h", type=float, default=reports.SWEEP_STALE_H)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    book = reports.load_book()
    city = tuple(book.get("city") or reports.CITY_DEFAULT)
    track = book.get("track", [])
    runs = reports.read_runs(args.since)
    if not runs:
        print("no runs since", args.since)
        return 1
    if args.list or (args.run is None and not args.all):
        print(" idx  start     min  views marches failed farthest  new/shown"
              "  re-scan%  crossings")
        for idx, run in enumerate(runs):
            s = reports.run_summary(run, track, city, args.stale_h)
            print(f"{idx:4d}  {time.strftime('%H:%M:%S', time.localtime(run[0]))}"
                  f" {(run[1] - run[0]) / 60:5.1f} {s['views']:5d} {s['marches']:7d}"
                  f" {s['failed']:6d} {s['farthest']:8d}  {s['new']:4d}/{s['shown']:<4d}"
                  f"  {100 * s['rescan']:6.0f}  {s['crossings']:9d}")
        return 0
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for idx in (range(len(runs)) if args.all else [args.run]):
        png, _s = reports.run_map(runs[idx], idx, book, args.stale_h)
        path = out_dir / (f"run_{idx:03d}_"
                          f"{time.strftime('%m%d_%H%M', time.localtime(runs[idx][0]))}.png")
        path.write_bytes(png)
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
