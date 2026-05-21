"""Capture 10 WGC frames and analyze black row stats."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
from capture.screen_capture import _WGCBackend

print("Starting WGC capture...")
wgc = _WGCBackend("Rise of Kingdoms")
time.sleep(1.0)

os.makedirs("screenshots/wgc_debug", exist_ok=True)

for i in range(20):
    frame = wgc.grab({})
    if frame is None:
        print("[%02d] None" % i)
        time.sleep(0.1)
        continue

    h, w = frame.shape[:2]
    ch = frame.shape[2] if len(frame.shape) > 2 else 1
    gray = np.mean(frame[:, :, :3], axis=2) if ch >= 3 else frame.astype(float)
    row_means = np.mean(gray, axis=1)
    black_rows = np.sum(row_means < 8)
    black_pct = black_rows / len(row_means) * 100

    # Find contiguous black bands
    is_black = row_means < 8
    bands = []
    start = None
    for r in range(len(is_black)):
        if is_black[r] and start is None:
            start = r
        elif not is_black[r] and start is not None:
            bands.append((start, r - 1, r - start))
            start = None
    if start is not None:
        bands.append((start, len(is_black) - 1, len(is_black) - start))

    band_str = ""
    if bands:
        biggest = max(bands, key=lambda b: b[2])
        band_str = " biggest_band=%d rows @%d-%d" % (biggest[2], biggest[0], biggest[1])

    tag = "BAD" if black_pct > 4 else "OK "
    cv2.imwrite("screenshots/wgc_debug/frame_%02d.png" % i, frame)
    print("[%02d] %s %dx%d ch=%d black_rows=%d (%.1f%%)%s" % (i, tag, w, h, ch, black_rows, black_pct, band_str))
    time.sleep(0.15)

wgc.close()
print("\nFrames saved to screenshots/wgc_debug/")
