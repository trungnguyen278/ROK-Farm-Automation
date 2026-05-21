"""Record real mouse movements to train MouseHumanizer.

Usage:
    .venv\\Scripts\\python -m tools.record_mouse              # record until Ctrl+C
    .venv\\Scripts\\python -m tools.record_mouse --dur 60      # record 60 seconds
    .venv\\Scripts\\python -m tools.record_mouse --analyze     # analyze saved data

Move your mouse naturally inside the game window.
Press Ctrl+C to stop recording. Data is saved to data/mouse_recordings/.
"""

import argparse
import json
import math
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import win32api
import win32gui

DATA_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "data" / "mouse_recordings"
SAMPLE_HZ = 120


def get_cursor():
    return win32api.GetCursorPos()


def find_game_window(title="Rise of Kingdoms"):
    result = {}

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if title.lower() in t.lower():
                r = win32gui.GetWindowRect(hwnd)
                result["left"] = r[0]
                result["top"] = r[1]
                result["right"] = r[2]
                result["bottom"] = r[3]

    win32gui.EnumWindows(cb, None)
    return result if result else None


def record(duration=None):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    win = find_game_window()
    if win:
        print(f"  Game window: ({win['left']},{win['top']}) - ({win['right']},{win['bottom']})")
    else:
        print("  Game window not found, recording all mouse movement")

    print(f"  Sample rate: {SAMPLE_HZ} Hz")
    if duration:
        print(f"  Duration: {duration}s")
    print("  Move your mouse naturally. Press Ctrl+C to stop.\n")

    strokes = []
    current_stroke = []
    last_x, last_y = get_cursor()
    last_t = time.perf_counter()
    idle_start = last_t
    stopped = False
    total_points = 0

    def on_stop(sig, frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGINT, on_stop)

    start_time = time.perf_counter()
    interval = 1.0 / SAMPLE_HZ

    while not stopped:
        now = time.perf_counter()
        if duration and (now - start_time) >= duration:
            break

        x, y = get_cursor()
        dx = x - last_x
        dy = y - last_y
        dist = math.hypot(dx, dy)
        dt = now - last_t

        if dist >= 1:
            if now - idle_start > 0.15 and current_stroke:
                strokes.append(current_stroke)
                current_stroke = []
            current_stroke.append({
                "x": x, "y": y,
                "t": round(now - start_time, 5),
                "dt": round(dt, 5),
            })
            total_points += 1
            idle_start = now
            last_x, last_y = x, y
        elif current_stroke and (now - idle_start) > 0.3:
            strokes.append(current_stroke)
            current_stroke = []

        last_t = now

        elapsed = time.perf_counter() - now
        sleep_t = interval - elapsed
        if sleep_t > 0:
            time.sleep(sleep_t)

        if total_points % 500 == 0 and total_points > 0:
            sys.stdout.write(f"\r  {total_points} points, {len(strokes)} strokes, "
                             f"{now - start_time:.0f}s elapsed")
            sys.stdout.flush()

    if current_stroke:
        strokes.append(current_stroke)

    print(f"\n\n  Done: {total_points} points, {len(strokes)} strokes")

    if not strokes:
        print("  No data recorded")
        return None

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = DATA_DIR / f"mouse_{ts}.json"

    meta = {
        "timestamp": ts,
        "duration_s": round(time.perf_counter() - start_time, 1),
        "sample_hz": SAMPLE_HZ,
        "total_points": total_points,
        "total_strokes": len(strokes),
        "game_window": win,
    }
    with open(fname, "w") as f:
        json.dump({"meta": meta, "strokes": strokes}, f)

    print(f"  Saved: {fname}")
    analyze_file(fname)
    return fname


