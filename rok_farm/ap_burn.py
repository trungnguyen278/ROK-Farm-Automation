"""Spending action points on barbarians, through the game's own auto mode.

The operator asked for this on 2026-09-21, and the reason is not the points
themselves -- they said outright that spending them barely matters. It is that
an account which gathers sixty deposits a day and does nothing else all day is
an odd shape, and the anti-cheat letters have not been explained by anything
smaller. A day with real barbarian hunting in it looks less like a machine
with one job.

The flow, measured screen by screen with the operator watching each one:

  1. the world map's search button (magnifier, shortcut F), bottom right
  2. the search panel, which must be on the "Nguoi man ro" tab -- it sometimes
     opens on "Phao dai Barbaria", where the auto button does not exist
  3. the small round button beside TIM KIEM, which opens the game's own auto
  4. BAT DAU

Two of their warnings shape the rest of it:

  * the auto is a VIP feature and errors if pressed within two or three
    minutes of the client starting;
  * losing the network OR CLOSING THE CLIENT stops the run and sends the
    troops home.

That second one is not a problem to work around -- it is the brake. The farm
lets the auto run for a short random while, then quits the client, which both
ends the run and caps what it spends. "Dai dai di", as they put it: roughly is
fine, and they did not want much spent on barbarians anyway.
"""

from __future__ import annotations

import json
import time

import cv2
import numpy as np

from rok_farm import PROJECT_ROOT

# --- Where the buttons are -------------------------------------------------
# Fixed positions, as the operator confirmed they are. Measured on a 1533x862
# client and stored as fractions so a resize cannot move them.
#
# The search button was found independently on 8 saved world-map frames by
# looking for its gold ring: every one put the centre at (1488, 716), not a
# pixel of spread. The other three were measured once each, on the frame the
# step before opened, and checked by eye against a marked-up screenshot.
SEARCH_BTN_PCT = (0.9706, 0.8306)   # magnifier, bottom right of the world map
BARB_TAB_PCT = (0.2446, 0.5313)     # "Nguoi man ro" tab in the search panel
AUTO_BTN_PCT = (0.3718, 0.7587)     # small round button beside TIM KIEM
START_BTN_PCT = (0.4990, 0.7169)    # BAT DAU on the auto panel

# The active tab reads mean saturation 78 against the inactive one's 38, in a
# 110x28 patch centred on the tab. One sample of each so far, which is why the
# threshold sits midway rather than close to either.
TAB_ACTIVE_SAT = 55

# Blue fill of the auto button's own disc: 0.60 with the panel open,
# 0.00 with the map underneath.
AUTO_BTN_BLUE_MIN = 0.25

# --- Reading the bar -------------------------------------------------------
# The action-point bar is the green arc under the commander portrait, top left
# of the CITY view -- a shallow smile, filling left to right.
#
# It was first read by counting bright-green pixels in a box and dividing by
# 139, the count on a frame where the bar was full. The operator killed that
# measure on 2026-09-21: three city frames it scored 99%, 67%, 67% all looked
# full to them, and they were right. Two faults, both fatal:
#
#   * the gate was S>150 V>180, so when the scene lit differently the arc's
#     dimmer pixels dropped out. Under a looser gate the same three frames
#     read 154, 141, 141 -- and drawn as a mask they are the same arc, the
#     right tip 2px apart on a 52px span. The count was tracking the
#     LIGHTING, and 80% of the readings it fed were the wrong side of the
#     threshold that decides whether to spend.
#   * a count cannot tell a long thin arc from a short fat one, and it counts
#     anything green. On world-map frames, where that corner holds grass
#     instead of the portrait, it returned 44%, 96%, even 152% of "full".
#
# So measure the arc as an arc. Fitting a circle to the green of three full
# frames put the centre at (39.4, 27.4) with radius 34.4 and a spread of only
# 1.16px, and the sweep runs 138.2 degrees (left tip, empty) to 43.9 (right
# tip, full). Fill is how far round that sweep the green reaches -- an angle,
# which does not care how bright or how thick the arc is drawn.
#
# Measured on a 1533x862 client and left in absolute pixels: whether this HUD
# scales with the window is not something any saved frame can answer, so it is
# not assumed either way.
#
# The operator's cap is 1500 points, but no arithmetic here needs that: they
# asked for "80 or 90 percent, roughly", so the fraction of the sweep is the
# whole measurement.
AP_ARC_BAND = (30, 85, 0, 95)       # y1, y2, x1, x2 in client pixels
AP_ARC_CENTRE = (39.4, 27.4)        # x, y of the circle the arc lies on
AP_ARC_RADIUS = (31.0, 40.0)        # the ring the arc's pixels fall in
AP_ARC_SWEEP = (138.2, 43.9)        # degrees, empty end -> full end
AP_ARC_HUE = (40, 70)
AP_ARC_GATE = (90, 120)             # S, V minimums -- loose, on purpose
AP_ARC_STEP_DEG = 1.0
# A tip is anti-aliased away, so a bar the operator calls full reads ~99%.
# Two blank bins are forgiven before the arc is taken to have ended.
AP_ARC_GAP_BINS = 2

