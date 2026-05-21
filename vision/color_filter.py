from __future__ import annotations

import cv2
import numpy as np


# --- Day/Night normalization ---
# ROK map has a day/night cycle that shifts terrain brightness.
# Linear V-scaling preserves pixel patterns for template matching.
# (CLAHE distorts local contrast which breaks template matching.)
NIGHT_BRIGHTNESS_THRESH = 90
DAY_TARGET_BRIGHTNESS = 130


def estimate_terrain_brightness(frame: np.ndarray) -> float:
    """Sample median brightness from the center band of the frame (avoids UI)."""
    fh, fw = frame.shape[:2]
    y1 = int(fh * 0.3)
    y2 = int(fh * 0.7)
    x1 = int(fw * 0.2)
    x2 = int(fw * 0.8)
    roi = frame[y1:y2, x1:x2]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    return float(np.median(gray))


def normalize_frame(frame: np.ndarray) -> tuple[np.ndarray, bool]:
    """Normalize frame brightness if night-time detected.

    Returns (normalized_frame, is_night).
    Day frames pass through unchanged.
    Uses linear V-scaling (not CLAHE) to preserve template matching patterns.
    """
    brightness = estimate_terrain_brightness(frame)
    is_night = brightness < NIGHT_BRIGHTNESS_THRESH

    if not is_night:
        return frame, False

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)

    scale = min(DAY_TARGET_BRIGHTNESS / max(brightness, 1.0), 3.0)
    v_scaled = np.clip(v.astype(np.float32) * scale, 0, 255).astype(np.uint8)

    s_boost = min(1.0 + (1.0 - brightness / DAY_TARGET_BRIGHTNESS) * 0.4, 1.5)
    s_scaled = np.clip(s.astype(np.float32) * s_boost, 0, 255).astype(np.uint8)

    out = cv2.merge([h, s_scaled, v_scaled])
    return cv2.cvtColor(out, cv2.COLOR_HSV2BGR), True


# Gem crystal has H ~38 (green) in HSV. Wood ~15 (brown), gold ~25 (yellow).
# On alliance territory the map tint affects background but crystal keeps its color.
GEM_HUE_MIN = 28
GEM_HUE_MAX = 52
GEM_SAT_MIN = 15
GEM_VAL_MIN = 100

# Crystal = top 60% of icon, center 60% width (excludes background edges)
CRYSTAL_TOP_RATIO = 0.60
CRYSTAL_SIDE_PAD = 0.20

# Thresholds: green is the primary discriminant.
# White is a fallback for tinted-territory gems where green is suppressed.
# Bright+hue is a second fallback for extreme red territory where both fail.
GREEN_PCT_THRESHOLD = 30.0
WHITE_PCT_THRESHOLD = 45.0
WHITE_VAL_MIN = 180
WHITE_SAT_MAX = 80

# Fallback for red-territory gems: crystal stays bright, max hue reaches green range.
# Wood max hue ~15, gold ~25, gem ~38 even when red-tinted.
BRIGHT_PCT_THRESHOLD = 70.0
BRIGHT_VAL_MIN = 120
BRIGHT_HUE_MIN = 30

# Gold rejection: gold crystals have H 12-27 (yellow-orange range).
# If gold pixels dominate over green, it's a gold mine icon, not gem.
GOLD_HUE_MIN = 12
GOLD_HUE_MAX = 27
GOLD_PCT_REJECT = 20.0


