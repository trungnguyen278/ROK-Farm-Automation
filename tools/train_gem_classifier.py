"""
Gem Classifier Training Tool -- Visual UI labeling

Captures the world map at icon-zoom level, finds all resource icon candidates,
and displays them in a tkinter grid. You label each patch: Gem or Not.

Run: .venv\\Scripts\\python -m tools.train_gem_classifier --port COM27
"""

import sys
import os
import time
import logging
import argparse
import random
import threading
from pathlib import Path
from datetime import datetime
from typing import Callable

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capture.screen_capture import ScreenCapture
from capture.screen_info import screen_to_hid
from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher, Match
from vision.color_filter import is_gem_icon_color
from vision.gem_classifier import GemPatchClassifier

OUTPUT_DIR = Path("data/training_sessions")
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            LOG_DIR / f"train_classifier_{datetime.now():%Y%m%d_%H%M%S}.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("train_classifier")

GEM_ICON_THRESHOLD = 0.69
GEM_ICON_REJECT_FLOOR = 0.60
ICON_ZOOM_SCROLLS = 2
SAFE_ZONE_MARGIN = 0.08
DARK_TERRAIN_THRESH = 70
PATCH_DISPLAY_SIZE = 80


class TrainerBackend:
    """Handles ESP32 + screen capture + scanning (non-UI thread)."""

    def __init__(self, port: str, skip_filters: bool = False):
        self.port = port
        self.skip_filters = skip_filters
        self.sc: ScreenCapture | None = None
        self.cache: TemplateCache | None = None
        self.matcher: TemplateMatcher | None = None
        self.conn = None
        self.cmd = None
        self.win: dict | None = None
        self.classifier = GemPatchClassifier()
        self.classifier.load()

        self.session_dir: Path | None = None
        self.stats = {"gem": 0, "not_gem": 0}
        self.labeled_positions: list[tuple[int, int]] = []
        self._sample_idx = 0

    def init_vision(self) -> tuple[bool, str]:
        """Init screen capture + vision (call from main thread)."""
        self.sc = ScreenCapture()
        self.win = self.sc.find_window()
        if not self.win:
            return False, "Game window not found"

        self.cache = TemplateCache("templates")
        self.matcher = TemplateMatcher(self.cache, threshold=0.50)
        return True, f"Window: {self.win['width']}x{self.win['height']}"

    def connect_esp32(self) -> tuple[bool, str]:
        """Connect ESP32 (can run from any thread)."""
        from serial_comm.connection import SerialConnection
        from serial_comm.command_buffer import CommandBuffer

        self.conn = SerialConnection(port=self.port)
        if not self.conn.connect():
            return False, f"ESP32 connect failed on {self.port}"
        self.cmd = CommandBuffer(self.conn)
        self.cmd.start()
        time.sleep(0.3)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = OUTPUT_DIR / ts
        self.session_dir.mkdir(parents=True, exist_ok=True)
        (self.session_dir / "gem").mkdir(exist_ok=True)
        (self.session_dir / "not_gem").mkdir(exist_ok=True)

        return True, f"ESP32: {self.port}"

    def teardown(self):
        if self.classifier.sample_count > 0:
            self.classifier.save()
        if self.cmd:
            self.cmd.send("RESET")
            self.cmd.stop()
        if self.conn:
            self.conn.disconnect()
        if self.sc:
            self.sc.close()

    def navigate_to_icon_zoom(self) -> str:
        """From any state, get to world map at icon-zoom level.

        Returns status message.
        """
        frame = self.sc.grab_full()
        if frame is None:
            return "FAIL: cannot capture screen"

        # Check if already on world map (city_btn visible = on world map)
        city_btn = self._find_on_frame(frame, "buttons/city_btn", threshold=0.70)
        if city_btn:
            # Already on world map, just zoom out to icon level
            logger.info("Already on world map, zooming out to icon level")
            cx, cy = self._center_screen()
            self._click(cx, cy)
            time.sleep(0.3)
            self._scroll_at_center(-5, ICON_ZOOM_SCROLLS)
            time.sleep(1.0)
            return "OK: world map -> zoomed out"

        # Not on world map -- try clicking world_map_city_btn (city view bottom-right)
        m = self._find_on_frame(frame, "buttons/world_map_city_btn", threshold=0.65)
        if m:
            logger.info("Found world_map_city_btn, clicking to enter world map")
            sx, sy = self._screen_xy(*m.center)
            self._click(sx, sy)
            time.sleep(2.5)
        else:
            # Fallback: click bottom-right area where the button usually is
            logger.info("world_map_city_btn not found, clicking bottom-right fallback")
            br_x = self.win["left"] + int(self.win["width"] * 0.95)
            br_y = self.win["top"] + int(self.win["height"] * 0.93)
            self._click(br_x, br_y)
            time.sleep(2.5)

        # Verify we arrived on world map
        frame = self.sc.grab_full()
        if frame is not None:
            city_btn = self._find_on_frame(frame, "buttons/city_btn", threshold=0.70)
            if not city_btn:
                return "WARN: may not be on world map, zooming out anyway"

        # Zoom out to icon level
        cx, cy = self._center_screen()
        self._click(cx, cy)
        time.sleep(0.3)
        self._scroll_at_center(-5, ICON_ZOOM_SCROLLS)
        time.sleep(1.0)
        return "OK: city view -> world map -> zoomed out"

    def reset_to_city(self) -> str:
        """Return to city view from anywhere."""
        frame = self.sc.grab_full()
        if frame is None:
            return "FAIL: cannot capture screen"

        # If city_btn visible, click it to go back to city
        city_btn = self._find_on_frame(frame, "buttons/city_btn", threshold=0.70)
        if city_btn:
            logger.info("Clicking city_btn to return to city view")
            sx, sy = self._screen_xy(*city_btn.center)
            self._click(sx, sy)
            time.sleep(2.0)
            return "OK: returned to city view"

        # Maybe already in city view (world_map_city_btn visible)
        m = self._find_on_frame(frame, "buttons/world_map_city_btn", threshold=0.65)
        if m:
            return "OK: already in city view"

        # Try pressing ESC to close any popup/panel
        self.cmd.send("KEY", 27)
        time.sleep(1.0)

        frame = self.sc.grab_full()
        if frame is not None:
            city_btn = self._find_on_frame(frame, "buttons/city_btn", threshold=0.70)
            if city_btn:
                sx, sy = self._screen_xy(*city_btn.center)
                self._click(sx, sy)
                time.sleep(2.0)
                return "OK: ESC -> city_btn -> city view"

            m = self._find_on_frame(frame, "buttons/world_map_city_btn", threshold=0.65)
            if m:
                return "OK: ESC -> already in city view"

        return "WARN: could not confirm city view"

    def scan_current_frame(self) -> tuple[np.ndarray | None, list[dict], list[dict]]:
        """Capture frame and find all icon candidates.

        Returns (frame, accepted_list, rejected_list).
        Each item is {"match": Match, "patch": ndarray, "reason": str}.
        """
        frame = self.sc.grab_full()
        if frame is None:
            return None, [], []

        accepted, rejected = self._find_all_candidates(frame)
        for item in accepted:
            item["patch"] = self._extract_icon_patch(frame, item["match"])
        for item in rejected:
            item["patch"] = self._extract_icon_patch(frame, item["match"])
        return frame, accepted, rejected

    def extract_patch_at(self, frame: np.ndarray, x: int, y: int) -> np.ndarray:
        """Extract a patch at arbitrary frame coordinates (for manual marking)."""
        tpl = self.cache.get("resources/gem_icon")
        if tpl is not None:
            h, w = tpl.shape[:2]
        else:
            h, w = 48, 48
        fh, fw = frame.shape[:2]
        x1 = max(0, x - w // 2)
        y1 = max(0, y - h // 2)
        x2 = min(fw, x1 + w)
        y2 = min(fh, y1 + h)
        return frame[y1:y2, x1:x2].copy()

    def drag_to_new_area(self):
        cx, cy = self._center_screen()
        ww = self.win["width"]
        wh = self.win["height"]
        margin = 80
        angle = random.choice([(1, 0), (-1, 0), (0, 1), (0, -1),
                               (1, 1), (-1, -1), (1, -1), (-1, 1)])
        dp = random.uniform(0.7, 1.0)
        sx = cx + int(angle[0] * (ww // 2 - margin) * dp)
        sy = cy + int(angle[1] * (wh // 2 - margin) * dp)
        ex = cx - int(angle[0] * (ww // 2 - margin) * dp)
        ey = cy - int(angle[1] * (wh // 2 - margin) * dp)
        sx, sy = self._clamp(sx, sy)
        ex, ey = self._clamp(ex, ey)
        hx1, hy1 = screen_to_hid(sx, sy)
        hx2, hy2 = screen_to_hid(ex, ey)
        self.cmd.send("MOVETO", hx1, hy1)
        time.sleep(0.1)
        self.cmd.send("DRAG", 0, 0, hx2 - hx1, hy2 - hy1, random.randint(400, 600), timeout=3.0)
        time.sleep(2.0)

    def label_patch(self, patch: np.ndarray, label: str):
        """Save labeled patch to classifier + disk."""
        idx = self._sample_idx
        self._sample_idx += 1

        if label == "gem":
            self.classifier.add_sample(patch, True)
            self.stats["gem"] += 1
            cv2.imwrite(str(self.session_dir / "gem" / f"{idx:04d}.png"), patch)

        elif label == "not_gem":
            self.classifier.add_sample(patch, False)
            self.stats["not_gem"] += 1
            cv2.imwrite(str(self.session_dir / "not_gem" / f"{idx:04d}.png"), patch)

    # --- Internal helpers ---

    def _screen_xy(self, frame_x: int, frame_y: int) -> tuple[int, int]:
        return frame_x + self.win["left"], frame_y + self.win["top"]

    def _center_screen(self) -> tuple[int, int]:
        return (self.win["left"] + self.win["width"] // 2,
                self.win["top"] + self.win["height"] // 2)

    def _clamp(self, sx: int, sy: int, pad: int = 40) -> tuple[int, int]:
        x = max(self.win["left"] + pad, min(self.win["left"] + self.win["width"] - pad, sx))
        y = max(self.win["top"] + pad, min(self.win["top"] + self.win["height"] - pad, sy))
        return x, y

    def _moveto(self, sx: int, sy: int) -> bool:
        sx, sy = self._clamp(sx, sy, pad=5)
        hx, hy = screen_to_hid(sx, sy)
        return self.cmd.send("MOVETO", hx, hy)

    def _click(self, sx: int, sy: int) -> bool:
        if not self._moveto(sx, sy):
            return False
        time.sleep(random.uniform(0.05, 0.12))
        return self.cmd.send("CLICK", "L", random.randint(60, 100))

    def _scroll_at_center(self, amount: int, count: int = 1):
        cx, cy = self._center_screen()
        self._moveto(cx, cy)
        time.sleep(0.1)
        for _ in range(count):
            self.cmd.send("SCROLL", amount)
            time.sleep(0.15)

    def _find_on_frame(self, frame, template: str, threshold: float = 0.60) -> Match | None:
        m = self.matcher.match_single(frame, template)
        if m and m.confidence >= threshold:
            return m
        return None

    def _extract_icon_patch(self, frame, m: Match) -> np.ndarray:
        fh, fw = frame.shape[:2]
        x1 = max(0, m.x)
        y1 = max(0, m.y)
        x2 = min(fw, m.x + m.w)
        y2 = min(fh, m.y + m.h)
        return frame[y1:y2, x1:x2].copy()

    def _find_all_candidates(self, frame) -> tuple[list[dict], list[dict]]:
        matches = self.matcher.match_all(frame, "resources/gem_icon", overlap_thresh=0.3)
        accepted = []
        rejected = []
        for m in matches:
            if m.confidence < GEM_ICON_REJECT_FLOOR:
                continue

            if any(abs(m.center[0] - px) < 80 and abs(m.center[1] - py) < 80
                   for px, py in self.labeled_positions):
                continue

            if m.confidence < GEM_ICON_THRESHOLD:
                rejected.append({"match": m, "reason": f"low_conf({m.confidence:.2f})"})
                continue

            accepted.append({"match": m, "reason": "accepted"})

        accepted.sort(key=lambda x: -x["match"].confidence)
        rejected.sort(key=lambda x: -x["match"].confidence)
        return accepted, rejected

    def _is_clickable_zone(self, frame, m: Match) -> tuple[bool, str]:
        fh, fw = frame.shape[:2]
        cx, cy = m.center
        margin_x = int(fw * SAFE_ZONE_MARGIN)
        margin_y = int(fh * SAFE_ZONE_MARGIN)
        if cx < margin_x or cx > fw - margin_x or cy < margin_y or cy > fh - margin_y:
            return False, f"edge({cx},{cy})"
        pad = max(m.w, m.h) * 2
        y1 = max(0, cy - pad)
        y2 = min(fh, cy + pad)
        x1 = max(0, cx - pad)
        x2 = min(fw, cx + pad)
        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return False, "empty"
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        ir = max(m.w, m.h) // 2
        mask_arr = np.ones(gray.shape, dtype=bool)
        ly, lx = cy - y1, cx - x1
        mask_arr[max(0, ly - ir):min(gray.shape[0], ly + ir),
                 max(0, lx - ir):min(gray.shape[1], lx + ir)] = False
        terrain = gray[mask_arr]
        if terrain.size == 0:
            return False, "no_terrain"
        med = float(np.median(terrain))
        if med < DARK_TERRAIN_THRESH:
            return False, f"dark({med:.0f})"
        return True, f"ok({med:.0f})"


# ============================================================
# Tkinter UI
# ============================================================

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

BG = "#1a1a2e"
FG = "#e0e0e0"
BTN_BG = "#2a2a4e"
GEM_COLOR = "#44cc44"
NOT_GEM_COLOR = "#cc4444"


class PatchCard(tk.Frame):
    """Single icon patch with label buttons."""

    def __init__(self, parent, idx: int, patch_bgr: np.ndarray, match: Match,
                 color_info: dict, clf_label: str, clf_conf: float,
                 on_label: Callable[[int, str], None],
                 is_rejected: bool = False):
        bg_color = "#331a1a" if is_rejected else "#222244"
        super().__init__(parent, bg=bg_color, bd=1, relief="solid", padx=4, pady=4)
        self._idx = idx
        self._on_label = on_label
        self._labeled = False
        self._bg_color = bg_color

        # Convert patch to PhotoImage
        patch_rgb = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(patch_rgb).resize(
            (PATCH_DISPLAY_SIZE, PATCH_DISPLAY_SIZE), Image.NEAREST
        )
        self._photo = ImageTk.PhotoImage(img)

        # Image
        img_label = tk.Label(self, image=self._photo, bg=bg_color)
        img_label.pack(pady=2)

        # Info
        conf_text = f"conf={match.confidence:.2f}"
        color_reason = color_info.get("reason", "?")[:14]
        clf_text = f"{clf_label[:6]}({clf_conf:.1f})"

        info = tk.Label(self, text=f"{conf_text}\n{color_reason}\n{clf_text}",
                        font=("Consolas", 8), bg=bg_color, fg="#aaaaaa", justify="center")
        info.pack()

        # Buttons with tooltips
        btn_frame = tk.Frame(self, bg=bg_color)
        btn_frame.pack(pady=2)

        tk.Button(btn_frame, text="Gem", font=("Consolas", 9, "bold"), width=5,
                  bg="#225522", fg=GEM_COLOR, bd=0,
                  command=lambda: self._do_label("gem")).pack(side="left", padx=2)
        tk.Button(btn_frame, text="Not", font=("Consolas", 9, "bold"), width=5,
                  bg="#552222", fg=NOT_GEM_COLOR, bd=0,
                  command=lambda: self._do_label("not_gem")).pack(side="left", padx=2)

    def _do_label(self, label: str):
        if self._labeled:
            return
        self._labeled = True
        colors = {"gem": GEM_COLOR, "not_gem": NOT_GEM_COLOR}
        self.configure(bg=colors.get(label, self._bg_color), bd=2)
        self._on_label(self._idx, label)


FRAME_PREVIEW_HEIGHT = 180
REJECTED_BORDER = "#882222"


class TrainerUI(tk.Tk):
    def __init__(self, backend: TrainerBackend):
        super().__init__()
        self.title("Gem Classifier Trainer")
        self.configure(bg=BG)
        self.geometry("1200x800")
        self.minsize(900, 600)

        self._backend = backend
        self._current_accepted: list[dict] = []
        self._current_rejected: list[dict] = []
        self._current_frame: np.ndarray | None = None
        self._cards: list[PatchCard] = []
        self._rejected_cards: list[PatchCard] = []
        self._frame_photo = None
        self._frame_scale = 1.0

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._do_setup)

    def _build_ui(self):
        # Top bar
        top = tk.Frame(self, bg=BG, height=40)
        top.pack(fill="x", padx=10, pady=5)

        self._btn_scan = tk.Button(top, text="Scan", font=("Consolas", 10, "bold"),
                                   bg="#2a4a2a", fg="#44ff44", bd=0, padx=16, pady=4,
                                   command=self._on_scan)
        self._btn_scan.pack(side="left", padx=4)

        self._btn_drag = tk.Button(top, text="Drag", font=("Consolas", 10),
                                   bg=BTN_BG, fg=FG, bd=0, padx=12, pady=4,
                                   command=self._on_drag)
        self._btn_drag.pack(side="left", padx=4)

        self._btn_nav = tk.Button(top, text="Nav to Map", font=("Consolas", 10),
                                  bg=BTN_BG, fg=FG, bd=0, padx=12, pady=4,
                                  command=self._on_navigate)
        self._btn_nav.pack(side="left", padx=4)

        self._btn_reset = tk.Button(top, text="Reset", font=("Consolas", 10),
                                    bg="#4a2a2a", fg="#ff8888", bd=0, padx=12, pady=4,
                                    command=self._on_reset)
        self._btn_reset.pack(side="left", padx=4)

        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=8, pady=2)

        self._btn_all_gem = tk.Button(top, text="All Gem", font=("Consolas", 10),
                                      bg="#225522", fg=GEM_COLOR, bd=0, padx=12, pady=4,
                                      command=lambda: self._label_all("gem"))
        self._btn_all_gem.pack(side="left", padx=4)

        self._btn_all_not = tk.Button(top, text="All Not", font=("Consolas", 10),
                                      bg="#552222", fg=NOT_GEM_COLOR, bd=0, padx=12, pady=4,
                                      command=lambda: self._label_all("not_gem"))
        self._btn_all_not.pack(side="left", padx=4)

        self._show_rejected_var = tk.BooleanVar(value=True)
        tk.Checkbutton(top, text="Show Rejected", variable=self._show_rejected_var,
                       font=("Consolas", 9), bg=BG, fg=FG, selectcolor="#333355",
                       activebackground=BG, activeforeground=FG,
                       command=self._toggle_rejected).pack(side="left", padx=8)

        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=4, pady=2)

        self._btn_save = tk.Button(top, text="Save", font=("Consolas", 10, "bold"),
                                   bg="#2a2a6a", fg="#88aaff", bd=0, padx=16, pady=4,
                                   command=self._on_save)
        self._btn_save.pack(side="left", padx=4)

        # Stats
        self._stats_var = tk.StringVar(value="gem=0 | not=0")
        tk.Label(top, textvariable=self._stats_var, font=("Consolas", 10),
                 bg=BG, fg="#888888").pack(side="right", padx=10)

        # Status
        self._status_var = tk.StringVar(value="Initializing...")
        tk.Label(self, textvariable=self._status_var, font=("Consolas", 10),
                 bg=BG, fg="#aaaaaa", anchor="w").pack(fill="x", padx=10)

        # Legend
        legend_frame = tk.Frame(self, bg=BG)
        legend_frame.pack(fill="x", padx=10, pady=(2, 0))
        tk.Label(legend_frame, text="Labels:", font=("Consolas", 8, "bold"),
                 bg=BG, fg="#888888").pack(side="left")
        tk.Label(legend_frame, text="Gem = mo gem", font=("Consolas", 8),
                 bg=BG, fg=GEM_COLOR).pack(side="left", padx=6)
        tk.Label(legend_frame, text="Not = khong phai gem (da, go, thong bao...)", font=("Consolas", 8),
                 bg=BG, fg=NOT_GEM_COLOR).pack(side="left", padx=6)

        # Frame preview (clickable to mark missed gems)
        frame_container = tk.Frame(self, bg="#111122", height=FRAME_PREVIEW_HEIGHT)
        frame_container.pack(fill="x", padx=10, pady=(5, 0))
        frame_container.pack_propagate(False)

        self._frame_label = tk.Label(frame_container, bg="#111122",
                                     text="[Frame preview -- click vao vi tri gem ma he thong bo sot]",
                                     fg="#555555", font=("Consolas", 9))
        self._frame_label.pack(expand=True)
        self._frame_label.bind("<Button-1>", self._on_frame_click)

        hint = tk.Label(self, text="Click frame = danh dau gem bi miss | Xanh=accepted | Do=rejected | Vang=manual",
                        font=("Consolas", 8), bg=BG, fg="#555566", anchor="w")
        hint.pack(fill="x", padx=10)

        # Scrollable patch grid
        container = tk.Frame(self, bg=BG)
        container.pack(fill="both", expand=True, padx=10, pady=5)

        self._canvas = tk.Canvas(container, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self._canvas.yview)
        self._scroll_frame = tk.Frame(self._canvas, bg=BG)

        self._scroll_frame.bind("<Configure>",
                                lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.create_window((0, 0), window=self._scroll_frame, anchor="nw")
        self._canvas.configure(yscrollcommand=scrollbar.set)

        self._canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._canvas.bind_all("<MouseWheel>",
                              lambda e: self._canvas.yview_scroll(-1 * (e.delta // 120), "units"))

    def _do_setup(self):
        # Vision init on main thread (mss has thread affinity)
        ok, msg = self._backend.init_vision()
        if not ok:
            self._status_var.set(f"FAILED: {msg}")
            self._btn_scan.configure(state="disabled")
            return

        self._status_var.set(f"{msg} | Connecting ESP32...")

        # ESP32 connection in background
        def _worker():
            ok2, msg2 = self._backend.connect_esp32()
            self.after(0, self._on_setup_done, ok2, f"{msg} | {msg2}")
        threading.Thread(target=_worker, daemon=True).start()

    def _on_setup_done(self, ok: bool, msg: str):
        if ok:
            stats = self._backend.classifier.get_stats()
            self._status_var.set(
                f"Ready | {msg} | Classifier: {stats['total']} samples"
            )
        else:
            self._status_var.set(f"FAILED: {msg}")
            self._btn_scan.configure(state="disabled")

    def _on_navigate(self):
        self._status_var.set("Navigating to world map icon-zoom...")
        self._disable_buttons()

        def _worker():
            msg = self._backend.navigate_to_icon_zoom()
            self.after(0, self._enable_buttons)
            self.after(0, lambda: self._status_var.set(f"Nav done: {msg} -- click Scan"))
        threading.Thread(target=_worker, daemon=True).start()

    def _on_reset(self):
        self._status_var.set("Resetting to city view...")
        self._disable_buttons()

        def _worker():
            msg = self._backend.reset_to_city()
            self.after(0, self._enable_buttons)
            self.after(0, lambda: self._status_var.set(f"Reset: {msg}"))
        threading.Thread(target=_worker, daemon=True).start()

    def _on_drag(self):
        self._status_var.set("Dragging to new area...")
        self._disable_buttons()

        def _worker():
            self._backend.drag_to_new_area()
            self.after(0, self._enable_buttons)
            self.after(0, lambda: self._status_var.set("Dragged -- click Scan"))
        threading.Thread(target=_worker, daemon=True).start()

    def _on_scan(self):
        self._status_var.set("Scanning...")
        self._disable_buttons()
        self._backend.labeled_positions.clear()

        def _worker():
            frame, accepted, rejected = self._backend.scan_current_frame()
            self.after(0, self._display_results, frame, accepted, rejected)
        threading.Thread(target=_worker, daemon=True).start()

    def _display_results(self, frame, accepted: list[dict], rejected: list[dict]):
        # Clear old cards
        for card in self._cards + self._rejected_cards:
            card.destroy()
        self._cards.clear()
        self._rejected_cards.clear()

        self._current_accepted = accepted
        self._current_rejected = rejected
        self._current_frame = frame

        # Update frame preview
        self._update_frame_preview(frame, accepted, rejected)

        if not accepted and not rejected:
            self._status_var.set("No icons found -- try Drag then Scan")
            self._enable_buttons()
            return

        n_acc = len(accepted)
        n_rej = len(rejected)
        self._status_var.set(
            f"Found {n_acc} accepted + {n_rej} rejected -- label below"
        )

        cols = max(1, self.winfo_width() // (PATCH_DISPLAY_SIZE + 30))
        row_offset = 0

        # Section header: Accepted
        if accepted:
            hdr = tk.Label(self._scroll_frame, text=f"-- Accepted ({n_acc}) --",
                           font=("Consolas", 10, "bold"), bg=BG, fg=GEM_COLOR)
            hdr.grid(row=0, column=0, columnspan=cols, sticky="w", pady=(4, 2))
            self._cards.append(hdr)
            row_offset = 1

        for i, item in enumerate(accepted):
            m = item["match"]
            patch = item["patch"]
            is_gem_color, color_info = is_gem_icon_color(frame, m.x, m.y, m.w, m.h)
            clf_label, clf_conf = self._backend.classifier.predict(patch)

            card = PatchCard(
                self._scroll_frame, idx=i,
                patch_bgr=patch, match=m,
                color_info=color_info, clf_label=clf_label, clf_conf=clf_conf,
                on_label=self._on_patch_labeled,
            )
            row = row_offset + i // cols
            col = i % cols
            card.grid(row=row, column=col, padx=4, pady=4, sticky="n")
            self._cards.append(card)

        # Section header: Rejected
        if rejected and self._show_rejected_var.get():
            rej_row_offset = row_offset + (len(accepted) + cols - 1) // cols
            hdr2 = tk.Label(self._scroll_frame,
                            text=f"-- Rejected ({n_rej}) -- review false negatives --",
                            font=("Consolas", 10, "bold"), bg=BG, fg=NOT_GEM_COLOR)
            hdr2.grid(row=rej_row_offset, column=0, columnspan=cols, sticky="w", pady=(8, 2))
            self._rejected_cards.append(hdr2)
            rej_row_offset += 1

            for j, item in enumerate(rejected):
                m = item["match"]
                patch = item["patch"]
                reason = item["reason"]
                is_gem_color, color_info = is_gem_icon_color(frame, m.x, m.y, m.w, m.h)
                color_info["reason"] = reason
                clf_label, clf_conf = self._backend.classifier.predict(patch)

                card = PatchCard(
                    self._scroll_frame, idx=len(accepted) + j,
                    patch_bgr=patch, match=m,
                    color_info=color_info, clf_label=clf_label, clf_conf=clf_conf,
                    on_label=self._on_patch_labeled,
                    is_rejected=True,
                )
                row = rej_row_offset + j // cols
                col = j % cols
                card.grid(row=row, column=col, padx=4, pady=4, sticky="n")
                self._rejected_cards.append(card)

        self._enable_buttons()

    def _update_frame_preview(self, frame, accepted: list[dict], rejected: list[dict]):
        """Show scaled frame with markers for detected/rejected/manually-marked patches."""
        if frame is None:
            return
        fh, fw = frame.shape[:2]
        target_h = FRAME_PREVIEW_HEIGHT - 10
        scale = target_h / fh
        new_w = int(fw * scale)
        self._frame_scale = scale

        preview = cv2.resize(frame, (new_w, target_h))

        # Draw accepted (green circles)
        for item in accepted:
            m = item["match"]
            cx, cy = int(m.center[0] * scale), int(m.center[1] * scale)
            cv2.circle(preview, (cx, cy), 6, (0, 255, 0), 2)

        # Draw rejected (red circles)
        for item in rejected:
            m = item["match"]
            cx, cy = int(m.center[0] * scale), int(m.center[1] * scale)
            cv2.circle(preview, (cx, cy), 5, (0, 0, 255), 1)

        # Draw manually-marked (cyan diamonds)
        for px, py in self._backend.labeled_positions:
            sx, sy = int(px * scale), int(py * scale)
            pts = np.array([[sx, sy - 5], [sx + 5, sy], [sx, sy + 5], [sx - 5, sy]])
            cv2.polylines(preview, [pts], True, (255, 255, 0), 2)

        preview_rgb = cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(preview_rgb)
        self._frame_photo = ImageTk.PhotoImage(img)
        self._frame_label.configure(image=self._frame_photo, text="")

    def _on_frame_click(self, event):
        """User clicks on frame preview to mark a missed/extra patch."""
        if self._current_frame is None:
            return
        if self._frame_scale <= 0:
            return

        frame_x = int(event.x / self._frame_scale)
        frame_y = int(event.y / self._frame_scale)

        fh, fw = self._current_frame.shape[:2]
        if frame_x < 0 or frame_x >= fw or frame_y < 0 or frame_y >= fh:
            return

        patch = self._backend.extract_patch_at(self._current_frame, frame_x, frame_y)
        if patch.size == 0:
            return

        # Show patch + label choice popup
        self._show_mark_popup(patch, frame_x, frame_y)

    def _show_mark_popup(self, patch: np.ndarray, fx: int, fy: int):
        """Popup showing the cropped patch with label buttons."""
        popup = tk.Toplevel(self)
        popup.title("Label this patch")
        popup.configure(bg=BG)
        popup.geometry("220x200")
        popup.resizable(False, False)
        popup.transient(self)
        popup.grab_set()

        # Show patch
        patch_rgb = cv2.cvtColor(patch, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(patch_rgb).resize((80, 80), Image.NEAREST)
        photo = ImageTk.PhotoImage(img)
        lbl = tk.Label(popup, image=photo, bg=BG)
        lbl.image = photo
        lbl.pack(pady=6)

        tk.Label(popup, text=f"pos=({fx},{fy})", font=("Consolas", 8),
                 bg=BG, fg="#888888").pack()

        btn_frame = tk.Frame(popup, bg=BG)
        btn_frame.pack(pady=8)

        def _do(label):
            self._backend.label_patch(patch, label)
            self._backend.labeled_positions.append((fx, fy))
            self._update_stats()
            self._update_frame_preview(
                self._current_frame, self._current_accepted, self._current_rejected
            )
            self._status_var.set(f"Marked ({fx},{fy}) as {label}")
            popup.destroy()

        tk.Button(btn_frame, text="Gem", font=("Consolas", 9, "bold"), width=6,
                  bg="#225522", fg=GEM_COLOR, bd=0,
                  command=lambda: _do("gem")).pack(side="left", padx=4)
        tk.Button(btn_frame, text="Not", font=("Consolas", 9, "bold"), width=6,
                  bg="#552222", fg=NOT_GEM_COLOR, bd=0,
                  command=lambda: _do("not_gem")).pack(side="left", padx=4)

        popup.bind("<Escape>", lambda e: popup.destroy())

    def _on_patch_labeled(self, idx: int, label: str):
        all_items = self._current_accepted + self._current_rejected
        if idx >= len(all_items):
            return

        item = all_items[idx]
        match = item["match"]
        patch = item["patch"]
        self._backend.labeled_positions.append(match.center)

        self._backend.label_patch(patch, label)
        self._update_stats()

    def _label_all(self, label: str):
        """Label all un-labeled accepted patches with the same label."""
        for card in self._cards:
            if isinstance(card, PatchCard) and not card._labeled:
                card._do_label(label)

    def _toggle_rejected(self):
        """Show/hide rejected section without re-scanning."""
        if self._current_frame is not None:
            self._display_results(
                self._current_frame, self._current_accepted, self._current_rejected
            )

    def _on_save(self):
        clf = self._backend.classifier
        clf.save()
        stats = clf.get_stats()
        total = stats["total"]
        gem = stats["gem"]
        not_gem = stats["not_gem"]
        self._status_var.set(
            f"Saved! Total: {total} samples ({gem} gem, {not_gem} not_gem) "
            f"| Path: {stats['model_path']}"
        )

    def _update_stats(self):
        s = self._backend.stats
        clf_stats = self._backend.classifier.get_stats()
        self._stats_var.set(
            f"session: gem={s['gem']} not={s['not_gem']} | "
            f"total: {clf_stats['total']}"
        )

    def _disable_buttons(self):
        for btn in (self._btn_scan, self._btn_drag, self._btn_nav,
                    self._btn_reset, self._btn_all_gem, self._btn_all_not):
            btn.configure(state="disabled")

    def _enable_buttons(self):
        for btn in (self._btn_scan, self._btn_drag, self._btn_nav,
                    self._btn_reset, self._btn_all_gem, self._btn_all_not):
            btn.configure(state="normal")

    def _on_close(self):
        self._backend.teardown()
        self.destroy()


def main():
    parser = argparse.ArgumentParser(description="Gem Classifier Training Tool (Visual UI)")
    parser.add_argument("--port", default="COM27")
    parser.add_argument("--skip-filters", action="store_true",
                        help="Skip zone filters to get more candidates")
    args = parser.parse_args()

    backend = TrainerBackend(port=args.port, skip_filters=args.skip_filters)
    app = TrainerUI(backend)
    app.mainloop()


if __name__ == "__main__":
    main()
