"""Background frame capture + window geometry.

A daemon thread keeps the newest game frame ready so the flow never blocks on a
grab. ``_grab`` hands out the day/night-normalized frame and keeps the raw one
in ``self._raw_frame`` (HUD template matching wants the raw pixels).
"""

from __future__ import annotations

import random
import threading
import time

import numpy as np

from anti_detection.player_actions import _try_resize_game
from vision.color_filter import normalize_frame

from rok_farm import config as cfg
from rok_farm.config import (GEM_ICON_THRESHOLD, GEM_ICON_THRESHOLD_NIGHT,
                             TARGET_CONTENT_W, TITLE_BAR_H)
from rok_farm.logging_setup import INFO, WARN


class CaptureMixin:
    """Capture thread, frame access, window geometry. Mixed into GemFarmRunner."""

    # --- Frame capture with day/night normalization ---

    def _start_capture_thread(self):
        # The frame buffer and its lock come from __init__ so setup-time
        # detection (launching the game) can grab frames before this runs.
        self._capture_running = True
        self._capture_paused = False
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

    def _stop_capture_thread(self):
        self._capture_running = False
        if hasattr(self, '_capture_thread') and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)

    def _capture_loop(self):
        win_refresh_interval = 10.0
        last_win_refresh = time.monotonic()
        while self._capture_running:
            # While alt-tabbed away (Phase 3) we only read OS notifications, so
            # don't grab the screen -- it's wasted work and a needless capture of
            # a backgrounded window. Resume the moment we tab back in.
            if self._capture_paused:
                # Keep the health clock fresh while paused on purpose, so the
                # 15-minute alt-tab wait is not mistaken for a frozen client.
                self._last_frame_ok = time.time()
                time.sleep(0.2)
                continue
            frame = self.sc.grab_full()
            if frame is not None:
                with self._frame_lock:
                    self._bg_back = self._bg_frame
                    self._bg_frame = frame
                # Health signal for _client_looks_broken: a dead client stops
                # producing frames entirely. (Frame *motion* is not a health
                # signal in this game -- see the note in config.py.)
                self._last_frame_ok = time.time()
            now = time.monotonic()
            if now - last_win_refresh > win_refresh_interval:
                self._refresh_window()
                last_win_refresh = now
            time.sleep(random.uniform(0.03, 0.15))

    def _grab(self) -> np.ndarray | None:
        with self._frame_lock:
            if self._bg_frame is None:
                self._raw_frame = None
                return None
            frame = self._bg_frame
            self._bg_frame = self._bg_back
        self._raw_frame = frame
        normalized, is_night = normalize_frame(frame)
        self._is_night = is_night
        if is_night and not self._night_logged:
            print(f"  [{INFO}] Night mode detected -- normalizing frames")
            self._night_logged = True
        return normalized

    def _gem_icon_threshold(self) -> float:
        """At night the gem_icon template (captured by day) only matches ~0.65-0.71
        even after normalization, so the day gate (0.72) drops real gems. Use a
        lower gate at night and let the classifier + color filter discriminate."""
        return GEM_ICON_THRESHOLD_NIGHT if getattr(self, "_is_night", False) else GEM_ICON_THRESHOLD

    # --- Coordinate helpers (all constrained to game window) ---

    def _refresh_window(self):
        w = self.sc.find_window()
        if w:
            self.win = w

    def _ensure_target_size(self) -> bool:
        """Resize the client to TARGET_CONTENT_W so template scales match.

        Every template was captured at that width, so detection is unreliable
        until this has run -- which is why it happens the moment a window
        appears (fresh launch included), not only once at setup.
        """
        if not self.win:
            return False
        if self.win["width"] == TARGET_CONTENT_W:
            return True
        print(f"  [{INFO}] Resizing game {self.win['width']}x{self.win['height']} "
              f"-> w={TARGET_CONTENT_W}")
        try:
            _try_resize_game(self.sc, TARGET_CONTENT_W)
        except Exception as e:
            print(f"  [{WARN}] Resize failed: {e}")
            return False
        time.sleep(0.3)
        self.sc._window = None
        w = self.sc.find_window()
        if w:
            self.win = w
        print(f"  [{INFO}] Window now: {self.win['width']}x{self.win['height']}")
        return self.win["width"] == TARGET_CONTENT_W

    def _screen_xy(self, frame_x: int, frame_y: int) -> tuple[int, int]:
        raw = self._raw_frame
        if raw is not None:
            fh, fw = raw.shape[:2]
            ww, wh = self.win["width"], self.win["height"]
            if fw > 0 and fh > 0 and (fw != ww or fh != wh):
                frame_x = int(frame_x * ww / fw)
                frame_y = int(frame_y * wh / fh)
        return frame_x + self.win["left"], frame_y + self.win["top"]

    def _center_screen(self) -> tuple[int, int]:
        return (self.win["left"] + self.win["width"] // 2,
                self.win["top"] + self.win["height"] // 2)

    @staticmethod
    def _zoom_scrolls() -> int:
        # Read through the module: --zoom-scrolls rebinds cfg.ICON_ZOOM_SCROLLS
        # at startup, and a by-name import here would freeze the default.
        return cfg.ICON_ZOOM_SCROLLS if cfg.ICON_ZOOM_SCROLLS > 0 else 3

    def _clamp_to_window(self, sx: int, sy: int, pad: int = 5) -> tuple[int, int]:
        x = max(self.win["left"] + pad, min(self.win["left"] + self.win["width"] - pad, sx))
        top_pad = max(pad, TITLE_BAR_H)
        y = max(self.win["top"] + top_pad, min(self.win["top"] + self.win["height"] - pad, sy))
        return x, y

    def _clamp_to_play_area(self, sx: int, sy: int) -> tuple[int, int]:
        wl, wt = self.win["left"], self.win["top"]
        ww, wh = self.win["width"], self.win["height"]
        x = max(wl + int(ww * 0.12), min(wl + int(ww * 0.88), sx))
        y = max(wt + int(wh * 0.22), min(wt + int(wh * 0.70), sy))
        return x, y
