from __future__ import annotations

import logging
import random
import threading
import time
from collections import namedtuple

import cv2
import numpy as np
import win32gui

logger = logging.getLogger(__name__)

ROI = namedtuple("ROI", ["x", "y", "w", "h", "name"])

WINDOW_RETRY_INTERVAL = 30.0


# ---------------------------------------------------------------------------
# Backend: MSS (DXGI Desktop Duplication) -- fallback
# ---------------------------------------------------------------------------

class _MSSBackend:
    def __init__(self):
        import mss
        self._sct = mss.mss()
        self._lock = threading.Lock()
        self._owner_thread = threading.current_thread().ident

    def grab(self, monitor: dict) -> np.ndarray | None:
        try:
            with self._lock:
                current_thread = threading.current_thread().ident
                if current_thread != self._owner_thread:
                    import mss
                    try:
                        self._sct.close()
                    except Exception:
                        pass
                    self._sct = mss.mss()
                    self._owner_thread = current_thread
                shot = self._sct.grab(monitor)
                frame = np.array(shot, dtype=np.uint8)
            return frame[:, :, :3]
        except Exception:
            return None

    def close(self):
        try:
            self._sct.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Backend: Windows Graphics Capture (WGC) -- same API as Game Bar
# ---------------------------------------------------------------------------

class _WGCBackend:
    def __init__(self, window_title: str):
        from windows_capture import WindowsCapture, Frame, CaptureControl

        self._latest_frame: np.ndarray | None = None
        self._lock = threading.Lock()
        self._control: CaptureControl | None = None

        cap = WindowsCapture(
            cursor_capture=False,
            draw_border=False,
            window_name=window_title,
        )

        @cap.event
        def on_frame_arrived(frame: Frame, capture_control: CaptureControl):
            bgr = frame.convert_to_bgr()
            with self._lock:
                self._latest_frame = bgr.frame_buffer

        @cap.event
        def on_closed():
            pass

        self._control = cap.start_free_threaded()

    def grab(self, monitor: dict) -> np.ndarray | None:
        with self._lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()

    def close(self):
        if self._control:
            try:
                self._control.stop()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Backend: OBS WebSocket -- capture via OBS running instance
# ---------------------------------------------------------------------------

class _OBSBackend:
    def __init__(self, host: str = "localhost", port: int = 4455, password: str = ""):
        import obsws_python as obs
        import base64
        self._obs = obs
        self._base64 = base64
        self._client = obs.ReqClient(host=host, port=port, password=password)
        self._source_name: str | None = None

    def _find_game_source(self):
        try:
            scenes = self._client.get_scene_list()
            for scene in scenes.scenes:
                items = self._client.get_scene_item_list(scene["sceneName"])
                for item in items.scene_items:
                    name = item["sourceName"].lower()
                    if any(k in name for k in ("rise", "rok", "game")):
                        self._source_name = item["sourceName"]
                        logger.info("OBS: found game source '%s'", self._source_name)
                        return
        except Exception as e:
            logger.debug("OBS: failed to find game source: %s", e)

    def grab(self, monitor: dict) -> np.ndarray | None:
        if not self._source_name:
            self._find_game_source()
        if not self._source_name:
            return None
        try:
            resp = self._client.get_source_screenshot(
                name=self._source_name, img_format="png", width=0, height=0,
            )
            img_data = self._base64.b64decode(resp.image_data.split(",")[1])
            arr = np.frombuffer(img_data, dtype=np.uint8)
            return cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except Exception as e:
            logger.debug("OBS: grab failed: %s", e)
            return None

    def close(self):
        try:
            self._client.disconnect()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# ScreenCapture facade -- random backend switching for anti-detection
# ---------------------------------------------------------------------------

