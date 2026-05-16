"""Debug specific scan frames: template match + color filter + march line analysis."""
import sys
import os
import cv2
import numpy as np
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher
from vision.color_filter import is_gem_icon_color

SCREENSHOT_DIR = Path("tools/screenshots/gem_farm_test")
DEBUG_DIR = Path("tools/screenshots/debug_scan")
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

FRAMES = [
    "m1_scan_04_152809",
    "m1_scan_06_152825",
    "m2_scan_04_152935",
    "m2_scan_12_153014",
]


def analyze_march_lines(frame, cx, cy, icon_r):
    fh, fw = frame.shape[:2]
    pad = icon_r * 5
    y1 = max(cy - pad, 0)
    y2 = min(cy + pad, fh)
    x1 = max(cx - pad, 0)
    x2 = min(cx + pad, fw)

    roi = frame[y1:y2, x1:x2]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    color_mask = ((hsv[:, :, 2] > 180) & (hsv[:, :, 1] < 80)).astype(np.uint8) * 255
    edge_mask = cv2.Canny(gray, 80, 200)

    min_len = icon_r * 3
    icon_lx = cx - x1
    icon_ly = cy - y1
    near_r = icon_r * 3

    results = {}
    for name, mask in [("color_s80_v180", color_mask), ("canny_edge", edge_mask)]:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 1))
        closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

        lines = cv2.HoughLinesP(closed, 1, np.pi / 180,
                                threshold=40, minLineLength=min_len, maxLineGap=10)

        converging = []
        if lines is not None:
            for line in lines:
                lx1, ly1, lx2, ly2 = line[0]
                length = np.sqrt((lx2 - lx1) ** 2 + (ly2 - ly1) ** 2)
                if length < min_len:
                    continue
                d1 = np.sqrt((lx1 - icon_lx) ** 2 + (ly1 - icon_ly) ** 2)
                d2 = np.sqrt((lx2 - icon_lx) ** 2 + (ly2 - icon_ly) ** 2)
                near = min(d1, d2) < near_r

                bright_ok = True
                if name == "canny_edge" and near:
                    pts = np.linspace(0, 1, 10)
                    bright_count = 0
                    for t in pts:
                        px = int(lx1 + t * (lx2 - lx1))
                        py = int(ly1 + t * (ly2 - ly1))
                        px = max(0, min(px, roi.shape[1] - 1))
                        py = max(0, min(py, roi.shape[0] - 1))
                        if hsv[py, px, 2] > 120:
                            bright_count += 1
                    bright_ok = bright_count >= 6

                converging.append({
                    "line": (lx1, ly1, lx2, ly2),
                    "len": length,
                    "endpt_min": min(d1, d2),
                    "near": near,
                    "bright_ok": bright_ok,
                })

        results[name] = {
            "total_lines": len(lines) if lines is not None else 0,
            "long_lines": len(converging),
            "converging": [c for c in converging if c["near"] and c["bright_ok"]],
            "roi_offset": (x1, y1),
        }

    return results


def main():
    cache = TemplateCache("templates")
    matcher = TemplateMatcher(cache, threshold=0.50)

    tpl = cache.get("resources/gem_icon")
    print(f"gem_icon template: {tpl.shape[1]}x{tpl.shape[0]}")

    for fname in FRAMES:
        path = SCREENSHOT_DIR / f"{fname}.png"
        if not path.exists():
            print(f"\n*** {fname}: FILE NOT FOUND ***")
            continue

        frame = cv2.imread(str(path))
        print(f"\n{'='*70}")
        print(f"  {fname} ({frame.shape[1]}x{frame.shape[0]})")
        print(f"{'='*70}")

        # 1) Raw template matches at various thresholds
        all_matches = matcher.match_all(frame, "resources/gem_icon", overlap_thresh=0.3)
        print(f"\n  Template matches (raw): {len(all_matches)}")
        for m in sorted(all_matches, key=lambda x: -x.confidence):
            is_gem, info = is_gem_icon_color(frame, m.x, m.y, m.w, m.h)
            gem_str = "GEM" if is_gem else "REJECT"
            print(f"    conf={m.confidence:.3f} at ({m.x:4d},{m.y:4d}) {m.w}x{m.h} "
                  f"color={gem_str} {info}")

        # 2) Annotate frame with all matches
        ann = frame.copy()
        for m in all_matches:
            is_gem, _ = is_gem_icon_color(frame, m.x, m.y, m.w, m.h)
            if m.confidence >= 0.80 and is_gem:
                color = (0, 255, 0)   # green: would be detected
            elif m.confidence >= 0.80:
                color = (0, 165, 255) # orange: above thresh but color reject
            elif m.confidence >= 0.65 and is_gem:
                color = (255, 255, 0) # cyan: below thresh but IS gem
            elif m.confidence >= 0.65:
                color = (0, 0, 255)   # red: below thresh + color reject
            else:
                color = (128, 128, 128)  # gray
            cv2.rectangle(ann, (m.x, m.y), (m.x + m.w, m.y + m.h), color, 2)
            cv2.putText(ann, f"{m.confidence:.2f}", (m.x, m.y - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

        # 3) March line analysis for top matches
        gem_matches = [m for m in all_matches if m.confidence >= 0.65]
        for m in gem_matches:
            is_gem, _ = is_gem_icon_color(frame, m.x, m.y, m.w, m.h)
            if not is_gem:
                continue
            icon_r = max(m.w, m.h)
            results = analyze_march_lines(frame, m.center[0], m.center[1], icon_r)
            print(f"\n  March line analysis at {m.center} (conf={m.confidence:.3f}):")
            for filter_name, res in results.items():
                conv = res["converging"]
                print(f"    {filter_name}: {res['total_lines']} total, "
                      f"{res['long_lines']} long, {len(conv)} converging")
                for c in conv:
                    print(f"      line len={c['len']:.0f} endpt={c['endpt_min']:.0f}")

                # Draw detected lines on annotated frame
                ox, oy = res["roi_offset"]
                for c in conv:
                    lx1, ly1, lx2, ly2 = c["line"]
                    pt1 = (lx1 + ox, ly1 + oy)
                    pt2 = (lx2 + ox, ly2 + oy)
                    line_color = (255, 0, 255) if filter_name == "white_s50_v200" else (255, 128, 0)
                    cv2.line(ann, pt1, pt2, line_color, 2)

        cv2.imwrite(str(DEBUG_DIR / f"{fname}_debug.png"), ann)
        print(f"\n  Saved: {DEBUG_DIR / f'{fname}_debug.png'}")


if __name__ == "__main__":
    main()
