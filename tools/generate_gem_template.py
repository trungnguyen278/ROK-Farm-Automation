"""Generate improved gem_icon template from collected samples.

Approaches:
1. Pick most representative sample (highest avg cross-correlation with others)
2. Average all samples (resize to common size, pixel-mean)
3. Crop crystal-only region (exclude pedestal/number common to all resource types)

Usage:
    python -m tools.generate_gem_template [--method best|average|crystal]
"""

import argparse
import cv2
import numpy as np
import os
import sys

SAMPLES_DIR = "templates/resources/gem_icon_samples"
OUTPUT_DIR = "templates/resources"
CURRENT_TEMPLATE = "templates/resources/gem_icon.png"


def load_samples():
    samples = []
    for f in sorted(os.listdir(SAMPLES_DIR)):
        path = os.path.join(SAMPLES_DIR, f)
        img = cv2.imread(path)
        if img is not None:
            samples.append((f, img))
    return samples


def find_most_representative(samples):
    """Find sample with highest average TM_CCOEFF_NORMED against all others."""
    n = len(samples)
    scores = np.zeros(n)

    for i, (name_i, img_i) in enumerate(samples):
        for j, (name_j, img_j) in enumerate(samples):
            if i == j:
                continue
            th, tw = img_i.shape[:2]
            sh, sw = img_j.shape[:2]
            if th > sh or tw > sw:
                scale = min(sh / th, sw / tw) * 0.95
                resized = cv2.resize(img_i, None, fx=scale, fy=scale)
            else:
                resized = img_i
            rh, rw = resized.shape[:2]
            if rh > sh or rw > sw:
                continue
            result = cv2.matchTemplate(img_j, resized, cv2.TM_CCOEFF_NORMED)
            scores[i] += result.max()

    scores /= (n - 1)
    ranking = np.argsort(scores)[::-1]

    print("Cross-correlation ranking:")
    for rank, idx in enumerate(ranking):
        name, img = samples[idx]
        h, w = img.shape[:2]
        print(f"  {rank+1}. {name} ({w}x{h}) avg_score={scores[idx]:.4f}")

    best_idx = ranking[0]
    return samples[best_idx]


def create_average_template(samples, target_size=(50, 55)):
    """Resize all samples to common size and average pixels."""
    tw, th = target_size
    accumulated = np.zeros((th, tw, 3), dtype=np.float64)

    for name, img in samples:
        resized = cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)
        accumulated += resized.astype(np.float64)

    averaged = (accumulated / len(samples)).astype(np.uint8)
    return averaged


def crop_crystal_region(img):
    """Crop top portion of icon (crystal) excluding bottom pedestal/number.

    The pedestal with level number is common to ALL resource types.
    The crystal shape/color is what distinguishes gem from wood/stone/gold.
    """
    h, w = img.shape[:2]
    cut_bottom = int(h * 0.30)
    crystal = img[:h - cut_bottom, :, :]
    return crystal


def test_template_against_samples(template, samples, label=""):
    """Test a template against all samples, report confidence."""
    th, tw = template.shape[:2]
    confs = []
    for name, img in samples:
        sh, sw = img.shape[:2]
        if th > sh or tw > sw:
            continue
        result = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
        conf = result.max()
        confs.append(conf)

    if confs:
        arr = np.array(confs)
        print(f"  {label}: min={arr.min():.4f} max={arr.max():.4f} "
              f"mean={arr.mean():.4f} std={arr.std():.4f} (n={len(confs)})")
    return confs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", choices=["best", "average", "crystal", "all"],
                        default="all")
    parser.add_argument("--save", action="store_true",
                        help="Save generated templates to output dir")
    args = parser.parse_args()

    samples = load_samples()
    if not samples:
        print(f"No samples found in {SAMPLES_DIR}")
        return

    print(f"Loaded {len(samples)} samples\n")

    current = cv2.imread(CURRENT_TEMPLATE)
    if current is not None:
        ch, cw = current.shape[:2]
        print(f"Current template: {cw}x{ch}")
        test_template_against_samples(current, samples, "current gem_icon")
        print()

    methods = [args.method] if args.method != "all" else ["best", "average", "crystal"]
    results = {}

    if "best" in methods:
        print("=== Method 1: Most representative sample ===")
        best_name, best_img = find_most_representative(samples)
        bh, bw = best_img.shape[:2]
        print(f"\nBest: {best_name} ({bw}x{bh})")
        test_template_against_samples(best_img, samples, "best-sample")
        results["gem_icon_best"] = best_img
        print()

    if "average" in methods:
        print("=== Method 2: Averaged template ===")
        median_w = int(np.median([s[1].shape[1] for s in samples]))
        median_h = int(np.median([s[1].shape[0] for s in samples]))
        print(f"Target size: {median_w}x{median_h} (median of samples)")
        avg_img = create_average_template(samples, (median_w, median_h))
        test_template_against_samples(avg_img, samples, "averaged")
        results["gem_icon_avg"] = avg_img
        print()

    if "crystal" in methods:
        print("=== Method 3: Crystal-only crop (no pedestal) ===")
        if "best" in results:
            source = results.get("gem_icon_best")
            source_label = "best sample"
        elif current is not None:
            source = current
            source_label = "current template"
        else:
            source = samples[0][1]
            source_label = samples[0][0]

        crystal = crop_crystal_region(source)
        crh, crw = crystal.shape[:2]
        print(f"Crystal crop from {source_label}: {crw}x{crh}")
        test_template_against_samples(crystal, samples, "crystal-only")
        results["gem_icon_crystal"] = crystal

        if current is not None:
            crystal_curr = crop_crystal_region(current)
            cch, ccw = crystal_curr.shape[:2]
            print(f"Crystal crop from current template: {ccw}x{cch}")
            test_template_against_samples(crystal_curr, samples, "crystal-current")
            results["gem_icon_crystal_curr"] = crystal_curr
        print()

    if args.save and results:
        print("=== Saving templates ===")
        for name, img in results.items():
            path = os.path.join(OUTPUT_DIR, f"{name}.png")
            cv2.imwrite(path, img)
            h, w = img.shape[:2]
            print(f"  Saved: {path} ({w}x{h})")

        print("\nNext steps:")
        print("  1. Pick the best template and rename to gem_icon.png")
        print("  2. Test with: python -m tools.test_gem_farm_flow --count 1 --find-only")
        print("  3. Compare false-positive rate on wood/stone/gold nodes")


if __name__ == "__main__":
    main()
