"""Turn logs/overnight/farm_run.log into the numbers that describe a run.

status.sh answers "is it alive right now". This answers "how did it actually
do": throughput per productive hour, why mines failed, how often the recurring
faults fire, and the distributions of the two timings that are now measured in
production rather than assumed (march-panel paint, zoom-out overrun).

Counts are split per farm start, because the log is APPENDED across restarts
(deliberately -- a truncating log erases the evidence of why it restarted).

    .venv\\Scripts\\python tools\\dev\\overnight\\report.py
    .venv\\Scripts\\python tools\\dev\\overnight\\report.py --log some/other.log
"""

from __future__ import annotations

import argparse
import re
import statistics
from datetime import datetime
from pathlib import Path

DEFAULT_LOG = Path(r"d:\ROK Farm Automation\logs\overnight\farm_run.log")

ANSI = re.compile(r"\x1b\[[0-9;]*m")
TS = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

PATTERNS = {
    "done":          re.compile(r"Mine (\d+) DONE"),
    "failed":        re.compile(r"Mine (\d+) FAILED"),
    "march_ok":      re.compile(r"March sent \(queue confirmed\)"),
    "march_unver":   re.compile(r"March sent \(unverified\)"),
    "march_fail":    re.compile(r"March did NOT fire"),
    "fog":           re.compile(r"FOG \(out of kingdom\)"),
    "empty_scan":    re.compile(r"no icons"),
    "scan_giveup":   re.compile(r"consecutive empty scans"),
    "clf_reject":    re.compile(r"Classifier reject"),
    "occupied":      re.compile(r"occupied \("),
    "gather_miss":   re.compile(r"gather_btn not found"),
    "world_fail":    re.compile(r"Not on world map after toggling"),
    "restart":       re.compile(r"Restarting the game"),
    "recovery":      re.compile(r"attempting recovery"),
    "reconnect":     re.compile(r"Reconnect: popup seen"),
    "client_died":   re.compile(r"Client vanished"),
    "fog_prevented": re.compile(r"Fog vanished on re-check"),
    "retreat":       re.compile(r"Retreating inland"),
    "queue_short":   re.compile(r"slot\(s\) never filled|slot\(s\) unfilled"),
    "dup_deposit":   re.compile(r"already marched this session"),
    "marched_site":  re.compile(r"Marched to \d+:\d+"),
    "queue_full_ok": re.compile(r"Queue reconciled"),
    "wait_ontime":   re.compile(r"Wait check:.*\[ON TIME\]"),
    "wait_early":    re.compile(r"Wait check:.*\[TOO EARLY\]"),
    "wait_over":     re.compile(r"Wait check:.*\[OVERSHOT"),
}

