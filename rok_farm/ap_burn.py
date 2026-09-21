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
# of the CITY view. Counting its bright-green pixels in a fixed band is enough:
# over 60 saved city frames the count sat at 138-139 in 55 of them (the bar
# pinned at full) and near 98-100 in the few where it was not.
#
# The operator's cap is 1500 points, but no arithmetic here needs that: they
# asked for "80 or 90 percent, roughly", so the fraction of a full arc is the
# whole measurement.
AP_ARC_BAND = (40, 72, 2, 80)       # y1, y2, x1, x2 in client pixels
AP_ARC_FULL_PX = 139.0
AP_BURN_AT = 0.80                   # spend when the arc is at least this full

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

# Never twice in the same stretch of a day. The bar takes hours to refill, so
# this is a backstop against a misread rather than a real limit.
AP_MIN_GAP_S = 6 * 3600.0
AP_STATE = PROJECT_ROOT / "data" / "ap_burn.json"


def arc_fill(frame) -> float:
    """How full the action-point arc is, 0.0 to 1.0, or -1.0 if unreadable.

    Only meaningful on a CITY frame: on the world map that corner holds the
    coordinate readout instead of the portrait.
    """
    if frame is None:
        return -1.0
    y1, y2, x1, x2 = AP_ARC_BAND
    band = frame[y1:y2, x1:x2]
    if band.size == 0:
        return -1.0
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    green = ((hsv[:, :, 0] >= 40) & (hsv[:, :, 0] <= 70) &
             (hsv[:, :, 1] > 150) & (hsv[:, :, 2] > 180)).sum()
    return float(green) / AP_ARC_FULL_PX


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


def last_burn() -> float:
    try:
        return float(json.loads(AP_STATE.read_text(encoding="utf-8"))["last"])
    except Exception:
        return 0.0


def note_burn() -> None:
    try:
        AP_STATE.parent.mkdir(parents=True, exist_ok=True)
        AP_STATE.write_text(json.dumps({"last": time.time()}), encoding="utf-8")
    except Exception:
        pass


def due(fill: float, now: float | None = None) -> bool:
    """Is the bar full enough, and has it been long enough since the last run?"""
    if fill < AP_BURN_AT:
        return False
    now = now if now is not None else time.time()
    return now - last_burn() >= AP_MIN_GAP_S
