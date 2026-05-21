"""Train mouse humanizer by recording real movements between target pairs.

Usage:
    .venv\\Scripts\\python -m tools.train_mouse                # 30 pairs, mixed distances
    .venv\\Scripts\\python -m tools.train_mouse --pairs 50      # 50 pairs
    .venv\\Scripts\\python -m tools.train_mouse --apply         # apply trained data to humanizer

A transparent overlay shows two dots (green=start, red=end).
Move your mouse from green to red naturally. Repeat for each pair.
Data is saved to data/mouse_training/.
"""

import argparse
import json
import math
import os
import random
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path

import numpy as np
import win32api
import win32gui

DATA_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "data" / "mouse_training"
SAMPLE_HZ = 200
DOT_RADIUS = 12
NEAR_THRESHOLD = 20


def get_cursor():
    return win32api.GetCursorPos()


def find_game_window(title="Rise of Kingdoms"):
    result = {}
    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if title.lower() in t.lower():
                r = win32gui.GetWindowRect(hwnd)
                result.update(left=r[0], top=r[1], width=r[2]-r[0], height=r[3]-r[1])
    win32gui.EnumWindows(cb, None)
    return result if result else None


def generate_pairs(win, count=30):
    """Generate target pairs with varied distances and angles."""
    cx = win["left"] + win["width"] // 2
    cy = win["top"] + win["height"] // 2
    margin_x = int(win["width"] * 0.1)
    margin_y = int(win["height"] * 0.15)
    x_lo = win["left"] + margin_x
    x_hi = win["left"] + win["width"] - margin_x
    y_lo = win["top"] + margin_y
    y_hi = win["top"] + win["height"] - margin_y

    dist_buckets = [
        (30, 80, count // 5),
        (80, 200, count // 4),
        (200, 400, count // 3),
        (400, 700, count // 5),
    ]
    remaining = count - sum(n for _, _, n in dist_buckets)
    if remaining > 0:
        dist_buckets.append((100, 500, remaining))

    pairs = []
    for d_lo, d_hi, n in dist_buckets:
        for _ in range(n):
            for _attempt in range(50):
                x1 = random.randint(x_lo, x_hi)
                y1 = random.randint(y_lo, y_hi)
                angle = random.uniform(0, 2 * math.pi)
                dist = random.uniform(d_lo, d_hi)
                x2 = int(x1 + dist * math.cos(angle))
                y2 = int(y1 + dist * math.sin(angle))
                if x_lo <= x2 <= x_hi and y_lo <= y2 <= y_hi:
                    pairs.append(((x1, y1), (x2, y2)))
                    break

    random.shuffle(pairs)
    return pairs


class TrainOverlay:
    def __init__(self, pairs, win_rect):
        self.pairs = pairs
        self.win_rect = win_rect
        self.current_idx = 0
        self.trajectories = []
        self.recording = False
        self.current_path = []
        self.done = False

        self.root = tk.Tk()
        self.root.title("Mouse Training")
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", "black")
        self.root.overrideredirect(True)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{sw}x{sh}+0+0")

        self.canvas = tk.Canvas(self.root, width=sw, height=sh,
                                bg="black", highlightthickness=0)
        self.canvas.pack()

        self.info_label = tk.Label(self.root, text="", font=("Consolas", 14),
                                   fg="white", bg="#222222", padx=10, pady=5)
        info_x = win_rect["left"] + win_rect["width"] // 2
        info_y = win_rect["top"] + 30
        self.info_label.place(x=info_x, y=info_y, anchor="n")

        self.recorder_thread = threading.Thread(target=self._record_loop, daemon=True)
        self.recorder_thread.start()

        self._draw_current_pair()
        self.root.bind("<Escape>", lambda e: self._finish())
        self.root.after(30, self._update)

    def _draw_current_pair(self):
        self.canvas.delete("dots")
        self.canvas.delete("trail")
        if self.current_idx >= len(self.pairs):
            self._finish()
            return

        (x1, y1), (x2, y2) = self.pairs[self.current_idx]
        dist = math.hypot(x2 - x1, y2 - y1)

        r = DOT_RADIUS
        self.canvas.create_oval(x1-r, y1-r, x1+r, y1+r,
                                fill="#00ff00", outline="white", width=2, tags="dots")
        self.canvas.create_oval(x2-r, y2-r, x2+r, y2+r,
                                fill="#ff3333", outline="white", width=2, tags="dots")
        self.canvas.create_text(x1, y1-r-12, text="A", fill="#00ff00",
                                font=("Consolas", 11, "bold"), tags="dots")
        self.canvas.create_text(x2, y2-r-12, text="B", fill="#ff3333",
                                font=("Consolas", 11, "bold"), tags="dots")

        self.info_label.config(
            text=f"  {self.current_idx+1}/{len(self.pairs)}  |  "
                 f"dist: {dist:.0f}px  |  Click+hold at A, drag to B, release  |  ESC = stop  ")

    def _record_loop(self):
        interval = 1.0 / SAMPLE_HZ
        mouse_was_down = False
        while not self.done:
            if self.current_idx >= len(self.pairs):
                break

            cx, cy = get_cursor()
            left_down = win32api.GetKeyState(0x01) < 0

            if not self.recording:
                if left_down and not mouse_was_down:
                    self.recording = True
                    self.current_path = [{"x": cx, "y": cy, "t": 0.0}]
                    self._rec_start = time.perf_counter()
            else:
                t = time.perf_counter() - self._rec_start
                self.current_path.append({"x": cx, "y": cy, "t": round(t, 5)})
                if not left_down:
                    self._save_trajectory()

            mouse_was_down = left_down
            time.sleep(interval)

    def _save_trajectory(self):
        if len(self.current_path) < 3:
            self.recording = False
            self.current_path = []
            return

        (x1, y1), (x2, y2) = self.pairs[self.current_idx]
        dist = math.hypot(x2 - x1, y2 - y1)
        angle = math.atan2(y2 - y1, x2 - x1)
        duration = self.current_path[-1]["t"]

        traj = {
            "start": [x1, y1],
            "end": [x2, y2],
            "distance": round(dist, 1),
            "angle": round(angle, 4),
            "duration": round(duration, 4),
            "points": len(self.current_path),
            "path": self.current_path,
        }
        self.trajectories.append(traj)
        self.recording = False
        self.current_path = []
        self.current_idx += 1
        self.root.after(0, self._draw_current_pair)

    def _update(self):
        if self.done:
            return
        if self.recording and self.current_path:
            self.canvas.delete("trail")
            pts = self.current_path
            if len(pts) >= 2:
                coords = []
                for p in pts[-60:]:
                    coords.extend([p["x"], p["y"]])
                if len(coords) >= 4:
                    self.canvas.create_line(*coords, fill="#44aaff", width=2,
                                           smooth=True, tags="trail")
        self.root.after(30, self._update)

    def _finish(self):
        self.done = True
        self.root.destroy()

    def run(self):
        self.root.mainloop()
        return self.trajectories


def save_training(trajectories):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = DATA_DIR / f"train_{ts}.json"

    meta = {
        "timestamp": ts,
        "total_trajectories": len(trajectories),
        "sample_hz": SAMPLE_HZ,
    }

    dist_stats = [t["distance"] for t in trajectories]
    if dist_stats:
        meta["dist_min"] = round(min(dist_stats), 1)
        meta["dist_max"] = round(max(dist_stats), 1)
        meta["dist_mean"] = round(sum(dist_stats) / len(dist_stats), 1)

    with open(fname, "w") as f:
        json.dump({"meta": meta, "trajectories": trajectories}, f)

    print(f"\n  Saved {len(trajectories)} trajectories to {fname}")
    return fname


def normalize_trajectory(traj):
    """Normalize a trajectory to unit distance along x-axis.

    Returns list of (nx, ny, t_norm) where:
    - nx, ny are in [0,1] range (x=0 is start, x=1 is end)
    - t_norm is [0,1] time
    """
    sx, sy = traj["start"]
    ex, ey = traj["end"]
    dist = traj["distance"]
    angle = math.atan2(ey - sy, ex - sx)
    dur = traj["duration"]

    if dist < 1 or dur <= 0:
        return []

    cos_a = math.cos(-angle)
    sin_a = math.sin(-angle)

    normalized = []
    for p in traj["path"]:
        dx = p["x"] - sx
        dy = p["y"] - sy
        rx = (dx * cos_a - dy * sin_a) / dist
        ry = (dx * sin_a + dy * cos_a) / dist
        t_norm = p["t"] / dur
        normalized.append((rx, ry, t_norm))

    return normalized


def build_trajectory_bank():
    """Load all training data and build a bank of normalized trajectories."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(DATA_DIR.glob("train_*.json"))
    if not files:
        return None

    bank = {"short": [], "medium": [], "long": [], "xlong": []}
    total = 0

    for f in files:
        with open(f) as fh:
            data = json.load(fh)
        for traj in data["trajectories"]:
            norm = normalize_trajectory(traj)
            if len(norm) < 3:
                continue
            d = traj["distance"]
            entry = {
                "norm_path": norm,
                "distance": d,
                "duration": traj["duration"],
                "speed": d / traj["duration"] if traj["duration"] > 0 else 0,
            }
            if d < 80:
                bank["short"].append(entry)
            elif d < 200:
                bank["medium"].append(entry)
            elif d < 400:
                bank["long"].append(entry)
            else:
                bank["xlong"].append(entry)
            total += 1

    if total == 0:
        return None

    bank_path = DATA_DIR / "trajectory_bank.npz"
    np.savez(bank_path,
             short=np.array(bank["short"], dtype=object),
             medium=np.array(bank["medium"], dtype=object),
             long=np.array(bank["long"], dtype=object),
             xlong=np.array(bank["xlong"], dtype=object))

    print(f"\n  === Trajectory Bank ===")
    print(f"  Total: {total} trajectories")
    for k, v in bank.items():
        if v:
            speeds = [e["speed"] for e in v]
            print(f"  {k:8s}: {len(v):3d} trajs, "
                  f"speed {min(speeds):.0f}-{max(speeds):.0f} px/s")

    json_bank_path = DATA_DIR / "trajectory_bank.json"
    with open(json_bank_path, "w") as f:
        json.dump(bank, f)
    print(f"  Saved: {json_bank_path}")

    return bank


def analyze_training():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(DATA_DIR.glob("train_*.json"))
    if not files:
        print("  No training data found")
        return

    all_trajs = []
    for f in files:
        with open(f) as fh:
            data = json.load(fh)
        all_trajs.extend(data["trajectories"])

    print(f"  Total: {len(all_trajs)} trajectories from {len(files)} session(s)")

    dists = np.array([t["distance"] for t in all_trajs])
    durs = np.array([t["duration"] for t in all_trajs])
    speeds = dists / np.maximum(durs, 0.001)

    print(f"\n  Distance (px): mean={dists.mean():.0f} std={dists.std():.0f} "
          f"min={dists.min():.0f} max={dists.max():.0f}")
    print(f"  Duration (ms): mean={durs.mean()*1000:.0f} std={durs.std()*1000:.0f}")
    print(f"  Speed (px/s):  mean={speeds.mean():.0f} std={speeds.std():.0f}")

    # Curvature analysis
    curvatures = []
    for traj in all_trajs:
        norm = normalize_trajectory(traj)
        if len(norm) < 5:
            continue
        max_dev = max(abs(p[1]) for p in norm)
        curvatures.append(max_dev)

    if curvatures:
        curv = np.array(curvatures)
        print(f"  Max lateral deviation (normalized): mean={curv.mean():.4f} "
              f"std={curv.std():.4f} median={np.median(curv):.4f}")

    bank = build_trajectory_bank()
    if bank:
        print("\n  Bank ready for MouseHumanizer integration")


def apply_to_humanizer():
    """Generate humanizer config from training data."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    bank_path = DATA_DIR / "trajectory_bank.json"
    if not bank_path.exists():
        print("  No trajectory bank. Run training first, then --analyze")
        return

    with open(bank_path) as f:
        bank = json.load(f)

    all_entries = []
    for entries in bank.values():
        all_entries.extend(entries)

    if not all_entries:
        print("  Empty bank")
        return

    speeds = [e["speed"] for e in all_entries]
    sp = np.array(speeds)

    curvatures = []
    for entries in bank.values():
        for e in entries:
            norm = e["norm_path"]
            if len(norm) >= 3:
                max_dev = max(abs(p[1]) for p in norm)
                curvatures.append(max_dev)

    curv = np.array(curvatures) if curvatures else np.array([0.05])

    params = {
        "speed_base": int(sp.mean()),
        "speed_variance": int(sp.std() * 0.5),
        "curve_spread": round(float(np.clip(curv.mean() * 3, 0.02, 0.5)), 3),
        "jitter_px": max(0, int(sp.std() * 0.002)),
    }

    print(f"\n  === Suggested profile params ===")
    for k, v in params.items():
        print(f"  {k}: {v}")

    print(f"\n  Trajectory bank: {len(all_entries)} trajectories")
    print(f"  To enable replay mode, set in profile:")
    print(f'    "mouse": {{ "trajectory_bank": "data/mouse_training/trajectory_bank.json", ... }}')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train mouse humanizer with target pairs")
    parser.add_argument("--pairs", type=int, default=30, help="Number of target pairs")
    parser.add_argument("--analyze", action="store_true", help="Analyze training data")
    parser.add_argument("--apply", action="store_true", help="Generate humanizer params")
    args = parser.parse_args()

    if args.analyze:
        analyze_training()
    elif args.apply:
        apply_to_humanizer()
    else:
        win = find_game_window()
        if not win:
            print("  Game window not found. Open Rise of Kingdoms first.")
            sys.exit(1)

        print(f"  Game window: {win['width']}x{win['height']} at ({win['left']},{win['top']})")
        print(f"  Pairs: {args.pairs}")
        print(f"  Move mouse from GREEN dot (A) to RED dot (B)")
        print(f"  Move naturally! Trail shows your path.")
        print(f"  Press ESC to stop early.\n")

        pairs = generate_pairs(win, args.pairs)
        overlay = TrainOverlay(pairs, win)
        trajectories = overlay.run()

        if trajectories:
            save_training(trajectories)
            print(f"\n  Next steps:")
            print(f"    1. .venv\\Scripts\\python -m tools.train_mouse --analyze")
            print(f"    2. .venv\\Scripts\\python -m tools.train_mouse --apply")
        else:
            print("  No trajectories recorded")