PAINT = re.compile(r"March button painted after ([\d.]+)s")
PAINT_MISS = re.compile(r"March button did not appear")
ZOOM_EXTRA = re.compile(r"still animating after the pause; waited ([\d.]+)s")
FOG_METRICS = re.compile(r"fog: (.+?) \[lap=([\d.]+) sat=([\d.]+) hue_std=([\d.]+)\]")
QUEUE = re.compile(r"Queue: (\d+)/(\d+)")
START = re.compile(r"=== farm start (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def ts_of(line):
    m = TS.search(line)
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") if m else None


def describe(vals, unit="s"):
    if not vals:
        return "no samples"
    v = sorted(vals)
    out = (f"n={len(v)} min={v[0]:.2f}{unit} median={statistics.median(v):.2f}{unit} "
           f"max={v[-1]:.2f}{unit}")
    if len(v) > 1:
        out += f" stdev={statistics.stdev(v):.2f}"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=str(DEFAULT_LOG))
    args = ap.parse_args()

    path = Path(args.log)
    if not path.exists():
        print(f"no log at {path}")
        return 1
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = [ANSI.sub("", ln) for ln in raw.splitlines()]

    segments, cur = [], None
    for ln in lines:
        m = START.search(ln)
        if m:
            cur = {"start": m.group(1), "lines": []}
            segments.append(cur)
            continue
        if cur is None:
            cur = {"start": "(before first banner)", "lines": []}
            segments.append(cur)
        cur["lines"].append(ln)

    print("=" * 70)
    print(f"{path}   {len(lines)} lines, {len(segments)} farm start(s)")
    print("=" * 70)

    tot = {k: 0 for k in PATTERNS}
    all_paint, all_zoom, all_fog = [], [], []

    for seg in segments:
        text_lines = seg["lines"]
        counts = {k: sum(bool(p.search(ln)) for ln in text_lines)
                  for k, p in PATTERNS.items()}
        for k, v in counts.items():
            tot[k] += v

        stamped = [t for t in (ts_of(ln) for ln in text_lines) if t]
        span = ""
        mins = 0.0
        if len(stamped) >= 2:
            mins = (max(stamped) - min(stamped)).total_seconds() / 60.0
            span = (f"{min(stamped):%H:%M} -> {max(stamped):%H:%M} "
                    f"({mins:.0f} min)")

        paint = [float(m.group(1)) for ln in text_lines
                 for m in [PAINT.search(ln)] if m]
        zoom = [float(m.group(1)) for ln in text_lines
                for m in [ZOOM_EXTRA.search(ln)] if m]
        fogs = [(m.group(1), float(m.group(2)), float(m.group(3)))
                for ln in text_lines for m in [FOG_METRICS.search(ln)] if m]
        all_paint += paint
        all_zoom += zoom
        all_fog += fogs
        queues = [(int(m.group(1)), int(m.group(2)))
                  for ln in text_lines for m in [QUEUE.search(ln)] if m]

        print(f"\n--- farm start {seg['start']}   {span}")
        done, failed = counts["done"], counts["failed"]
        attempts = done + failed
        print(f"  mines      : {done} done / {failed} failed"
              + (f"   ({100.0 * done / attempts:.0f}% success)" if attempts else ""))
        if mins > 5 and done:
            print(f"  throughput : {done / (mins / 60.0):.1f} mines/hour "
                  f"(wall clock, includes waiting for troops)")
        print(f"  marches    : {counts['march_ok']} confirmed, "
              f"{counts['march_unver']} unverified, "
              f"{counts['march_fail']} DID NOT FIRE")
        print(f"  fog saved  : {counts['fog_prevented']} false bail(s) blocked "
              f"by the second-frame check; {counts['retreat']} edge retreat(s)")
        print(f"  queue      : {counts['queue_full_ok']} burst(s) reconciled full, "
              f"{counts['queue_short']} short")
        print(f"  deposits   : {counts['marched_site']} distinct marched, "
              f"{counts['dup_deposit']} duplicate(s) refused")
        print(f"  fog bails  : {counts['fog']}     "
              f"empty scans: {counts['empty_scan']}     "
              f"scan giveups: {counts['scan_giveup']}")
        print(f"  rejects    : classifier {counts['clf_reject']}, "
              f"occupied {counts['occupied']}, gather miss {counts['gather_miss']}")
        print(f"  trouble    : {counts['restart']} game restart(s), "
              f"{counts['recovery']} recovery, {counts['world_fail']} world-nav fail, "
              f"{counts['reconnect']} reconnect popup(s), "
              f"{counts['client_died']} client death(s) mid-wait")
        if queues:
            print(f"  queue      : last {queues[-1][0]}/{queues[-1][1]}, "
                  f"peak {max(q[0] for q in queues)}")
        if paint:
            print(f"  march panel paint: {describe(paint)}")
        miss = sum(bool(PAINT_MISS.search(ln)) for ln in text_lines)
        if miss:
            print(f"  march panel NEVER painted in time: {miss}x  <-- raise the timeout")

    print("\n" + "=" * 70)
    print("TOTAL")
    attempts = tot["done"] + tot["failed"]
    print(f"  mines: {tot['done']} done / {tot['failed']} failed"
          + (f"   ({100.0 * tot['done'] / attempts:.0f}% success)" if attempts else ""))
    print(f"  marches: {tot['march_ok']} confirmed / {tot['march_fail']} did not fire"
          + (f"   ({100.0 * tot['march_fail'] / (tot['march_ok'] + tot['march_fail']):.0f}% lost)"
             if (tot['march_ok'] + tot['march_fail']) else ""))
    print(f"  fog bails: {tot['fog']}   empty scans: {tot['empty_scan']}   "
          f"giveups: {tot['scan_giveup']}")
    print(f"  fog FALSE bails prevented: {tot['fog_prevented']}   "
          f"edge retreats: {tot['retreat']}")
    print(f"  bursts reconciled full: {tot['queue_full_ok']}   short: {tot['queue_short']}")
    on, early = tot["wait_ontime"], tot["wait_early"]
    if on + early:
        over = tot["wait_over"]
        print(f"  gather-time prediction: {on} tight / {early} too early / "
              f"{over} overshot")
        if over:
            print(f"    ({over} wait(s) freed more than one slot -- the estimate "
                  f"is running long, costing farm time)")
    print(f"  game restarts: {tot['restart']}   client deaths mid-wait: {tot['client_died']}")

    print("\n  MEASURED IN PRODUCTION")
    print(f"    march panel paint : {describe(all_paint)}")
    print("      (the fixed wait this replaced was 0.28s)")
    print(f"    zoom-out overrun  : {describe(all_zoom)}")
    print("      (only logged when the map was STILL moving after the human pause)")

    if all_fog:
        print("\n  FOG DECISIONS (verify any with sat<30 and high lap by eye)")
        for why, lap, sat in all_fog:
            flag = "  <-- near the colourless ceiling" if sat < 30 and lap > 400 else ""
            print(f"    {why:32s} lap={lap:7.1f} sat={sat:5.1f}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
