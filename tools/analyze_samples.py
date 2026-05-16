"""Analyze all gem icon samples against current color filter."""
import cv2
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vision.color_filter import is_gem_icon_color

SAMPLES_DIR = "templates/resources/gem_icon_samples"


def main():
    files = sorted(os.listdir(SAMPLES_DIR))
    print("Total samples: %d\n" % len(files))

    pass_count = 0
    fail_count = 0
    results = []

    for f in files:
        path = os.path.join(SAMPLES_DIR, f)
        img = cv2.imread(path)
        if img is None:
            print("  SKIP (unreadable): %s" % f)
            continue
        h, w = img.shape[:2]
        is_gem, info = is_gem_icon_color(img, 0, 0, w, h)
        status = "PASS" if is_gem else "FAIL"
        if is_gem:
            pass_count += 1
        else:
            fail_count += 1
        results.append((f, is_gem, info, w, h))
        print("  %s: %s (%dx%d) green=%.1f%% white=%.1f%% bright=%.1f%% hue_max=%d [%s]" % (
            status, f, w, h, info["green_pct"], info["white_pct"],
            info.get("bright_pct", 0), info.get("max_hue", 0), info["reason"]))

    total = pass_count + fail_count
    print("\nSummary: %d PASS / %d FAIL out of %d samples" % (pass_count, fail_count, total))
    print("Pass rate: %.1f%%" % (pass_count / total * 100))

    greens = np.array([r[2]["green_pct"] for r in results])
    whites = np.array([r[2]["white_pct"] for r in results])
    print("\nGreen pct: min=%.1f max=%.1f mean=%.1f std=%.1f" % (
        greens.min(), greens.max(), greens.mean(), greens.std()))
    print("White pct: min=%.1f max=%.1f mean=%.1f std=%.1f" % (
        whites.min(), whites.max(), whites.mean(), whites.std()))

    pass_greens = [r[2]["green_pct"] for r in results if r[1]]
    fail_greens = [r[2]["green_pct"] for r in results if not r[1]]
    if pass_greens:
        pg = np.array(pass_greens)
        print("PASS green: min=%.1f max=%.1f mean=%.1f" % (pg.min(), pg.max(), pg.mean()))
    if fail_greens:
        fg = np.array(fail_greens)
        print("FAIL green: min=%.1f max=%.1f mean=%.1f" % (fg.min(), fg.max(), fg.mean()))

    # Show sizes distribution
    sizes = [(r[3], r[4]) for r in results]
    ws = [s[0] for s in sizes]
    hs = [s[1] for s in sizes]
    print("\nSizes: width %d-%d, height %d-%d" % (min(ws), max(ws), min(hs), max(hs)))


if __name__ == "__main__":
    main()