def analyze_file(path):
    with open(path) as f:
        data = json.load(f)

    strokes = data["strokes"]
    meta = data.get("meta", {})
    print(f"\n  === Analysis: {Path(path).name} ===")
    print(f"  Strokes: {len(strokes)}, Points: {meta.get('total_points', '?')}")

    speeds = []
    accels = []
    curvatures = []
    distances = []
    durations = []

    for stroke in strokes:
        if len(stroke) < 3:
            continue

        pts = [(p["x"], p["y"], p["t"]) for p in stroke]
        dx_total = pts[-1][0] - pts[0][0]
        dy_total = pts[-1][1] - pts[0][1]
        dist = math.hypot(dx_total, dy_total)
        dur = pts[-1][2] - pts[0][2]
        if dur <= 0:
            continue

        distances.append(dist)
        durations.append(dur)

        stroke_speeds = []
        stroke_accels = []
        for i in range(1, len(pts)):
            d = math.hypot(pts[i][0] - pts[i-1][0], pts[i][1] - pts[i-1][1])
            dt = pts[i][2] - pts[i-1][2]
            if dt > 0:
                spd = d / dt
                stroke_speeds.append(spd)
                if len(stroke_speeds) >= 2:
                    stroke_accels.append(abs(stroke_speeds[-1] - stroke_speeds[-2]) / dt)

        speeds.extend(stroke_speeds)
        accels.extend(stroke_accels)

        for i in range(1, len(pts) - 1):
            v1x = pts[i][0] - pts[i-1][0]
            v1y = pts[i][1] - pts[i-1][1]
            v2x = pts[i+1][0] - pts[i][0]
            v2y = pts[i+1][1] - pts[i][1]
            cross = abs(v1x * v2y - v1y * v2x)
            mag = math.hypot(v1x, v1y) * math.hypot(v2x, v2y)
            if mag > 0:
                curvatures.append(cross / mag)

    if not speeds:
        print("  Not enough data for analysis")
        return

    speeds = np.array(speeds)
    distances = np.array(distances)
    durations = np.array(durations)

    print(f"\n  Speed (px/s):")
    print(f"    mean={speeds.mean():.0f}  std={speeds.std():.0f}  "
          f"median={np.median(speeds):.0f}  p95={np.percentile(speeds, 95):.0f}")

    print(f"  Stroke distance (px):")
    print(f"    mean={distances.mean():.0f}  std={distances.std():.0f}  "
          f"median={np.median(distances):.0f}")

    print(f"  Stroke duration (ms):")
    durs_ms = durations * 1000
    print(f"    mean={durs_ms.mean():.0f}  std={durs_ms.std():.0f}  "
          f"median={np.median(durs_ms):.0f}")

    if curvatures:
        curv = np.array(curvatures)
        print(f"  Curvature:")
        print(f"    mean={curv.mean():.4f}  std={curv.std():.4f}  "
              f"median={np.median(curv):.4f}")

    if accels:
        acc = np.array(accels)
        print(f"  Acceleration (px/s2):")
        print(f"    mean={acc.mean():.0f}  std={acc.std():.0f}")

    avg_speed_pxs = speeds.mean()
    speed_std = speeds.std()
    avg_curve = np.array(curvatures).mean() if curvatures else 0.05

    print(f"\n  === Suggested profile params ===")
    print(f"  speed_base: {int(avg_speed_pxs)}")
    print(f"  speed_variance: {int(speed_std * 0.3)}")
    print(f"  curve_spread: {min(0.5, max(0.02, avg_curve * 2)):.3f}")
    if distances.mean() > 100:
        overshoot = max(0.02, min(0.15, 1.0 - np.median(distances) / distances.mean()))
    else:
        overshoot = 0.04
    print(f"  overshoot_chance: {overshoot:.3f}")
    print(f"  jitter_px: {max(0, int(speeds.std() * 0.003))}")


def analyze_all():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(DATA_DIR.glob("mouse_*.json"))
    if not files:
        print("  No recordings found in", DATA_DIR)
        return

    print(f"  Found {len(files)} recording(s)\n")
    for f in files:
        analyze_file(f)
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record mouse movements for humanizer training")
    parser.add_argument("--dur", type=int, default=None, help="Recording duration in seconds")
    parser.add_argument("--analyze", action="store_true", help="Analyze saved recordings")
    args = parser.parse_args()

    if args.analyze:
        analyze_all()
    else:
        record(args.dur)