# Telling the arc from a hillside. Both of these separate cleanly on the eight
# city frames and six map frames kept under screenshots/keep/ap_arc:
#   radial spread  arc 1.16-1.76   grass 2.46-2.78
#   green inside   arc 0 every one grass 16-1039
# The second is the portrait's own disc, which is brown and gold and has no
# business being green.
AP_ARC_SPREAD_MAX = 2.1
AP_ARC_INNER_MAX = 8
AP_ARC_MIN_PX = 20

AP_BURN_AT = 0.80                   # spend when the arc is at least this full

# What the auto is allowed to send, and what actually limits it.
#
# The operator set the auto's own march count to FOUR. That is a ceiling, not
# a promise: "no phu thuoc vao 2 van de, 1 la con slot khong, 2 la luong quan
# san co co du tao ra march day hay khong". So a run sends up to four marches,
# bounded by free slots and by whether there are troops at home to fill them.
#
# Both bounds move during a run. A gathering march coming home frees its slot
# AND returns its troops, so a long dwell feeds the auto on both counts -- and
# the farm has five slots in total, so four of them is nearly all of it.
#
# Nothing here enforces the number; the game does. It is written down because
# every question about how long to dwell is really a question about how much
# of the march queue the barbarians may hold, and that starts here.
AP_AUTO_MARCHES = 4

# How long to leave the auto running before quitting ends it.
#
# The first cut was two to five minutes, and the operator watched it and said
# that is nowhere near enough: the farm can spare exactly ONE march slot, so
# the auto sends one army at a time and a few minutes barely dents the bar.
# Twenty-odd minutes is their number.
#
# It costs online time -- the client stays up throughout -- but only once in
# six hours, and the queue is full for that whole stretch anyway, so the farm
# would have been waiting for returns regardless. Randomised because a fixed
# dwell is a fingerprint of its own.
AP_DWELL_S = (900.0, 1500.0)
# What the client has to have been up for before the auto will run at all.
AP_WARMUP_S = 180.0
# And how long to stay out afterwards, so the recalled troops are home before
# farming resumes.
AP_AWAY_S = (270.0, 360.0)

# How long before trying again.
#
# This started at six hours, on the reasoning that the bar takes hours to
# refill so anything sooner must be a misreading. That was wrong twice over.
# The operator refills it from a potion, and -- as they pointed out after the
# first live run -- a run that ends early spends almost nothing, so the bar is
# still full afterwards and the six hours were forbidding exactly the retry
# that was called for.
#
# The bar itself is the evidence, so the gap only has to stop a tight loop.
# Randomised, because a fixed spacing between visits is its own pattern.
AP_MIN_GAP_S = (2400.0, 4800.0)

# If a run leaves the bar no lower than it found it, the auto is not actually
# spending anything -- worth saying out loud rather than quietly retrying.
AP_SPENT_EPS = 0.05
AP_STATE = PROJECT_ROOT / "data" / "ap_burn.json"


def _arc_pixels(frame):
    """Green pixels of the arc band, as (angle, radius, inside-count)."""
    y1, y2, x1, x2 = AP_ARC_BAND
    band = frame[y1:y2, x1:x2]
    if band.size == 0:
        return None
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    lo, hi = AP_ARC_HUE
    smin, vmin = AP_ARC_GATE
    mask = ((hsv[:, :, 0] >= lo) & (hsv[:, :, 0] <= hi) &
            (hsv[:, :, 1] > smin) & (hsv[:, :, 2] > vmin))
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    cx, cy = AP_ARC_CENTRE
    xs = xs.astype(float) + x1
    ys = ys.astype(float) + y1
    rad = np.hypot(xs - cx, ys - cy)
    rmin, rmax = AP_ARC_RADIUS
    on = (rad >= rmin) & (rad <= rmax)
    inside = int((rad < rmin - 3).sum())
    if not on.any():
        return None
    ang = np.degrees(np.arctan2(ys[on] - cy, xs[on] - cx))
    return ang, rad[on], inside


