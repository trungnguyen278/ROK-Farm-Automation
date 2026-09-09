"""Vision-only scan: what does the current frame look like to the detector?

No ESP32, no clicking -- grab one frame, run the gem-icon template match plus
the colour filter, and write an annotated PNG. Used to sanity-check detection
without risking a live action.
"""

from __future__ import annotations

from datetime import datetime

import cv2

from capture.screen_capture import ScreenCapture
from vision.color_filter import is_gem_icon_color
from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher

from rok_farm.config import GEM_ICON_THRESHOLD, SCREENSHOT_DIR, TEMPLATE_DIR
from rok_farm.logging_setup import FAIL, PASS, WARN


def run_find_only():
    print("=" * 60)
    print("  GEM FARM -- Find-Only (vision scan, no ESP32)")
    print("=" * 60)
    print()

    sc = ScreenCapture()
    win = sc.find_window()
    if not win:
        print(f"  [{FAIL}] Game window not found")
        return
    print(f"  [{PASS}] Window: {win['width']}x{win['height']}")

    cache = TemplateCache(TEMPLATE_DIR)
    matcher = TemplateMatcher(cache, threshold=0.50)

    tpl = cache.get("resources/gem_icon")
    if tpl is None:
        print(f"  [{FAIL}] gem_icon template MISSING")
        return
    print(f"  [{PASS}] gem_icon template: {tpl.shape[1]}x{tpl.shape[0]}")

    frame = sc.grab_full()
    if frame is None:
        print(f"  [{FAIL}] Screen capture failed")
        return
    print(f"  [{PASS}] Frame: {frame.shape[1]}x{frame.shape[0]}")

    ts = datetime.now().strftime("%H%M%S")
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(SCREENSHOT_DIR / f"find_only_{ts}.png"), frame)

    all_matches = matcher.match_all(frame, "resources/gem_icon", overlap_thresh=0.3)
    print(f"\n  Raw matches (any conf): {len(all_matches)}")
    for m in sorted(all_matches, key=lambda x: -x.confidence):
        print(f"    conf={m.confidence:.3f} at {m.center} ({m.w}x{m.h})")

    above_thresh = [m for m in all_matches if m.confidence >= GEM_ICON_THRESHOLD]
    print(f"\n  Above threshold ({GEM_ICON_THRESHOLD}): {len(above_thresh)}")

    gems = []
    for m in sorted(above_thresh, key=lambda x: -x.confidence):
        is_gem, info = is_gem_icon_color(frame, m.x, m.y, m.w, m.h)
        status = PASS if is_gem else FAIL
        print(f"    [{status}] conf={m.confidence:.3f} at {m.center} color={info}")
        if is_gem:
            gems.append(m)

    # Draw annotated frame
    ann = frame.copy()
    for m in all_matches:
        if m.confidence < GEM_ICON_THRESHOLD:
            color = (128, 128, 128)  # gray: below threshold
        elif m in gems:
            color = (0, 255, 0)  # green: gem confirmed
        else:
            color = (0, 0, 255)  # red: color rejected
        cv2.rectangle(ann, (m.x, m.y), (m.x + m.w, m.y + m.h), color, 2)
        cv2.putText(ann, f"{m.confidence:.2f}", (m.x, m.y - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
    ann_path = SCREENSHOT_DIR / f"find_only_annotated_{ts}.png"
    cv2.imwrite(str(ann_path), ann)

    print(f"\n{'=' * 60}")
    if gems:
        print(f"  [{PASS}] Found {len(gems)} gem icon(s) on current frame")
    else:
        print(f"  [{WARN}] No gem icons on current frame (may need to be on world map at icon-zoom)")
    print(f"  Annotated: {ann_path}")
    print(f"{'=' * 60}")

    sc.close()
