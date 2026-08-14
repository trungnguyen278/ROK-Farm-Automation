"""March queue OCR -- reads the "x/5" counter in the top-right corner.

RapidOCR is preferred; pytesseract is the fallback. With neither installed the
runner falls back to its internal completed-march counter.
"""

from __future__ import annotations

import random
import re
import time

import cv2

from rok_farm.logging_setup import logger
from rok_farm.screenshots import save_screenshot

try:
    from rapidocr_onnxruntime import RapidOCR
    _ocr_engine = RapidOCR()
    _OCR_BACKEND = "rapidocr"
except ImportError:
    _ocr_engine = None
    try:
        import pytesseract
        _OCR_BACKEND = "pytesseract"
    except ImportError:
        _OCR_BACKEND = None


class QueueMixin:
    """March queue reading. Mixed into GemFarmRunner."""

    def _detect_march_queue(self, retries: int = 3) -> tuple[int, int] | None:
        """Read march queue (e.g. '1/5') via OCR. Returns (used, total) or None.

        A single OCR pass misses often (frame timing, faint text), which made the
        turn-1 'is the queue already full' check unreliable. Retry across a few
        fresh frames; on total failure save the ROI crop so the region can be
        verified against the actual queue indicator.
        """
        if _OCR_BACKEND is None:
            return None

        last_roi = None
        last_text = ""
        for attempt in range(max(1, retries)):
            if attempt > 0:
                time.sleep(random.uniform(0.25, 0.45))
            frame = self._grab()
            if frame is None:
                continue
            # Queue "x/5" counter sits at client ~(0.97, 0.15); box measured at
            # x[0.948,0.997] y[0.137,0.168]. Hug it (the old y 0.15-0.26 started
            # below the digits and ran down into terrain -> intermittent misses).
            fh, fw = frame.shape[:2]
            x1 = int(fw * 0.92)
            y1 = int(fh * 0.10)
            x2 = fw
            y2 = int(fh * 0.21)
            roi = frame[y1:y2, x1:x2]
            last_roi = roi

            try:
                texts = []
                if _OCR_BACKEND == "rapidocr":
                    result, _ = _ocr_engine(roi)
                    if result:
                        sorted_r = sorted(result, key=lambda r: r[0][0][0])
                        texts = [''.join(r[1] for r in sorted_r)]
                else:
                    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
                    binary = cv2.resize(binary, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
                    raw = pytesseract.image_to_string(
                        binary, config='--psm 7 -c tessedit_char_whitelist=0123456789/')
                    texts = [raw.strip()]

                for text in texts:
                    last_text = text
                    logger.debug("Queue OCR (try %d/%d): '%s'", attempt + 1, retries, text)
                    m = re.search(r'(\d)\s*/\s*(\d)', text)
                    if m:
                        used, total = int(m.group(1)), int(m.group(2))
                        if 0 <= used <= total <= 9:
                            return used, total
            except Exception as e:
                logger.debug("Queue OCR error: %s", e)

        # All retries failed -- save the ROI so the crop position can be verified.
        if last_roi is not None and last_roi.size > 0:
            path = save_screenshot(last_roi, "queue_roi_miss")
            logger.debug("Queue OCR failed after %d tries (last text='%s'); saved %s",
                         retries, last_text, path)
        return None
