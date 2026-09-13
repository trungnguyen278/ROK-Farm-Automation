"""Collect the resource bubbles in the city -- only on the way out of the client.

Every production building in the city grows a bubble when it has something to
collect, and a tap on the bubble takes it. There are five kinds: food, stone,
wood, gold, and an orange crystal the operator says exists only on the KvK map.

The templates in templates/city/ were cut by the operator from frames the bot
itself saved -- two matched their source at exactly 1.000 -- and those frames
come from _grab(), the same call the harvest uses at run time, night
normalisation included. So there is no scale to sweep and no lighting to
correct for: the templates look the way the live frame looks.

MEASURED on four saved city frames (2026-09-13, two by day, two at night; 20
bubbles each by eye), matching the maximum over all ten templates at scale 1.0:

    every unobstructed bubble        0.826 or higher, in all four frames
    a wood bubble under a UI label   0.756
    a crystal under a text banner    0.657
    the quest scroll                 0.641   <- NOT a bubble; opens a panel
    an alliance shield on a building 0.550   <- NOT a bubble

The quest scroll sits 0.016 under an obstructed real bubble, so nothing
separates "obstructed" from "wrong". What does separate is unobstructed-real
(>= 0.826) from everything else (<= 0.756), and that is where the threshold
goes. A bubble hidden behind a label is missed this time and collected on the
next exit; a tap on the quest scroll opens a panel. Misses are cheap, wrong
taps are not.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from rok_farm import PROJECT_ROOT

HARVEST_DIR = PROJECT_ROOT / "templates" / "city"
HARVEST_KINDS = ("food", "stone", "wood", "gold", "kvk")
HARVEST_THRESHOLD = 0.80
# Bubbles are ~45px wide and sit at least ~70px apart, so two peaks closer than
# this are the same bubble answering to two templates.
HARVEST_NMS_PX = 30
# A city has 20 production bubbles at most in the frames seen so far. A frame
# claiming far more is not a city full of bubbles, it is a detector gone wrong,
# and the cap stops that turning into a click storm.
HARVEST_MAX_CLICKS = 30
# The next tap goes to one of this many untapped bubbles nearest the last one.
HARVEST_NEAREST = 3


@dataclass(frozen=True)
class Bubble:
    x: int
    y: int
    score: float
    kind: str


def load_harvest_templates(folder: Path | None = None) -> list[tuple[str, np.ndarray]]:
    """(kind, image) for every harvest_<condition>_<kind>.png in the folder."""
    folder = HARVEST_DIR if folder is None else folder
    out: list[tuple[str, np.ndarray]] = []
    for path in sorted(folder.glob("harvest_*_*.png")):
        kind = path.stem.rsplit("_", 1)[-1]
        if kind not in HARVEST_KINDS:
            continue
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is not None:
            out.append((kind, img))
    return out


def find_harvest_bubbles(frame, templates, threshold: float = HARVEST_THRESHOLD,
                         nms_px: int = HARVEST_NMS_PX) -> list[Bubble]:
    """Every bubble on the frame, strongest first.

    Responses from all templates are laid on one map anchored at each
    template's CENTRE -- they differ by a few pixels in size, and anchoring at
    the corner would put the same bubble at slightly different places -- and
    the best template at each pixel names the kind.
    """
    if frame is None or not templates:
        return []
    fh, fw = frame.shape[:2]
    best = np.full((fh, fw), -1.0, np.float32)
    who = np.full((fh, fw), -1, np.int16)
    for idx, (_, tmpl) in enumerate(templates):
        th, tw = tmpl.shape[:2]
        if th >= fh or tw >= fw:
            continue
        res = cv2.matchTemplate(frame, tmpl, cv2.TM_CCOEFF_NORMED)
        y0, x0 = th // 2, tw // 2
        region = best[y0:y0 + res.shape[0], x0:x0 + res.shape[1]]
        owner = who[y0:y0 + res.shape[0], x0:x0 + res.shape[1]]
        better = res > region
        region[better] = res[better]
        owner[better] = idx

    ys, xs = np.where(best >= threshold)
    order = np.argsort(-best[ys, xs])
    kept: list[Bubble] = []
    for i in order:
        x, y = int(xs[i]), int(ys[i])
        if all((x - b.x) ** 2 + (y - b.y) ** 2 > nms_px ** 2 for b in kept):
            kept.append(Bubble(x, y, float(best[y, x]),
                               templates[int(who[y, x])][0]))
    return kept


def _near(a: Bubble, b: Bubble, px: int) -> bool:
    return (a.x - b.x) ** 2 + (a.y - b.y) ** 2 <= px ** 2


def untapped(bubbles, tapped, px: int = HARVEST_NMS_PX) -> list[Bubble]:
    """The bubbles that no earlier tap landed on."""
    return [b for b in bubbles if not any(_near(b, t, px) for t in tapped)]


def still_there(bubbles, target: Bubble, px: int = HARVEST_NMS_PX) -> Bubble | None:
    """The bubble showing at the spot just tapped, if there is one."""
    return next((b for b in bubbles if _near(b, target, px)), None)


def pick_next(candidates, last: Bubble | None, rng) -> Bubble:
    """One of the few bubbles nearest the last tap -- any of them for the first.

    A hand sweeps across the city. Jumping at random between far corners is
    not how a thumb moves, and always taking THE nearest would walk the same
    path through the same buildings on every exit.
    """
    if last is None:
        return rng.choice(list(candidates))
    ranked = sorted(candidates,
                    key=lambda b: (b.x - last.x) ** 2 + (b.y - last.y) ** 2)
    return rng.choice(ranked[:HARVEST_NEAREST])
