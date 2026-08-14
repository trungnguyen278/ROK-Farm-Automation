"""Visualize mouse path generators side-by-side.

Usage:
    .venv\\Scripts\\python tools/test_mouse_paths.py
    .venv\\Scripts\\python tools/test_mouse_paths.py --save   # save to screenshots/
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import argparse
import random
import numpy as np

from anti_detection.mouse_humanizer import MouseHumanizer


def _make_humanizer(**overrides):
    profile = {
        "mouse": {
            "windmouse": {"gravity": 9.0, "wind": 3.0, "max_velocity": 15.0, "target_distance": 12.0},
            "generator_weights": {"windmouse": 0.0, "bezier": 0.0, "replay": 0.0},
            "mid_pause": {"chance": 0.0, "min_distance": 9999, "duration_ms": [0, 0]},
            "overshoot_chance": 0.0,
            "micro_correction_chance": 0.0,
            "jitter_px": 1,
        }
    }
    profile["mouse"].update(overrides)
    return MouseHumanizer(profile)


def draw_path(img, path, color, thickness=1, dot_radius=2):
    import cv2
    for i in range(len(path) - 1):
        x1, y1, _ = path[i]
        x2, y2, _ = path[i + 1]
        cv2.line(img, (x1, y1), (x2, y2), color, thickness, cv2.LINE_AA)
    for x, y, ms in path:
        cv2.circle(img, (x, y), dot_radius, color, -1)
    if path:
        cv2.circle(img, (path[0][0], path[0][1]), 5, (0, 255, 0), -1)
        cv2.circle(img, (path[-1][0], path[-1][1]), 5, (0, 0, 255), -1)


def draw_velocity_profile(img, path, color, y_offset, width, height):
    import cv2
    if len(path) < 3:
        return
    velocities = []
    for i in range(1, len(path)):
        dx = path[i][0] - path[i-1][0]
        dy = path[i][1] - path[i-1][1]
        dt = max(1, path[i][2])
        speed = (dx**2 + dy**2)**0.5 / dt * 1000
        velocities.append(speed)
    if not velocities:
        return
    max_v = max(velocities) if max(velocities) > 0 else 1
    pts = []
    for i, v in enumerate(velocities):
        x = int(i / len(velocities) * width)
        y = y_offset + height - int(v / max_v * height * 0.9)
        pts.append((x, y))
    for i in range(len(pts) - 1):
        cv2.line(img, pts[i], pts[i+1], color, 1, cv2.LINE_AA)
    cv2.rectangle(img, (0, y_offset), (width, y_offset + height), (80, 80, 80), 1)


def main():
    import cv2
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()

    W, H = 900, 700
    VEL_H = 120

    scenarios = [
        ("Short (80px)", 200, 350, 280, 350),
        ("Medium (300px)", 100, 350, 400, 250),
        ("Long (600px)", 50, 350, 650, 200),
        ("Diagonal (500px)", 100, 100, 600, 500),
    ]

    for name, x1, y1, x2, y2 in scenarios:
        img = np.zeros((H + VEL_H * 2 + 40, W, 3), dtype=np.uint8)
        img[:] = 30

        cv2.putText(img, f"Scenario: {name}  ({x1},{y1})->({x2},{y2})",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
        cv2.putText(img, "GREEN=Force(accel)  BLUE=Bezier  (5 runs each, start=green dot, end=red dot)",
                    (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)

        # Force / acceleration-driven paths
        wm_h = _make_humanizer(generator_weights={"windmouse": 1.0, "bezier": 0.0, "replay": 0.0})
        for i in range(args.runs):
            path = wm_h._force_move(x1, y1, x2, y2,
                                    (((x2-x1)**2+(y2-y1)**2)**0.5))
            shade = 180 + i * 15
            draw_path(img, path, (0, shade, 0), thickness=1)
            draw_velocity_profile(img, path, (0, shade, 0),
                                  H + 10, W, VEL_H)

        # Bezier paths
        bz_h = _make_humanizer(generator_weights={"windmouse": 0.0, "bezier": 1.0, "replay": 0.0})
        for i in range(args.runs):
            path = bz_h._bezier_move(x1, y1, x2, y2,
                                     (((x2-x1)**2+(y2-y1)**2)**0.5))
            shade = 180 + i * 15
            draw_path(img, path, (shade, 60, 0), thickness=1)
            draw_velocity_profile(img, path, (shade, 60, 0),
                                  H + VEL_H + 25, W, VEL_H)

        cv2.putText(img, "Velocity: Force (accel)", (10, H + 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 200, 0), 1)
        cv2.putText(img, "Velocity: Bezier", (10, H + VEL_H + 23),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 100, 0), 1)

        safe_name = name.replace(" ", "_").replace("(", "").replace(")", "")
        if args.save:
            os.makedirs("screenshots", exist_ok=True)
            out = f"screenshots/mouse_path_{safe_name}.png"
            cv2.imwrite(out, img)
            print(f"Saved: {out}")
        else:
            cv2.imshow(f"Mouse Paths: {name}", img)

    # --save runs headless (CI/automated check); skip the blocking window.
    if not args.save:
        print("\nPress any key to close windows...")
        cv2.waitKey(0)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
