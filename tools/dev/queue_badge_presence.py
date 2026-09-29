"""Is the march-queue badge on screen? Measured on saved frames.

The game hides the "N/5" badge -- and the blue expand icon beside it --
when no march is out. The farm read that as "OCR failed" and fell back on
its burst counter, which on 2026-09-29 12:31 said 5/5 with nothing out:
an 18-minute quit and a 15-minute toast vigil with five slots free.

"No text at all" does not mean "no badge": of 205 empty reads in September
followed by a good one, 178 had troops out (transitions, loading frames).
So this measures a picture-level signal instead -- the icon's template
score at its fixed place -- on frames labelled from the log:

  present  a queue read of N >= 1 within 20 s of the frame
  absent   the next read (within 180 s) equals the marches sent since the
           frame, so nothing was out when it was taken

usage: .venv\\Scripts\\python tools\\dev\\queue_badge_presence.py
           [--logs "logs/gem_farm_test_20260929_*.log"] [--shots DIR]
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import os
import re
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rok_farm.queue_ocr import badge_icon_score  # noqa: E402

READ = re.compile(r"^(\S+ \S+),\d+ .*Queue OCR \(try \d/\d\): '([^']*)'")
MARCH = re.compile(r"^(\S+ \S+),\d+ .*Marched to deposit")
BADGE = re.compile(r"(\d)\s*/\s*(\d)\s*$")


def epoch(stamp: str) -> float:
    return dt.datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").timestamp()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default="logs/gem_farm_test_2026092[89]_*.log")
    ap.add_argument("--shots", default="screenshots/gem_farm_test")
    a = ap.parse_args()

    reads, marches = [], []
    for log in sorted(glob.glob(str(ROOT / a.logs))):
        with open(log, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = READ.match(line)
                if m:
                    b = BADGE.search(m.group(2))
                    if b:
                        reads.append((epoch(m.group(1)), int(b.group(1))))
                    continue
                m = MARCH.match(line)
                if m:
                    marches.append(epoch(m.group(1)))
    reads.sort()
    marches.sort()
    if not reads:
        print("no queue reads in", a.logs)
        return 1

    scores = {"present": [], "absent": []}
    names = {"present": [], "absent": []}
    for path in glob.glob(str(ROOT / a.shots / "*.png")):
        t = os.path.getmtime(path)
        if t < reads[0][0] - 60 or t > reads[-1][0] + 60:
            continue
        near = [n for tr, n in reads if abs(tr - t) <= 20]
        label = None
        if near and min(near) >= 1:
            label = "present"
        else:
            nxt = next(((tr, n) for tr, n in reads if t < tr <= t + 180), None)
            if nxt and nxt[1] >= 1:
                sent = sum(1 for tm in marches if t < tm <= nxt[0])
                if sent == nxt[1]:
                    label = "absent"
        if label is None:
            continue
        frame = cv2.imread(path)
        if frame is None or frame.shape[:2] != (862, 1533):
            continue
        scores[label].append(badge_icon_score(frame))
        names[label].append(os.path.basename(path))

    for label in ("present", "absent"):
        v = np.array(scores[label])
        if not len(v):
            print(f"{label:8s} n=0")
            continue
        print(f"{label:8s} n={len(v):4d}  min {v.min():.2f}  p5 {np.percentile(v, 5):.2f}  "
              f"p50 {np.median(v):.2f}  p95 {np.percentile(v, 95):.2f}  max {v.max():.2f}")
    for label, pick in (("present", np.argmin), ("absent", np.argmax)):
        if scores[label]:
            i = int(pick(scores[label]))
            print(f"  worst {label}: {names[label][i]} score {scores[label][i]:.2f}")

    # By the kind of frame: a panel over the corner hides the icon with
    # troops out, so what matters is the plain views the queue is read on.
    kinds: dict = {}
    for label in ("present", "absent"):
        for name, s in zip(names[label], scores[label]):
            kind = re.sub(r"^m\d+_|_\d{6}\.png$|_\d{2}$", "", name)
            kind = re.sub(r"_\d{2}$", "", kind)
            kinds.setdefault((label, kind), []).append(s)
    plain = re.compile(r"(scan_\d\d|icon_zoom|city_idle_return_city|after_march)_\d{6}\.png$")
    odd = sorted((s, n) for n, s in zip(names["present"], scores["present"])
                 if plain.search(n) and s < 0.6)
    print("\nplain views labelled present but under 0.6:")
    for s, n in odd:
        print(f"  {s:.2f}  {n}")
    print("\nby kind (label, kind: n, share under 0.6, lowest):")
    for (label, kind), v in sorted(kinds.items(), key=lambda kv: (kv[0][0], -len(kv[1]))):
        v = np.array(v)
        print(f"  {label:8s} {kind:28s} n={len(v):4d}  under 0.6: {np.mean(v < 0.6):4.0%}"
              f"  lowest {v.min():.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
