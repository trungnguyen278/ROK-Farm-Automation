"""Does the scan pan toward the sweep target? And who turns it?

Reads the farm log. For every ordinary pan (a map step of 3-40 tiles) taken
while a sweep target was more than 6 tiles away: the cosine between the step
and the direction to the target. And for every "steer: a -> b deg" override
by the book: did it turn the heading toward the target or away from it.

No steering at all would give about 50% toward and a mean cosine near 0.

2026-09-23 14:52 to 2026-09-24 01:10, before the fix: 381 pans, 42% toward,
mean cosine -0.12; 283 overrides, 223 of them away from the target.

Usage:
    .venv\\Scripts\\python tools\\dev\\steer_check.py
    .venv\\Scripts\\python tools\\dev\\steer_check.py --since "2026-09-24 01:30"
"""

from __future__ import annotations

import argparse
import math
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rok_farm import pan_model  # noqa: E402

LOG = ROOT / "logs" / "overnight" / "farm_run.log"
WIN_W, WIN_H = 1534, 863

TS = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
TARGET = re.compile(r"sweep: target (\d+),(\d+)")
STEP = re.compile(r"map step: (\d+) tiles \((\d+),(\d+) -> (\d+),(\d+)\)")
STEER = re.compile(r"steer: (\d+) -> (\d+) deg \(score")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-09-23 14:52")
    ap.add_argument("--log", default=str(LOG))
    args = ap.parse_args()

    cosines: list[float] = []
    toward = away = overrides = 0
    tgt = cam = None
    started = False
    with open(args.log, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = TS.match(line)
            if not started:
                if m and m.group(1) >= args.since:
                    started = True
                else:
                    continue
            m = TARGET.search(line)
            if m:
                tgt = (int(m.group(1)), int(m.group(2)))
                continue
            m = STEER.search(line)
            if m:
                overrides += 1
                if tgt and cam:
                    want = math.atan2(tgt[1] - cam[1], tgt[0] - cam[0])
                    a = pan_model.tile_heading(math.radians(float(m.group(1))),
                                               WIN_W, WIN_H)
                    b = pan_model.tile_heading(math.radians(float(m.group(2))),
                                               WIN_W, WIN_H)
                    if math.cos(b - want) > math.cos(a - want):
                        toward += 1
                    else:
                        away += 1
                continue
            m = STEP.search(line)
            if not m:
                continue
            n = int(m.group(1))
            a = (int(m.group(2)), int(m.group(3)))
            b = (int(m.group(4)), int(m.group(5)))
            cam = b
            if not 3 <= n <= 40 or tgt is None:
                continue
            dx, dy = tgt[0] - a[0], tgt[1] - a[1]
            if max(abs(dx), abs(dy)) <= 6:
                continue
            sx, sy = b[0] - a[0], b[1] - a[1]
            d1, d2 = math.hypot(dx, dy), math.hypot(sx, sy)
            if d2:
                cosines.append((dx * sx + dy * sy) / (d1 * d2))

    print(f"since {args.since}: {len(cosines)} pans with a target, "
          f"{overrides} book override(s)")
    if cosines:
        share = sum(c > 0 for c in cosines) / len(cosines)
        print(f"  toward the target {share:.0%}, cosine mean "
              f"{statistics.mean(cosines):+.2f} median "
              f"{statistics.median(cosines):+.2f}")
    if toward or away:
        print(f"  overrides turning toward the target {toward}, away {away}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
