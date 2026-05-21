"""Test badge detection on a static screenshot."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np

BADGE_X_RANGE = (0.02, 0.07)
CHAT_CHANNELS = [
    {"center": (0.09, 0.12), "badge_y": (0.06, 0.15)},
    {"center": (0.09, 0.21), "badge_y": (0.17, 0.25)},
    {"center": (0.09, 0.30), "badge_y": (0.26, 0.34)},
]


def _find_badge_circle(red_mask):
    mask_u8 = red_mask.astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    best = None
    best_score = -1
    for c in contours:
        area = cv2.contourArea(c)
        if area < 30:
            continue
        x, y, w, h = cv2.boundingRect(c)
        perimeter = cv2.arcLength(c, True)
        circularity = (4 * np.pi * area / (perimeter * perimeter)) if perimeter > 0 else 0
        aspect = min(w, h) / max(w, h) if max(w, h) > 0 else 0
        score = circularity * 2 + aspect
        if score > best_score:
            best_score = score
            best = (x, y, w, h, area)
    return best


def _extract_digits(badge_crop, red_mask_crop):
    gray = cv2.cvtColor(badge_crop, cv2.COLOR_BGR2GRAY)
    _, white_mask = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
    kernel = np.ones((3, 3), np.uint8)
    red_expanded = cv2.dilate(red_mask_crop.astype(np.uint8) * 255, kernel, iterations=2)
    digit_mask = (white_mask > 0) & (red_expanded > 0)
    digit_u8 = digit_mask.astype(np.uint8) * 255

    contours, _ = cv2.findContours(digit_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    digits = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        area = cv2.contourArea(c)
        if area >= 3 and h >= 4:
            crop = digit_u8[y:y+h, x:x+w]
            digits.append((crop, (x, y, w, h), area))
    digits.sort(key=lambda d: d[1][0])
    return digits


def _classify_digit(digit_img, bbox, contour_area):
    x, y, w, h = bbox
    binary = (digit_img > 0).astype(np.uint8)

    # Middle stem width: average active pixels per row in middle 40% of height
    r1 = int(h * 0.30)
    r2 = int(h * 0.70)
    if r2 > r1:
        mid_rows = binary[r1:r2, :]
        mid_active_per_row = mid_rows.sum(axis=1).astype(float)
        mid_width = float(mid_active_per_row.mean())
    else:
        mid_width = w

    # Hole detection
    padded = np.zeros((h + 2, w + 2), dtype=np.uint8)
    padded[1:h+1, 1:w+1] = binary * 255
    inv = cv2.bitwise_not(padded)
    n_labels, _ = cv2.connectedComponents(inv)
    holes = max(0, n_labels - 2)

    # Bottom row fill
    bot_fill = float(binary[-1, :].sum()) / w if w > 0 else 0
    # Top row fill
    top_fill = float(binary[0, :].sum()) / w if w > 0 else 0

    # Top half vs bottom half pixel count
    mid_h = h // 2
    top_px = int(binary[:mid_h, :].sum())
    bot_px = int(binary[mid_h:, :].sum())
    total_px = int(binary.sum())
    top_frac = top_px / total_px if total_px > 0 else 0.5

    # Column center of mass shift: how much the center moves from top to bottom
    row_centers = []
    for r in range(h):
        cols = np.where(binary[r, :] > 0)[0]
        if len(cols) > 0:
            row_centers.append(float(cols.mean()))
        else:
            row_centers.append(w / 2.0)
    if len(row_centers) >= 4:
        top_center = np.mean(row_centers[:h//3])
        bot_center = np.mean(row_centers[2*h//3:])
        center_shift = (bot_center - top_center) / w if w > 0 else 0
    else:
        center_shift = 0

    print(f"      {w}x{h} mid_w={mid_width:.1f} holes={holes} "
          f"top_fill={top_fill:.2f} bot_fill={bot_fill:.2f} "
          f"top_frac={top_frac:.2f} shift={center_shift:.2f}")

    # === "1": thin middle stem + narrow bbox OR no lateral shift ===
    if mid_width <= 2.5 and (w <= 5 or abs(center_shift) < 0.05):
        return 1

    # === Hole-based digits ===
    if holes >= 2:
        return 8

    if holes >= 1:
        # Find WHERE the hole is by locating enclosed dark regions
        padded_inv = cv2.bitwise_not(padded)
        n_lab, labels = cv2.connectedComponents(padded_inv)
        hole_cy_list = []
        for lab in range(2, n_lab):  # skip background (0) and outer region (1)
            ys_h = np.where(labels == lab)[0] - 1  # undo padding offset
            if len(ys_h) > 0:
                hole_cy_list.append(float(ys_h.mean()) / h)

        if hole_cy_list:
            avg_hole_y = np.mean(hole_cy_list)
            print(f"        hole_y={avg_hole_y:.2f} (0=top, 1=bot)")
        else:
            avg_hole_y = 0.5

        if holes >= 2:
            return 8

        # Single hole — where is it?
        if avg_hole_y < 0.40:
            return 9  # hole in top → "9"
        if avg_hole_y > 0.60:
            return 6  # hole in bottom → "6"
        # Hole in middle → "0", "4"
        if center_shift < -0.15:
            return 4
        return 0

    # === No holes ===
    # "7": top bar + diagonal, very few bottom pixels
    if top_frac > 0.55 and bot_fill < 0.5 and mid_width < w * 0.5:
        return 7

    # "2": top-right curve, diagonal, bottom bar (center shifts right-to-left)
    if center_shift < -0.05 and bot_fill > 0.7:
        return 2

    # "3": right-heavy, mid-bar
    mid_row_fill = float(binary[h//2, :].sum()) / w if w > 0 else 0
    if center_shift > -0.05 and mid_row_fill > 0.3 and bot_fill > 0.5:
        return 3

    # "5": top-left + bottom-right pattern (center shifts left-to-right)
    if center_shift > 0.10 and top_fill > 0.5:
        return 5

    # Fallback: use center shift direction
    if center_shift < -0.05:
        return 2
    if center_shift > 0.05:
        return 5
    return 3


def analyze_badge(frame, ch_idx, ch_conf):
    fh, fw = frame.shape[:2]
    bx1 = int(BADGE_X_RANGE[0] * fw)
    bx2 = int(BADGE_X_RANGE[1] * fw)
    by_lo, by_hi = ch_conf["badge_y"]
    y1 = int(by_lo * fh)
    y2 = int(by_hi * fh)

    band = frame[y1:y2, bx1:bx2]
    if band.size == 0:
        return 0

    r_ch = band[:, :, 2].astype(np.float32)
    g_ch = band[:, :, 1].astype(np.float32)
    b_ch = band[:, :, 0].astype(np.float32)
    red_mask = (r_ch > 150) & (g_ch < 100) & (b_ch < 100)
    red_px = int(red_mask.sum())

    if red_px < 15:
        print(f"  ch{ch_idx+1}: 0")
        return 0

    circle = _find_badge_circle(red_mask)
    if circle is None:
        return 0

    cx, cy, cw, c_h, c_area = circle
    pad = 3
    cx1 = max(0, cx - pad)
    cy1 = max(0, cy - pad)
    cx2 = min(band.shape[1], cx + cw + pad)
    cy2 = min(band.shape[0], cy + c_h + pad)
    badge_crop = band[cy1:cy2, cx1:cx2]
    red_mask_crop = red_mask[cy1:cy2, cx1:cx2]

    digits = _extract_digits(badge_crop, red_mask_crop)
    if not digits:
        print(f"  ch{ch_idx+1}: ~5 (badge, no digits)")
        return 5

    print(f"  ch{ch_idx+1}: {len(digits)} digit(s)")
    number = 0
    for i, (dimg, dbbox, darea) in enumerate(digits):
        d = _classify_digit(dimg, dbbox, darea)
        print(f"    => {d}")
        number = number * 10 + d

    print(f"  ch{ch_idx+1}: => {number}")
    return number


def main():
    img_path = sys.argv[1] if len(sys.argv) > 1 else (
        r"C:\Users\LEGION\Pictures\Screenshots\Screenshot 2026-05-20 161330.png"
    )
    img = cv2.imread(img_path)
    if img is None:
        print(f"Cannot load: {img_path}")
        return

    print(f"Frame: {img.shape[1]}x{img.shape[0]}")

    results = []
    for i, ch_conf in enumerate(CHAT_CHANNELS):
        est = analyze_badge(img, i, ch_conf)
        results.append(est)

    print(f"\nResult: {'/'.join(str(r) for r in results)}")
    print(f"Expected: 0/19/29")


if __name__ == "__main__":
    main()
