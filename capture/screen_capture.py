from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import threading
import time
from collections import namedtuple

import numpy as np
import win32gui

logger = logging.getLogger(__name__)

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

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
# ScreenCapture facade -- WGC preferred, MSS fallback
# ---------------------------------------------------------------------------

class ScreenCapture:
    def __init__(self, window_title: str = "Rise of Kingdoms"):
        self._title = window_title
        self._window: dict | None = None
        self._last_window_search: float = 0.0
        self._consecutive_failures: int = 0

        self._backend: object | None = None
        self._backend_name: str = ""

        self._init_backend()

    def _init_backend(self):
        for name, init_fn in [("wgc", self._try_wgc), ("mss", self._try_mss)]:
            try:
                backend = init_fn()
                if backend:
                    self._backend = backend
                    self._backend_name = name
                    logger.info("Screen capture: %s", name)
                    return
            except Exception as e:
                logger.debug("Capture backend '%s' unavailable: %s", name, e)

        logger.error("No capture backend available")

    def _try_wgc(self):
        return _WGCBackend(self._title)

    def _try_mss(self):
        return _MSSBackend()

    @staticmethod
    def _get_visible_rect(hwnd) -> tuple[int, int, int, int] | None:
        """Get visible window rect via DWM (excludes invisible shadow border)."""
        DWMWA_EXTENDED_FRAME_BOUNDS = 9
        rect = ctypes.wintypes.RECT()
        hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rect), ctypes.sizeof(rect),
        )
        if hr == 0:
            return rect.left, rect.top, rect.right, rect.bottom
        return None

    def find_window(self) -> dict | None:
        result: dict | None = None

        def _enum_cb(hwnd, _):
            nonlocal result
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd)
                if self._title.lower() in title.lower():
                    vis = ScreenCapture._get_visible_rect(hwnd)
                    if vis:
                        left, top, right, bottom = vis
                    else:
                        r = win32gui.GetWindowRect(hwnd)
                        left, top, right, bottom = r[0], r[1], r[2], r[3]
                    pt = win32gui.ClientToScreen(hwnd, (0, 0))
                    cl = win32gui.GetClientRect(hwnd)
                    client_w = cl[2] - cl[0]
                    client_h = cl[3] - cl[1]
                    result = {
                        "left": pt[0],
                        "top": pt[1],
                        "width": client_w,
                        "height": client_h,
                        "full_top": top,
                        "full_height": bottom - top,
                        "titlebar_h": pt[1] - top,
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

    @property
    def needs_window_rect(self) -> bool:
        return self._backend_name != "wgc"

    def grab_full(self) -> np.ndarray | None:
        if not self._backend:
            return None

        if not self._window:
            now = time.monotonic()
            if now - self._last_window_search < WINDOW_RETRY_INTERVAL:
                return None
            self._last_window_search = now
            if not self.find_window():
                return None

        monitor = {
            "left": self._window["left"],
            "top": self._window["top"],
            "width": self._window["width"],
            "height": self._window["height"],
        }

        cw = monitor["width"]
        ch = monitor["height"]

        for _retry in range(6):
            frame = self._backend.grab(monitor)
            if frame is not None and not self._has_black_bars(frame):
                fh, fw = frame.shape[:2]
                if fw > cw or fh > ch:
                    x_off = (fw - cw) // 2
                    y_off = fh - ch
                    frame = frame[y_off:y_off + ch, x_off:x_off + cw]
                self._consecutive_failures = 0
                return frame
            time.sleep(0.08)

        self._consecutive_failures += 1
        if self._consecutive_failures >= 3:
            logger.warning("Capture failed %d times, re-finding window",
                           self._consecutive_failures)
            self._window = None
            self._consecutive_failures = 0

        return None

    @staticmethod
    def _has_black_bars(frame: np.ndarray) -> bool:
        gray = np.mean(frame, axis=2)
        row_means = np.mean(gray, axis=1)
        black_rows = row_means < 8
        if np.sum(black_rows) > len(row_means) * 0.04:
            return True
        col_means = np.mean(gray, axis=0)
        black_cols = col_means < 8
        if np.sum(black_cols) > len(col_means) * 0.04:
            return True
        return False

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
        if self._backend:
            try:
                self._backend.close()
            except Exception:
                pass
