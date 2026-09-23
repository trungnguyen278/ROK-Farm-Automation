"""How sure is each "on the world map" verdict? The castle-glyph scores.

detect._find_city_btn calls the world map when the castle glyph on the
bottom-right Space button out-scores the map glyph and clears
SPACE_CASTLE_MIN (rok_farm/config.py). This reads every
"space_castle=A vs space_map=B -> WORLD" line in the farm log, prints the
scores in 0.05 bins, and for each verdict under 0.90 what came next: a
position read that parsed (the world map really was up) or "Map position
unparsed" with the city's power total (it was not).

2026-09-24 01:47: 1322 verdicts -- 1162 at 0.95-1.00, 160 at 0.719-0.783
(loading screen, maintenance notice, city HUD), none from 0.80 to 0.95.

Usage:
    .venv\\Scripts\\python tools\\dev\\castle_scores.py
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "logs" / "overnight" / "farm_run.log"
WORLD = re.compile(r"space_castle=([\d.]+) vs space_map=([\d.]+) -> WORLD")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=str(LOG))
    ap.add_argument("--show", type=int, default=20,
                    help="how many of the latest low verdicts to list")
    args = ap.parse_args()

    lines = open(args.log, encoding="utf-8",
                 errors="replace").read().splitlines()
    bins: Counter = Counter()
    low = []
    for i, line in enumerate(lines):
        m = WORLD.search(line)
        if not m:
            continue
        castle, space_map = float(m.group(1)), float(m.group(2))
        bins[int(castle * 20) / 20.0] += 1
        if castle >= 0.90:
            continue
        after = "?"
        for nxt in lines[i + 1:i + 60]:
            if "Map position unparsed" in nxt:
                after = "not the world map: " + nxt.split("unparsed:")[-1].strip()
                break
            if "map step:" in nxt or "Home map is" in nxt or "City is" in nxt:
                after = "a position read parsed"
                break
            if "space_castle=" in nxt:
                after = "next check " + nxt.split("space_castle=")[-1][:28]
                break
        low.append((line[:19], castle, space_map, after))

    print(f"{sum(bins.values())} WORLD verdicts")
    for b in sorted(bins):
        print(f"  castle {b:.2f}-{b + 0.05:.2f}: {bins[b]}")
    print(f"{len(low)} under 0.90; the latest {min(args.show, len(low))}:")
    for row in low[-args.show:]:
        print("  %s  castle %.3f  map %.3f  %s" % row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
