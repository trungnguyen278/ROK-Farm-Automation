"""Background frame capture + window geometry.

A daemon thread keeps the newest game frame ready so the flow never blocks on a
grab. ``_grab`` hands out the day/night-normalized frame and keeps the raw one
in ``self._raw_frame`` (HUD template matching wants the raw pixels).
"""

from __future__ import annotations

import random
import threading
import time

import cv2
import numpy as np

from anti_detection.player_actions import _try_resize_game
from vision.color_filter import normalize_frame

from rok_farm import config as cfg
from rok_farm.config import (DELAY_AFTER_SCROLL, GEM_ICON_THRESHOLD,
                             GEM_ICON_THRESHOLD_NIGHT, TARGET_CONTENT_W,
                             TITLE_BAR_H, ZOOM_OUT_POLL, ZOOM_OUT_QUIET_DIFF,
                             ZOOM_OUT_QUIET_POLLS, ZOOM_OUT_SETTLE_CAP)
from rok_farm.logging_setup import INFO, WARN, logger


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

    @staticmethod
    def _settle_patch(frame) -> np.ndarray | None:
        """Small gray crop of the play area, for frame-to-frame motion checks.

        Deliberately the CENTRE only: the chat box and the HUD animate on their
        own, and including them makes "has the map stopped moving" unanswerable.
        """
        fh, fw = frame.shape[:2]
        roi = frame[int(fh * 0.25):int(fh * 0.72), int(fw * 0.20):int(fw * 0.80)]
        if roi.size == 0:
            return None
        small = cv2.resize(roi, (160, 90), interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

    def _wait_zoom_settled(self) -> float:
        """Human pause after a zoom-out, extended only while the map still moves.

        The fixed pause stays and is drawn exactly as before -- it is what makes
        the bot's timing look human, and measurement said it is long enough
        almost always (see ZOOM_OUT_* in config). What it could not do is notice
        the rare draw that lands under the animation, which hands the first scan
        of a mine a smeared frame. So: pause, look once, and only keep waiting
        if the picture is genuinely still changing.

        Returns the extra seconds spent beyond the normal pause (0.0 when the
        map had already settled, which is the common case).
        """
        self._wait(DELAY_AFTER_SCROLL)

        start = time.monotonic()
        prev = None
        quiet = 0
        saw_motion = False
        while time.monotonic() - start < ZOOM_OUT_SETTLE_CAP:
            frame = self._grab()
            if frame is None:
                self._wait(ZOOM_OUT_POLL)
                continue
            cur = self._settle_patch(frame)
            if cur is None:
                break
            if prev is not None:
                diff = float(np.mean(cv2.absdiff(prev, cur)))
                if diff < ZOOM_OUT_QUIET_DIFF:
                    # Already still on the first look: nothing to wait for.
                    if not saw_motion:
                        prev = None
                        break
                    quiet += 1
                    if quiet >= ZOOM_OUT_QUIET_POLLS:
                        break
                else:
                    saw_motion = True
                    quiet = 0
            prev = cur
            self._wait(ZOOM_OUT_POLL)

        extra = time.monotonic() - start
        if saw_motion:
            logger.debug("zoom-out was still animating after the pause; "
                         "waited %.3fs more", extra)
        return extra

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

    # --- Absolute zoom control -------------------------------------------
    # Every world-map path only ever scrolled OUT, with no reference for what
    # "right" is, so the level ratcheted away until icons rendered at a third
    # of template size and nothing could ever match again (measured 2026-09-09:
    # best-matching scale 0.35-0.40 against a production ladder whose floor is
    # 0.7 -- physically unmatchable, so the bot pans blind and calls it empty
    # ground). A streak counter on ONE of the three zoom-out sites did not stop
    # it, because the other two kept ratcheting.
    #
    # The template ladder itself is the missing instrument: the scale at which
    # gem_icon matches best IS the zoom level. Measure it and correct toward
    # 1.0, one notch at a time, re-measuring after each -- a closed loop needs
    # no per-notch constant and cannot ratchet.
    ZOOM_PROBE_SCALES = [0.35, 0.45, 0.55, 0.7, 0.85, 1.0, 1.15, 1.3]
    ZOOM_OK_RANGE = (0.85, 1.2)

    def _icon_scale(self, frame) -> float | None:
        """Scale at which the gem icon matches best -- i.e. the zoom level."""
        if frame is None:
            return None
        tpl = self.cache.get("resources/gem_icon") if self.cache else None
        if tpl is None:
            return None
        fh, fw = frame.shape[:2]
        roi = frame[int(fh * 0.12):int(fh * 0.85), int(fw * 0.10):int(fw * 0.90)]
        if roi.size == 0:
            return None
        best_v, best_s = 0.0, None
        for sc in self.ZOOM_PROBE_SCALES:
            r = cv2.resize(tpl, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA)
            if r.shape[0] > roi.shape[0] or r.shape[1] > roi.shape[1]:
                continue
            _, v, _, _ = cv2.minMaxLoc(cv2.matchTemplate(roi, r,
                                                         cv2.TM_CCOEFF_NORMED))
            if v > best_v:
                best_v, best_s = v, sc
        # A weak best match says nothing about zoom -- it just means there was
        # no icon in view. Only trust a reading with some signal behind it.
        return best_s if best_v >= 0.62 else None

    def _correct_zoom_level(self, max_steps: int = 9) -> bool:
        """DEPRECATED as a controller -- see _reset_zoom_to_reference.

        Kept only as an observation. Driving the zoom from `_icon_scale` cannot
        work: on a frame with no gem icon in it the "best matching scale" is the
        template matching terrain noise, and a 0.35x template is 13x17 px, small
        enough to score over the gate on almost anything. So the reading is
        biased small exactly when the bot is lost, and the loop scrolled in
        forever without the number ever climbing (measured: 0.35, 0.45, 0.35,
        0.55, 0.45, 0.35 while scrolling in every time). A gauge that only reads
        correctly once you can already see what you are looking for is not a
        gauge.
        """
        return True

    # Notches to reach the zoom-in clamp from anywhere. The game stops zooming
    # at its own limit, so overshooting is free and lands on a KNOWN state --
    # which is the whole point: an absolute reference needs no measurement, and
    # measurement is what kept failing here.
    ZOOM_CLAMP_NOTCHES = 10

    def _reset_zoom_to_reference(self) -> None:
        """Zoom fully IN (hits the game's clamp), then out to icon zoom.

        Replaces both the blind zoom-out and the measured loop. Deterministic:
        wherever the level had drifted to, this ends at the same place.
        """
        out = cfg.ICON_ZOOM_SCROLLS if cfg.ICON_ZOOM_SCROLLS > 0 else 3
        print(f"  [{INFO}] Zoom reset: in to the clamp, then out {out}")
        logger.info("Zoom reset via clamp, then out %d", out)
        self._scroll_at_center(+1, self.ZOOM_CLAMP_NOTCHES)
        self._wait_zoom_settled()
        self._scroll_at_center(-1, out)
        self._wait_zoom_settled()
