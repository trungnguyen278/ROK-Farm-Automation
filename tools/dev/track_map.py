"""Draw where the scan has NOT been, and where it has been over and over.

The operator, 2026-09-23: "phai ve duoc ra thi moi biet cho nao chua den va
cho nao bi lap". Drawn by rok_farm.reports.book_map (the Discord bot's !map
draws the same): left, cells within the sweep radius not seen in the stale
window before the end of the period; right, how often each cell was in view
during it. Rebuilt from the camera track the book keeps, cut to the period.

    .venv\\Scripts\\python tools\\dev\\track_map.py --since "2026-09-24 01:43"
        [--until "2026-09-24 07:55"] [--stale-h 2] [--out file.png]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rok_farm import reports  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=datetime.now().strftime("%Y-%m-%d 00:00"))
    ap.add_argument("--until", default=None)
    ap.add_argument("--stale-h", type=float, default=reports.SWEEP_STALE_H)
    ap.add_argument("--book", default=None)
    ap.add_argument("--out", default=str(ROOT / "screenshots" / "track_map.png"))
    ap.add_argument("--radius", type=int, default=200)
    args = ap.parse_args()

    book = reports.load_book(Path(args.book) if args.book else None)
    png, s = reports.book_map(args.since, args.until, args.stale_h,
                              args.radius, 3, book)
    if png is None:
        print("no track points in that period")
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png)
    print(out)
    print(f"{s['views']} views; not reached {s['not_reached']}/{s['cells']} within "
          f"{reports.SWEEP_RADIUS} ({s['near_not_reached']}/{s['near_cells']} within "
          f"80); repeats {s['repeats']}; {s['views_per_cell']:.1f} views per seen "
          f"cell; marches {s['marches']}"
          + (f", median {s['march_median']} tiles out, max {s['march_max']}"
             if s["march_median"] is not None else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
