"""Detailed HSV analysis of gem icon samples, especially failed ones."""
import cv2
import numpy as np
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vision.color_filter import is_gem_icon_color

SAMPLES_DIR = "templates/resources/gem_icon_samples"


def analyze_sample(path):
    img = cv2.imread(path)
    h, w = img.shape[:2]
    is_gem, info = is_gem_icon_color(img, 0, 0, w, h)

    pad = int(w * 0.20)
    x1, y1, x2, y2 = pad, 0, w - pad, int(h * 0.60)
    region = img[y1:y2, x1:x2]

    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0]
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]

    print("  Size: %dx%d, Crystal: %dx%d" % (w, h, region.shape[1], region.shape[0]))
    print("  Filter: %s (green=%.1f%%, white=%.1f%%)" % (
        "PASS" if is_gem else "FAIL", info["green_pct"], info["white_pct"]))
    print("  Hue: min=%d max=%d mean=%.1f" % (hue.min(), hue.max(), hue.mean()))
    print("  Sat: min=%d max=%d mean=%.1f" % (sat.min(), sat.max(), sat.mean()))
    print("  Val: min=%d max=%d mean=%.1f" % (val.min(), val.max(), val.mean()))

    bins = [
        (0, 10, "red-low"),
        (10, 20, "orange"),
        (20, 30, "yellow"),
        (28, 52, "gem-green"),
        (52, 80, "cyan"),
        (150, 180, "red-high"),
    ]
    for lo, hi, label in bins:
        mask = (hue >= lo) & (hue < hi) & (sat >= 20) & (val >= 100)
        pct = mask.sum() / float(hue.size) * 100
        if pct > 1.0:
            print("  Hue %d-%d (%s): %.1f%%" % (lo, hi, label, pct))

    bright = (val >= 160).sum() / float(val.size) * 100
    very_bright = (val >= 200).sum() / float(val.size) * 100
    low_sat_bright = ((sat < 60) & (val >= 120)).sum() / float(sat.size) * 100
    print("  Bright(V>=160): %.1f%%, VeryBright(V>=200): %.1f%%, LowSat+Bright: %.1f%%" % (
        bright, very_bright, low_sat_bright))
    return is_gem, info


def main():
    files = sorted(os.listdir(SAMPLES_DIR))

    # Analyze ALL failed samples
    print("=== FAILED SAMPLES ===")
    for f in files:
        path = os.path.join(SAMPLES_DIR, f)
        img = cv2.imread(path)
        if img is None:
            continue
        h, w = img.shape[:2]
        is_gem, info = is_gem_icon_color(img, 0, 0, w, h)
        if not is_gem:
            print("\n%s:" % f)
            analyze_sample(path)

    # Analyze borderline PASS (green < 45%)
    print("\n=== BORDERLINE PASS (green < 45%) ===")
    for f in files:
        path = os.path.join(SAMPLES_DIR, f)
        img = cv2.imread(path)
        if img is None:
            continue
        h, w = img.shape[:2]
        is_gem, info = is_gem_icon_color(img, 0, 0, w, h)
        if is_gem and info["green_pct"] < 45.0:
            print("\n%s:" % f)
            analyze_sample(path)


if __name__ == "__main__":
    main()