class ScreenCapture:
    def __init__(self, window_title: str = "Rise of Kingdoms"):
        self._title = window_title
        self._window: dict | None = None
        self._last_window_search: float = 0.0
        self._consecutive_failures: int = 0

        self._backends: list[tuple[str, object]] = []
        self._active: object | None = None
        self._active_name: str = ""
        self._switch_interval: float = random.uniform(300, 900)
        self._last_switch: float = time.monotonic()

        self._init_backends()

    def _init_backends(self):
        for name, init_fn in [("wgc", self._try_wgc), ("obs", self._try_obs)]:
            try:
                backend = init_fn()
                if backend:
                    self._backends.append((name, backend))
                    logger.info("Capture backend '%s' ready", name)
            except Exception as e:
                logger.debug("Capture backend '%s' unavailable: %s", name, e)

        if not self._backends:
            logger.info("No WGC/OBS backend, falling back to mss (DXGI)")
            self._backends.append(("mss", _MSSBackend()))

        self._active_name, self._active = random.choice(self._backends)
        available = [n for n, _ in self._backends]
        logger.info("Screen capture: %s (available: %s)", self._active_name, available)

    def _try_wgc(self):
        return _WGCBackend(self._title)

    def _try_obs(self):
        return _OBSBackend()

    def _random_switch(self):
        others = [(n, b) for n, b in self._backends if n != self._active_name]
        if others:
            self._active_name, self._active = random.choice(others)
            self._switch_interval = random.uniform(300, 900)
            self._last_switch = time.monotonic()
            logger.info("Switched capture backend to: %s", self._active_name)

    def find_window(self) -> dict | None:
        result: dict | None = None

        def _enum_cb(hwnd, _):
            nonlocal result
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd)
                if self._title.lower() in title.lower():
                    rect = win32gui.GetWindowRect(hwnd)
                    result = {
                        "left": rect[0],
                        "top": rect[1],
                        "width": rect[2] - rect[0],
                        "height": rect[3] - rect[1],
                    }
            except Exception:
                pass

        try:
            win32gui.EnumWindows(_enum_cb, None)
        except Exception:
            logger.error("Failed to enumerate windows")
            self._window = None
            return None

        if result and result["width"] > 0 and result["height"] > 0:
            self._window = result
            logger.info("Found window '%s' at %s", self._title, result)
        else:
            self._window = None
            logger.warning("Window '%s' not found", self._title)
        return self._window

    @property
    def window(self) -> dict | None:
        return self._window

    def grab_full(self) -> np.ndarray | None:
        if not self._window:
            now = time.monotonic()
            if now - self._last_window_search < WINDOW_RETRY_INTERVAL:
                return None
            self._last_window_search = now
            if not self.find_window():
                return None

        if len(self._backends) > 1:
            elapsed = time.monotonic() - self._last_switch
            if elapsed > self._switch_interval:
                self._random_switch()

        monitor = {
            "left": self._window["left"],
            "top": self._window["top"],
            "width": self._window["width"],
            "height": self._window["height"],
        }

        frame = self._active.grab(monitor)
        if frame is not None:
            self._consecutive_failures = 0
            return frame

        self._consecutive_failures += 1
        if len(self._backends) > 1:
            self._random_switch()
            frame = self._active.grab(monitor)
            if frame is not None:
                self._consecutive_failures = 0
                return frame

        if self._consecutive_failures >= 3:
            logger.warning("Capture failed %d times, resetting backends",
                           self._consecutive_failures)
            self._window = None
            self._consecutive_failures = 0

        return None

    def grab_roi(self, roi: ROI) -> np.ndarray | None:
        frame = self.grab_full()
        if frame is None:
            return None
        h, w = frame.shape[:2]
        x1 = int(roi.x * w)
        y1 = int(roi.y * h)
        x2 = x1 + int(roi.w * w)
        y2 = y1 + int(roi.h * h)
        x1, x2 = max(0, x1), min(w, x2)
        y1, y2 = max(0, y1), min(h, y2)
        return frame[y1:y2, x1:x2]

    def close(self):
        for _, backend in self._backends:
            try:
                backend.close()
            except Exception:
                pass
