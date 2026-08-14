r"""Measure the layer-1 screen-state signals against the live client.

Thresholds in this project are measured, never guessed (see the fog and night
notes in rok_farm/config.py). Run this once per screen state, then read the
summary to pick the gates.

    .venv\Scripts\python tools\dev\measure_state_signals.py --label city
    .venv\Scripts\python tools\dev\measure_state_signals.py --label world
    .venv\Scripts\python tools\dev\measure_state_signals.py --label panel
    .venv\Scripts\python tools\dev\measure_state_signals.py --summary

Signals measured:
  liveness  mean |diff| between consecutive frames on a 160x90 gray downscale.
            A live view animates (water, flags, troops); a frozen or crashed
            client repeats one frame. This is the signal the current
            _client_looks_broken check is missing -- it only notices when
            capture returns nothing at all.
  dim_ratio centre brightness / border brightness. ROK darkens the background
            behind a modal, so an open panel should push this well above a
            clean view.
  views     what the city/world discriminators score right now.

Results append to logs/state_signals.json so runs can be compared.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np

from capture.screen_capture import ScreenCapture
from rok_farm.config import LOG_DIR, TEMPLATE_DIR
from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher

OUT_FILE = LOG_DIR / "state_signals.json"
SMALL = (160, 90)


def small_gray(frame: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(cv2.resize(frame, SMALL, interpolation=cv2.INTER_AREA),
                        cv2.COLOR_BGR2GRAY).astype(np.int16)


def dim_ratio(frame: np.ndarray) -> tuple[float, float, float]:
    """Mean brightness of the outer 10% ring vs the centre box."""
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mx, my = int(w * 0.10), int(h * 0.10)
    ring = np.ones(gray.shape, dtype=bool)
    ring[my:h - my, mx:w - mx] = False
    centre = gray[int(h * 0.22):int(h * 0.78), int(w * 0.28):int(w * 0.72)]
    border_mean = float(gray[ring].mean())
    centre_mean = float(centre.mean())
    return border_mean, centre_mean, (centre_mean / border_mean if border_mean else 0.0)


def measure(label: str, samples: int, gap: float) -> dict:
    sc = ScreenCapture()
    win = sc.find_window()
    if not win:
        sys.exit("Game window not found -- open the game first.")
    print(f"window {win['width']}x{win['height']}, sampling {samples}x every {gap}s\n")

    frames = []
    for _ in range(samples):
        f = sc.grab_full()
        if f is not None:
            frames.append(f)
        time.sleep(gap)
    if len(frames) < 2:
        sys.exit("not enough frames captured")

    diffs = []
    prev = None
    for f in frames:
        g = small_gray(f)
        if prev is not None:
            diffs.append(float(np.abs(g - prev).mean()))
        prev = g

    border, centre, ratio = dim_ratio(frames[-1])

    cache = TemplateCache(TEMPLATE_DIR)
    matcher = TemplateMatcher(cache, threshold=0.30)
    views = {}
    for name in ("buttons/city_btn", "buttons/world_map_city_btn",
                 "states/city_view", "states/world_map",
                 "ui/city_food", "ui/city_wood"):
        if cache.get(name) is None:
            views[name] = None
            continue
        m = matcher.match_single(frames[-1], name)
        views[name] = round(m.confidence, 3) if m else 0.0

    result = {
        "label": label,
        "when": datetime.now().isoformat(timespec="seconds"),
        "window": f"{win['width']}x{win['height']}",
        "liveness": {
            "samples": [round(d, 3) for d in diffs],
            "mean": round(statistics.mean(diffs), 3),
            "min": round(min(diffs), 3),
            "max": round(max(diffs), 3),
        },
        "dim": {"border": round(border, 1), "centre": round(centre, 1),
                "ratio": round(ratio, 3)},
        "views": views,
    }

    print("--- liveness (mean |diff|, 160x90 gray) ---")
    print(f"    samples : {result['liveness']['samples']}")
    print(f"    mean={result['liveness']['mean']}  "
          f"min={result['liveness']['min']}  max={result['liveness']['max']}")
    print("\n--- modal dim ---")
    print(f"    border={border:.1f}  centre={centre:.1f}  ratio={ratio:.3f}")
    print("\n--- view discriminators ---")
    for name, conf in views.items():
        print(f"    {name:30s} {'MISSING' if conf is None else f'{conf:.3f}'}")

    sc.close()
    return result


def append_result(result: dict):
    history = []
    if OUT_FILE.exists():
        try:
            history = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        except Exception:
            history = []
    history.append(result)
    OUT_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")
    print(f"\nappended to {OUT_FILE}")


def summary():
    if not OUT_FILE.exists():
        sys.exit(f"no measurements yet at {OUT_FILE}")
    history = json.loads(OUT_FILE.read_text(encoding="utf-8"))
    print(f"{'label':10s} {'live.mean':>10s} {'live.min':>9s} {'dim.ratio':>10s}  window")
    for r in history:
        print(f"{r['label']:10s} {r['liveness']['mean']:10.3f} "
              f"{r['liveness']['min']:9.3f} {r['dim']['ratio']:10.3f}  {r['window']}")

    by_label = {}
    for r in history:
        by_label.setdefault(r["label"], []).append(r)
    print("\nSuggested gates (only meaningful once every state has been measured):")
    live_all = [r["liveness"]["min"] for r in history if r["label"] != "frozen"]
    frozen = [r["liveness"]["max"] for r in history if r["label"] == "frozen"]
    if live_all and frozen:
        print(f"  LIVENESS_MIN_DIFF between {max(frozen):.3f} (frozen) and "
              f"{min(live_all):.3f} (live)")
    elif live_all:
        print(f"  live views bottom out at {min(live_all):.3f}; "
              f"measure a frozen client (--label frozen) for the other side")
    clean = [r["dim"]["ratio"] for r in history if r["label"] in ("city", "world")]
    panel = [r["dim"]["ratio"] for r in history if r["label"] == "panel"]
    if clean and panel:
        print(f"  MODAL_RATIO_MIN between {max(clean):.3f} (clean) and "
              f"{min(panel):.3f} (panel)")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", default="unlabelled",
                        help="what is on screen: city | world | panel | frozen")
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--gap", type=float, default=0.5,
                        help="seconds between frames")
    parser.add_argument("--summary", action="store_true",
                        help="print all past measurements and suggested gates")
    args = parser.parse_args()

    if args.summary:
        summary()
        return
    append_result(measure(args.label, args.samples, args.gap))


if __name__ == "__main__":
    main()
