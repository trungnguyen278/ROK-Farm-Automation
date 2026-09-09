"""Debug frame dumps into screenshots/gem_farm_test/."""

from __future__ import annotations

import random
from datetime import datetime

import cv2

from rok_farm import config as cfg
from rok_farm.config import SCREENSHOT_DIR


def save_screenshot(frame, name):
    if not cfg.SAVE_SCREENSHOTS:
        return None
    ts_offset = random.randint(-30, 30)
    fake_ts = datetime.now().timestamp() + ts_offset
    ts = datetime.fromtimestamp(fake_ts).strftime("%H%M%S")
    path = SCREENSHOT_DIR / f"{name}_{ts}.png"
    cv2.imwrite(str(path), frame)
    return str(path)


def save_annotated(frame, match, name):
    ann = frame.copy()
    if match:
        cv2.rectangle(ann, (match.x, match.y),
                       (match.x + match.w, match.y + match.h), (0, 255, 0), 2)
        cv2.circle(ann, match.center, 5, (0, 0, 255), -1)
        cv2.putText(ann, f"{match.confidence:.3f}", (match.x, match.y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    ts = datetime.now().strftime("%H%M%S")
    path = SCREENSHOT_DIR / f"{name}_{ts}.png"
    cv2.imwrite(str(path), ann)
    return str(path)
