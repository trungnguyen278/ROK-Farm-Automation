from __future__ import annotations

import logging
from collections import namedtuple

import mss
import numpy as np
import win32gui

logger = logging.getLogger(__name__)

ROI = namedtuple("ROI", ["x", "y", "w", "h", "name"])


class ScreenCapture:
    def __init__(self, window_title: str = "Rise of Kingdoms"):
        self._title = window_title
        self._sct = mss.mss()
        self._window: dict | None = None

    def find_window(self) -> dict | None:
        result: dict | None = None

        def _enum_cb(hwnd, _):
            nonlocal result
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

        win32gui.EnumWindows(_enum_cb, None)
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
            if not self.find_window():
                return None
        monitor = {
            "left": self._window["left"],
            "top": self._window["top"],
            "width": self._window["width"],
            "height": self._window["height"],
        }
        shot = self._sct.grab(monitor)
        frame = np.array(shot, dtype=np.uint8)
        return frame[:, :, :3]  # BGRA → BGR

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
        self._sct.close()