def is_gem_icon_color(
    frame: np.ndarray, x: int, y: int, w: int, h: int
) -> tuple[bool, dict]:
    """Check if a matched region has gem-like color (vs wood/stone/gold).

    Analyzes the crystal body (top-center of icon) for green-tinted pixels.
    Background territory tint (red/blue alliance) affects edges but crystal
    retains distinctive green facets.

    Returns (is_gem, info_dict) where info_dict has green_pct, gold_pct,
    white_pct, and which check passed.
    """
    fh, fw = frame.shape[:2]
    x1 = max(0, x + int(w * CRYSTAL_SIDE_PAD))
    y1 = max(0, y)
    x2 = min(fw, x + w - int(w * CRYSTAL_SIDE_PAD))
    y2 = min(fh, y + int(h * CRYSTAL_TOP_RATIO))

    region = frame[y1:y2, x1:x2]
    if region.size == 0:
        return False, {"green_pct": 0, "gold_pct": 0, "white_pct": 0, "reason": "empty"}

    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0]
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    total = float(hue.size)

    green_mask = (
        (hue >= GEM_HUE_MIN) & (hue <= GEM_HUE_MAX)
        & (sat >= GEM_SAT_MIN) & (val >= GEM_VAL_MIN)
    )
    green_pct = float(green_mask.sum()) / total * 100.0

    white_mask = (val >= WHITE_VAL_MIN) & (sat <= WHITE_SAT_MAX)
    white_pct = float(white_mask.sum()) / total * 100.0

    gold_mask = (
        (hue >= GOLD_HUE_MIN) & (hue <= GOLD_HUE_MAX)
        & (sat >= GEM_SAT_MIN) & (val >= GEM_VAL_MIN)
    )
    gold_pct = float(gold_mask.sum()) / total * 100.0

    bright_mask = val >= BRIGHT_VAL_MIN
    bright_pct = float(bright_mask.sum()) / total * 100.0
    max_hue = int(hue.max())

    info = {
        "green_pct": round(green_pct, 1),
        "gold_pct": round(gold_pct, 1),
        "white_pct": round(white_pct, 1),
        "bright_pct": round(bright_pct, 1),
        "max_hue": max_hue,
    }

    # Terrain noise: solid green with no white crystal = grass, not icon
    if green_pct >= 95 and white_pct < 5:
        info["reason"] = "terrain_noise"
        return False, info

    # Early reject: gold pixels dominate over green
    if gold_pct >= GOLD_PCT_REJECT and gold_pct > green_pct:
        info["reason"] = "gold_reject"
        return False, info

    # Primary: clear green presence
    if green_pct >= GREEN_PCT_THRESHOLD:
        info["reason"] = "green"
        return True, info

    # Borderline green (15-30%) but clearly not gold
    if green_pct >= 15 and gold_pct < 10:
        info["reason"] = "green_borderline"
        return True, info

    # White fallback: reject if also gold-tinted
    if white_pct >= WHITE_PCT_THRESHOLD:
        if gold_pct >= 15:
            info["reason"] = "white_but_gold"
            return False, info
        info["reason"] = "white"
        return True, info

    # Bright+hue fallback for red-territory gems
    if bright_pct >= BRIGHT_PCT_THRESHOLD and max_hue >= BRIGHT_HUE_MIN:
        info["reason"] = "bright+hue"
        return True, info

    info["reason"] = (
        "reject (green=%.0f%% < %.0f%%, gold=%.0f%%, white=%.0f%% < %.0f%%, "
        "bright=%.0f%%/hue=%d)"
        % (green_pct, GREEN_PCT_THRESHOLD, gold_pct,
           white_pct, WHITE_PCT_THRESHOLD, bright_pct, max_hue)
    )
    return False, info


def is_gem_mine_color(
    frame: np.ndarray, x: int, y: int, w: int, h: int
) -> tuple[bool, dict]:
    """Verify zoomed-in mine structure is gem (green/teal) not gold (yellow).

    Used as post-zoom confirmation after template match finds a mine.
    Checks the center 70% of the match area for dominant hue.
    """
    fh, fw = frame.shape[:2]
    pad_x = int(w * 0.15)
    pad_y = int(h * 0.15)
    rx1 = max(0, x + pad_x)
    ry1 = max(0, y + pad_y)
    rx2 = min(fw, x + w - pad_x)
    ry2 = min(fh, y + h - pad_y)

    region = frame[ry1:ry2, rx1:rx2]
    if region.size == 0:
        return True, {"reason": "empty_pass"}

    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0]
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    total = float(hue.size)

    colored = (sat >= 25) & (val >= 80)
    gem_hue = colored & (hue >= 28) & (hue <= 85)
    gold_hue = colored & (hue >= 12) & (hue <= 27)

    gem_pct = float(gem_hue.sum()) / total * 100.0
    gold_pct = float(gold_hue.sum()) / total * 100.0

    info = {"gem_pct": round(gem_pct, 1), "gold_pct": round(gold_pct, 1)}

    if gold_pct > gem_pct * 3 and gold_pct > 40:
        info["reason"] = "gold_mine"
        return False, info

    info["reason"] = "gem_ok"
    return True, info
