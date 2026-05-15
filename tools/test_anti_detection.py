"""
Phase 6 — Anti-Detection Verification Tool
Visualizes mouse paths (Bézier), timing distributions, and session behavior.
Run: python -m tools.test_anti_detection [--profile NAME] [--samples N]

Output:
  - Window 1: Mouse paths overlay (10 random moves)
  - Window 2: Timing distribution histogram
  - Window 3: Session timeline simulation
  - Console: statistical summary
"""
import sys
import os
import argparse
import random
import statistics
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np

from anti_detection.profile_loader import ProfileLoader
from anti_detection.mouse_humanizer import MouseHumanizer
from anti_detection.timing_engine import TimingEngine
from anti_detection.session_manager import SessionManager


def visualize_mouse_paths(humanizer: MouseHumanizer, num_paths: int = 10):
    canvas = np.zeros((800, 1200, 3), dtype=np.uint8)
    canvas[:] = (20, 20, 40)

    cv2.putText(canvas, "Mouse Path Visualization (Bezier + Jitter + Overshoot)",
                (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1)
    cv2.putText(canvas, f"{num_paths} random moves | Start=green | End=red | Overshoot=yellow",
                (20, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)

    colors = [
        (86, 180, 233), (230, 159, 0), (0, 158, 115), (240, 228, 66),
        (0, 114, 178), (213, 94, 0), (204, 121, 167), (255, 127, 80),
        (100, 149, 237), (144, 238, 144),
    ]

    for i in range(num_paths):
        x1 = random.randint(100, 1100)
        y1 = random.randint(100, 700)
        x2 = random.randint(100, 1100)
        y2 = random.randint(100, 700)

        path = humanizer.humanize_move(x1, y1, x2, y2)
        color = colors[i % len(colors)]

        cv2.circle(canvas, (x1, y1), 5, (0, 255, 0), -1)  # start
        cv2.circle(canvas, (x2, y2), 5, (0, 0, 255), -1)  # target

        points = [(x1, y1)]
        for px, py, _ in path:
            px = max(0, min(1199, px))
            py = max(0, min(799, py))
            points.append((px, py))

        for j in range(1, len(points)):
            cv2.line(canvas, points[j-1], points[j], color, 1, cv2.LINE_AA)

        if len(path) > 3:
            last = path[-1]
            cv2.circle(canvas, (max(0, min(1199, last[0])), max(0, min(799, last[1]))),
                       3, (0, 255, 255), -1)

    straight_label = "Gray dashed = straight line"
    cv2.putText(canvas, straight_label, (20, 780), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (100, 100, 100), 1)

    return canvas


def visualize_timing(timing: TimingEngine, num_samples: int = 500):
    canvas = np.zeros((600, 800, 3), dtype=np.uint8)
    canvas[:] = (20, 20, 40)

    delays = [timing.action_delay() * 1000 for _ in range(num_samples)]
    pauses = [timing.micro_pause() for _ in range(num_samples)]
    actual_pauses = [p * 1000 for p in pauses if p is not None]
    pause_rate = len(actual_pauses) / num_samples * 100

    cv2.putText(canvas, "Timing Distribution", (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1)

    hist_h = 200
    hist_y = 80
    _draw_histogram(canvas, delays, 40, hist_y, 720, hist_h,
                    "Action Delays (ms)", (86, 180, 233))

    avg_d = statistics.mean(delays)
    std_d = statistics.stdev(delays)
    cv2.putText(canvas, f"avg={avg_d:.0f}ms  std={std_d:.0f}ms  n={num_samples}",
                (40, hist_y + hist_h + 35), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)

    if actual_pauses:
        hist_y2 = 360
        _draw_histogram(canvas, actual_pauses, 40, hist_y2, 720, hist_h,
                        f"Micro Pauses (ms) — {pause_rate:.0f}% chance", (0, 158, 115))
        avg_p = statistics.mean(actual_pauses)
        cv2.putText(canvas, f"avg={avg_p:.0f}ms  n={len(actual_pauses)}/{num_samples}",
                    (40, hist_y2 + hist_h + 35), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)

    return canvas


def _draw_histogram(canvas, values, x, y, w, h, label, color, bins=30):
    cv2.putText(canvas, label, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

    cv2.rectangle(canvas, (x, y), (x + w, y + h), (50, 50, 70), 1)

    if not values:
        return

    lo, hi = min(values), max(values)
    if lo == hi:
        hi = lo + 1
    bin_width = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / bin_width), bins - 1)
        counts[idx] += 1

    max_count = max(counts)
    bar_w = w // bins

    for i, count in enumerate(counts):
        bar_h = int(count / max_count * (h - 20)) if max_count > 0 else 0
        bx = x + i * bar_w
        by = y + h - bar_h
        cv2.rectangle(canvas, (bx, by), (bx + bar_w - 1, y + h), color, -1)

    cv2.putText(canvas, f"{lo:.0f}", (x, y + h + 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (120, 120, 120), 1)
    cv2.putText(canvas, f"{hi:.0f}", (x + w - 40, y + h + 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (120, 120, 120), 1)


def visualize_session(session_mgr: SessionManager, sim_hours: float = 2.0):
    canvas = np.zeros((400, 1000, 3), dtype=np.uint8)
    canvas[:] = (20, 20, 40)

    cv2.putText(canvas, f"Session Simulation ({sim_hours:.0f}h)", (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1)

    stats = session_mgr.session_stats()
    farm_target = stats["current_farm_target_min"]
    daily_max = stats["daily_max_hours"]

    cv2.putText(canvas, f"Farm target: {farm_target:.0f}min | Daily max: {daily_max}h",
                (20, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)

    timeline_y = 100
    timeline_h = 40
    bar_x = 50
    bar_w = 900
    total_seconds = sim_hours * 3600

    cv2.rectangle(canvas, (bar_x, timeline_y), (bar_x + bar_w, timeline_y + timeline_h),
                  (50, 50, 70), 1)

    farm_periods = []
    break_periods = []
    t = 0.0
    farming = True
    while t < total_seconds:
        if farming:
            duration = max(60, random.gauss(farm_target * 60, 8 * 60))
            end = min(t + duration, total_seconds)
            farm_periods.append((t, end))
            t = end
            farming = False
        else:
            duration = max(60, random.gauss(8 * 60, 3 * 60))
            end = min(t + duration, total_seconds)
            break_periods.append((t, end))
            t = end
            farming = True

    for start, end in farm_periods:
        x1 = bar_x + int(start / total_seconds * bar_w)
        x2 = bar_x + int(end / total_seconds * bar_w)
        cv2.rectangle(canvas, (x1, timeline_y), (x2, timeline_y + timeline_h),
                      (0, 158, 115), -1)

    for start, end in break_periods:
        x1 = bar_x + int(start / total_seconds * bar_w)
        x2 = bar_x + int(end / total_seconds * bar_w)
        cv2.rectangle(canvas, (x1, timeline_y), (x2, timeline_y + timeline_h),
                      (40, 60, 120), -1)

    cv2.putText(canvas, "0min", (bar_x, timeline_y + timeline_h + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 120), 1)
    cv2.putText(canvas, f"{sim_hours * 60:.0f}min",
                (bar_x + bar_w - 50, timeline_y + timeline_h + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 120), 1)

    legend_y = 180
    cv2.rectangle(canvas, (50, legend_y), (70, legend_y + 15), (0, 158, 115), -1)
    cv2.putText(canvas, "Farming", (80, legend_y + 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    cv2.rectangle(canvas, (200, legend_y), (220, legend_y + 15), (40, 60, 120), -1)
    cv2.putText(canvas, "Break", (230, legend_y + 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

    total_farm = sum(e - s for s, e in farm_periods)
    total_break = sum(e - s for s, e in break_periods)
    farm_pct = total_farm / total_seconds * 100 if total_seconds > 0 else 0

    info_y = 220
    cv2.putText(canvas, f"Farm sessions: {len(farm_periods)}  |  Breaks: {len(break_periods)}",
                (50, info_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)
    cv2.putText(canvas, f"Farm time: {total_farm/60:.0f}min ({farm_pct:.0f}%)  |  "
                f"Break time: {total_break/60:.0f}min",
                (50, info_y + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)

    fatigue_y = 280
    cv2.putText(canvas, "Fatigue Multiplier Over Time:", (50, fatigue_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

    from anti_detection.timing_engine import TimingEngine as _TE
    graph_x = 50
    graph_y = fatigue_y + 20
    graph_w = 900
    graph_h = 80

    cv2.rectangle(canvas, (graph_x, graph_y), (graph_x + graph_w, graph_y + graph_h),
                  (50, 50, 70), 1)

    prev_pt = None
    for i in range(graph_w):
        minutes = (i / graph_w) * sim_hours * 60
        fatigue = 1.0 + 0.5 * min(minutes / 60.0, 1.0)
        norm_y = int((fatigue - 1.0) / 0.5 * graph_h)
        pt = (graph_x + i, graph_y + graph_h - norm_y)
        if prev_pt:
            cv2.line(canvas, prev_pt, pt, (230, 159, 0), 1, cv2.LINE_AA)
        prev_pt = pt

    cv2.putText(canvas, "1.0x", (graph_x - 35, graph_y + graph_h),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (120, 120, 120), 1)
    cv2.putText(canvas, "1.5x", (graph_x - 35, graph_y + 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (120, 120, 120), 1)

    return canvas


def print_stats(humanizer, timing, session_mgr, profile, num_samples=200):
    print("\n  === Anti-Detection Statistics ===")
    print(f"  Profile: {profile.get('name', 'unknown')}")

    mouse = profile.get("mouse", {})
    print(f"\n  Mouse Config:")
    print(f"    Bézier control points: {mouse.get('bezier_control_points', 3)}")
    print(f"    Speed base: {mouse.get('speed_base', 400)}px/s ± {mouse.get('speed_variance', 150)}")
    print(f"    Overshoot: {mouse.get('overshoot_chance', 0.15)*100:.0f}% chance, "
          f"{mouse.get('overshoot_distance', [5,15])}px")
    print(f"    Misclick: {mouse.get('misclick_chance', 0.01)*100:.1f}% chance")
    print(f"    Click spread: {mouse.get('click_spread', 8)}px")
    print(f"    Hold time: {mouse.get('hold_ms', [50,150])}ms")

    path_lengths = []
    overshoot_count = 0
    for _ in range(num_samples):
        x1, y1 = random.randint(0, 1000), random.randint(0, 700)
        x2, y2 = random.randint(0, 1000), random.randint(0, 700)
        path = humanizer.humanize_move(x1, y1, x2, y2)
        path_lengths.append(len(path))
        if humanizer.should_overshoot():
            overshoot_count += 1

    print(f"\n  Path Stats ({num_samples} samples):")
    print(f"    Avg steps/move: {statistics.mean(path_lengths):.1f}")
    print(f"    Overshoot rate: {overshoot_count/num_samples*100:.1f}%")

    delays = [timing.action_delay() * 1000 for _ in range(num_samples)]
    pauses = [timing.micro_pause() for _ in range(num_samples)]
    actual_pauses = [p * 1000 for p in pauses if p is not None]

    print(f"\n  Timing Stats ({num_samples} samples):")
    print(f"    Action delay: {statistics.mean(delays):.0f}ms ± {statistics.stdev(delays):.0f}ms "
          f"[{min(delays):.0f}-{max(delays):.0f}]")
    print(f"    Micro pause rate: {len(actual_pauses)/num_samples*100:.0f}%")
    if actual_pauses:
        print(f"    Micro pause duration: {statistics.mean(actual_pauses):.0f}ms "
              f"[{min(actual_pauses):.0f}-{max(actual_pauses):.0f}]")

    fatigue_samples = [timing.apply_fatigue(m) for m in range(0, 61, 10)]
    print(f"\n  Fatigue multiplier: ", end="")
    for i, m in enumerate(range(0, 61, 10)):
        print(f"{m}min={fatigue_samples[i]:.2f}x", end="  ")
    print()

    ss = session_mgr.session_stats()
    print(f"\n  Session Config:")
    print(f"    Farm target: {ss['current_farm_target_min']:.0f}min")
    print(f"    Daily max: {ss['daily_max_hours']}h")


def main():
    parser = argparse.ArgumentParser(description="Anti-Detection Verification")
    parser.add_argument("--profile", default="default", help="Profile name")
    parser.add_argument("--samples", type=int, default=200, help="Number of stat samples")
    parser.add_argument("--no-gui", action="store_true", help="Skip OpenCV windows")
    args = parser.parse_args()

    print("=" * 60)
    print("  Anti-Detection Verification — Phase 6")
    print("=" * 60)

    loader = ProfileLoader("profiles")
    profile = loader.load(args.profile)
    print(f"  Profile loaded: {profile.get('name', args.profile)}")

    humanizer = MouseHumanizer(profile)
    timing = TimingEngine(profile)
    session = SessionManager(profile)

    print_stats(humanizer, timing, session, profile, args.samples)

    if not args.no_gui:
        print("\n  Generating visualizations... (press any key to close each window)")

        path_canvas = visualize_mouse_paths(humanizer, 10)
        cv2.imshow("Mouse Paths", path_canvas)

        timing_canvas = visualize_timing(timing, args.samples)
        cv2.imshow("Timing Distribution", timing_canvas)

        session_canvas = visualize_session(session, 2.0)
        cv2.imshow("Session Timeline", session_canvas)

        print("  Windows open. Press 'q' or ESC to close all.")
        while True:
            key = cv2.waitKey(100) & 0xFF
            if key in (ord('q'), 27):
                break
            if cv2.getWindowProperty("Mouse Paths", cv2.WND_PROP_VISIBLE) < 1:
                break

        cv2.destroyAllWindows()

    print("\n  Done.")


if __name__ == "__main__":
    main()