def arc_fill(frame) -> float:
    """How far the action-point arc has filled, 0.0 to 1.0, or -1.0 if there
    is no arc to read.

    Only the CITY view has one: on the world map that corner holds terrain,
    and the guards below exist because green terrain used to be read as a
    full bar.
    """
    if frame is None:
        return -1.0
    found = _arc_pixels(frame)
    if found is None:
        return -1.0
    ang, rad, inside = found
    if len(ang) < AP_ARC_MIN_PX:
        return -1.0
    if inside > AP_ARC_INNER_MAX or rad.std() > AP_ARC_SPREAD_MAX:
        return -1.0

    empty, full = AP_ARC_SWEEP
    bins = int(round((empty - full) / AP_ARC_STEP_DEG))
    edges = np.linspace(empty, full, bins + 1)
    reached, gap = 0, 0
    for i in range(bins):
        if ((ang <= edges[i]) & (ang > edges[i + 1])).any():
            reached, gap = i + 1, 0
        else:
            gap += 1
            if gap > AP_ARC_GAP_BINS:
                break
    if reached == 0:
        # Green on the ring, but none of it at the left tip. The bar fills
        # left to right, so a real one is never empty there while showing
        # elsewhere -- an empty bar has no green at all and was turned away by
        # the pixel count above. This is something else wearing the ring:
        # live at 16:00:43 on 2026-09-21 a frame caught during the client's
        # relaunch read 0% seven minutes after the same bar read 99%.
        return -1.0
    return reached / bins


def tab_saturation(frame, pct=BARB_TAB_PCT) -> float:
    """Mean saturation of a tab label: the active one is about twice the other."""
    if frame is None:
        return -1.0
    h, w = frame.shape[:2]
    x, y = int(w * pct[0]), int(h * pct[1])
    patch = frame[y - 14:y + 14, x - 55:x + 55]
    if patch.size == 0:
        return -1.0
    return float(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)[:, :, 1].mean())


def auto_button_visible(frame) -> bool:
    """Is the search panel open? The auto button is the cheapest tell.

    The search panel does not dim the map -- measured 1.10, where the modal
    check wants 1.8 -- so the usual "something covers the game" signal is no
    help here. The button's own blue disc is: 0.60 of that patch is blue with
    the panel open, 0.00 with the map underneath, on both frames checked.
    """
    if frame is None:
        return False
    h, w = frame.shape[:2]
    x, y = int(w * AUTO_BTN_PCT[0]), int(h * AUTO_BTN_PCT[1])
    patch = frame[y - 12:y + 12, x - 12:x + 12]
    if patch.size == 0:
        return False
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    blue = ((hsv[:, :, 0] >= 95) & (hsv[:, :, 0] <= 115) &
            (hsv[:, :, 1] > 120) & (hsv[:, :, 2] > 120)).mean()
    return bool(blue >= AUTO_BTN_BLUE_MIN)


def last_run() -> tuple[float, float]:
    """When the last run started, and how full the bar was then."""
    try:
        d = json.loads(AP_STATE.read_text(encoding="utf-8"))
        return float(d.get("last", 0.0)), float(d.get("fill", 0.0))
    except Exception:
        return 0.0, 0.0


def last_burn() -> float:
    return last_run()[0]


def note_burn(fill: float = 0.0) -> None:
    try:
        AP_STATE.parent.mkdir(parents=True, exist_ok=True)
        AP_STATE.write_text(json.dumps({"last": time.time(), "fill": fill}),
                            encoding="utf-8")
    except Exception:
        pass


def spent_nothing(fill_now: float) -> bool:
    """Did the last run leave the bar exactly where it found it?"""
    when, fill_then = last_run()
    if not when or fill_then <= 0:
        return False
    return fill_now >= fill_then - AP_SPENT_EPS


def due(fill: float, now: float | None = None,
        gap: float | None = None) -> bool:
    """Is the bar full enough, and has it been long enough since the last run?"""
    if fill < AP_BURN_AT:
        return False
    now = now if now is not None else time.time()
    if gap is None:
        import random
        gap = random.uniform(*AP_MIN_GAP_S)
    return now - last_burn() >= gap
