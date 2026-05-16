"""Compare gem_icon template candidates on all samples.

Tests each candidate template against every sample that's large enough,
reports min/max/mean confidence and match count.
"""
import cv2
import numpy as np
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SAMPLES_DIR = "templates/resources/gem_icon_samples"

CANDIDATES = {
    "current (57x62)": "templates/resources/gem_icon.png",
    "best #1 (36x48)": "templates/resources/gem_icon_samples/Screenshot 2026-05-16 111537.png",
    "best #2 (43x51)": "templates/resources/gem_icon_samples/Screenshot 2026-05-16 111451.png",
    "best #3 (43x55)": "templates/resources/gem_icon_samples/Screenshot 2026-05-16 114604.png",
    "best #4 (46x58)": "templates/resources/gem_icon_samples/Screenshot 2026-05-16 114631.png",
}


def test_candidate(template, samples):
    th, tw = template.shape[:2]
    confs = []
    matched = []
    skipped = []
    for name, img in samples:
        sh, sw = img.shape[:2]
        if th > sh or tw > sw:
            skipped.append(name)
            continue
        result = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
        conf = float(result.max())
        confs.append(conf)
        matched.append((name, conf))
    return confs, matched, skipped


def main():
    files = sorted(os.listdir(SAMPLES_DIR))
    samples = []
    for f in files:
        path = os.path.join(SAMPLES_DIR, f)
        img = cv2.imread(path)
        if img is not None:
            samples.append((f, img))

    print("Samples: %d" % len(samples))
    print("Sample sizes: %s" % ", ".join(
        "%dx%d" % (s[1].shape[1], s[1].shape[0]) for s in samples[:5]))
    print()

    for label, path in CANDIDATES.items():
        template = cv2.imread(path)
        if template is None:
            print("%s: FILE NOT FOUND" % label)
            continue

        th, tw = template.shape[:2]
        confs, matched, skipped = test_candidate(template, samples)

        if confs:
            arr = np.array(confs)
            above_80 = (arr >= 0.80).sum()
            above_85 = (arr >= 0.85).sum()
            print("%s (%dx%d):" % (label, tw, th))
            print("  Matched: %d/%d (skipped %d too small)" % (
                len(matched), len(samples), len(skipped)))
            print("  Conf: min=%.4f max=%.4f mean=%.4f std=%.4f" % (
                arr.min(), arr.max(), arr.mean(), arr.std()))
            print("  >= 0.80: %d/%d (%.0f%%)" % (
                above_80, len(confs), above_80 / len(confs) * 100))
            print("  >= 0.85: %d/%d (%.0f%%)" % (
                above_85, len(confs), above_85 / len(confs) * 100))

            low = [(n, c) for n, c in matched if c < 0.80]
            if low:
                print("  Low confidence (<0.80):")
                for n, c in sorted(low, key=lambda x: x[1]):
                    print("    %.4f %s" % (c, n))
        else:
            print("%s: no matches (template bigger than all samples)" % label)
        print()


if __name__ == "__main__":
    main()
