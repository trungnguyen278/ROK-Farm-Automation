"""Human-like idle/distraction actions for anti-detection.

Each action is a standalone function that receives a `ctx` object
(anything that exposes the helpers listed in PlayerActionCtx).
This keeps actions testable independently of the farm flow.

Usage from GemFarmFlowTest:
    from anti_detection.player_actions import PlayerActions
    self._actions = PlayerActions(self, persona)
    self._actions.maybe_distract("after_march")

Standalone test:
    .venv\\Scripts\\python -m anti_detection.player_actions --port COM27 --list
    .venv\\Scripts\\python -m anti_detection.player_actions --port COM27 --action pan
    .venv\\Scripts\\python -m anti_detection.player_actions --port COM27 --action pan,zoom,stare
    .venv\\Scripts\\python -m anti_detection.player_actions --port COM27 --random 5
    .venv\\Scripts\\python -m anti_detection.player_actions --port COM27 --all
"""

from __future__ import annotations

import logging
import math
import os
import random
import time
from typing import Protocol, runtime_checkable

import cv2
import numpy as np

logger = logging.getLogger(__name__)

INFO = "\033[94mINFO\033[0m"


# ---------------------------------------------------------------------------
# Context protocol -- anything that provides these methods can host actions
# ---------------------------------------------------------------------------

@runtime_checkable
class PlayerActionCtx(Protocol):
    win: dict

    def _center_screen(self) -> tuple[int, int]: ...
    def _clamp_to_play_area(self, sx: int, sy: int) -> tuple[int, int]: ...
    def _moveto(self, sx: int, sy: int) -> bool: ...
    def _click(self, sx: int, sy: int, hold_ms: int = 0) -> bool: ...
    def _click_pct(self, pct_x: float, pct_y: float, jitter_px: int = 10): ...
    def _human_drag(self, sx: int, sy: int, ex: int, ey: int,
                    button: str = "L", speed_factor: float = 1.0,
                    easing: str = "in_out"): ...
    def _scroll_at_center(self, amount: int, count: int = 1): ...
    def _press_escape(self): ...
    def _wait(self, spec, variance: float = 0.0) -> float: ...
    def _find(self, template: str, threshold: float = 0.65): ...
    def _close_panel(self, panel: str): ...

    @property
    def cmd(self): ...


# ---------------------------------------------------------------------------
# Layout constants (relative to game window)
# ---------------------------------------------------------------------------

BTN_POS = {
    "bag":      (0.755, 0.953),
    "alliance": (0.803, 0.953),
    "mail":     (0.898, 0.953),
    "events":   (0.898, 0.090),
}

PANEL_ITEMS = {
    "bag": [
        (0.12, 0.187), (0.24, 0.187), (0.36, 0.187),
        (0.48, 0.187), (0.60, 0.187), (0.72, 0.187),
    ],
    "alliance": [
        (0.38, 0.52), (0.48, 0.52), (0.58, 0.52), (0.68, 0.52), (0.78, 0.52),
        (0.38, 0.72), (0.48, 0.72), (0.58, 0.72), (0.68, 0.72), (0.78, 0.72),
    ],
}

MAIL_TAB_TEMPLATES = [
    {"name": "personal", "template": "ui/mail_tab_personal"},
    {"name": "reports",  "template": "ui/mail_tab_reports"},
    {"name": "alliance", "template": "ui/mail_tab_alliance"},
    {"name": "system",   "template": "ui/mail_tab_system"},
]

X_CLOSE_POS = {
    "bag":      (0.865, 0.187),
    "alliance": (0.765, 0.233),
    "events":   (0.817, 0.086),
}

DELAY_AFTER_ESCAPE = (0.18, 0.07)
DELAY_AFTER_DISMISS = (0.4, 0.15)
TITLE_BAR_H = 40
_DEBUG_BADGES = False


def _dismiss_panel(ctx):
    """Close any open panel by clicking an empty area of the game map.
    Never use ESC -- it opens the profile panel when nothing is open."""
    rx = random.uniform(0.82, 0.92)
    ry = random.uniform(0.35, 0.55)
    ctx._click_pct(rx, ry, jitter_px=8)
    ctx._wait(DELAY_AFTER_DISMISS)

_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
_tmpl_cache: dict[str, np.ndarray | None] = {}


def _load_tmpl(name: str) -> np.ndarray | None:
    if name in _tmpl_cache:
        return _tmpl_cache[name]
    path = os.path.join(_TEMPLATE_DIR, f"{name}.png")
    img = cv2.imread(path)
    if img is None:
        logger.warning("Template not found: %s", path)
    _tmpl_cache[name] = img
    return img


def _match_on_frame(frame, template_name: str, threshold: float = 0.65,
                    roi=None, scales=None):
    """Match template on a pre-captured frame.

    roi: optional (y1_pct, y2_pct) to restrict vertical search area.
    Returns (pct_x, pct_y, confidence, tmpl_w, tmpl_h) or None.
    Coordinates are always relative to the full frame.
    """
    tmpl = _load_tmpl(template_name)
    if tmpl is None:
        return None
    fh, fw = frame.shape[:2]
    y_off = 0
    search = frame
    if roi:
        ry1 = int(roi[0] * fh)
        ry2 = int(roi[1] * fh)
        search = frame[ry1:ry2, :]
        y_off = ry1
    sh, sw = search.shape[:2]
    best_val = 0.0
    best_center = None
    for scale in (scales or [0.8, 0.9, 1.0, 1.1, 1.2]):
        resized = cv2.resize(tmpl, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        rh, rw = resized.shape[:2]
        if rw > sw or rh > sh:
            continue
        result = cv2.matchTemplate(search, resized, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val > best_val:
            best_val = max_val
            best_center = (max_loc[0] + rw // 2, max_loc[1] + y_off + rh // 2, rw, rh)
    if best_val < threshold or best_center is None:
        return None
    cx, cy, tw, th = best_center
    return (cx / fw, cy / fh, best_val, tw, th)

# All registered action names
CITY_ONLY = {"bag", "events"}
WORLD_ONLY = {"peek_poi", "check_troops", "scout_fog"}
ANYWHERE = {"pan", "zoom", "stare", "hesitate", "misclick", "alt_tab",
            "idle_drag", "micro_afk", "mail", "alliance", "chat"}

ALL_ACTIONS = CITY_ONLY | WORLD_ONLY | ANYWHERE


# ---------------------------------------------------------------------------
# Individual action implementations
# ---------------------------------------------------------------------------

def act_mail(ctx: PlayerActionCtx):
    print(f"  [{INFO}] Distraction: checking mail")

    frame = _grab_chat_frame(ctx)
    if not _mail_btn_has_badge(frame):
        print("    mail icon has no badge, skipping")
        return

    ctx._click_pct(*BTN_POS["mail"])
    time.sleep(random.uniform(1.5, 3.0))

    frame = _grab_chat_frame(ctx)
    if frame is None:
        print("    no frame, aborting mail")
        _dismiss_panel(ctx)
        return

    if _DEBUG_BADGES:
        cv2.imwrite("screenshots/mail_panel_frame.png", frame)
        print(f"    saved frame {frame.shape[1]}x{frame.shape[0]}")

    badge_tabs = _find_mail_tab_badges(frame)

    if not badge_tabs:
        print("    no tab badges found")
        time.sleep(random.uniform(1.0, 2.5))
        _close_mail(ctx)
        return

    active_x = _detect_active_mail_tab_x(frame)
    if active_x is not None:
        print(f"    active tab at x={active_x:.3f}")

    for bx, by in badge_tabs:
        if active_x is not None and abs(bx - active_x) < 0.08:
            print(f"    tab pct({bx:.3f}) is active, reading without re-click")
        else:
            print(f"    -> click tab at badge pct({bx:.3f},{by:.3f})")
            ctx._click_pct(bx - 0.01, by + 0.02, jitter_px=3)
            time.sleep(random.uniform(1.5, 3.0))

        frame2 = _grab_chat_frame(ctx)
        if frame2 is not None:
            still_has_badge = any(
                abs(b2x - bx) < 0.08 for b2x, _ in _find_mail_tab_badges(frame2)
            )
            if not still_has_badge:
                print(f"    tab pct({bx:.3f}) badge cleared after switch, skip read")
            else:
                read_btn = _find_mail_read_all(frame2)
                if read_btn:
                    rx, ry = read_btn[0], read_btn[1]
                    print(f"    -> read & collect all at pct({rx:.3f},{ry:.3f})")
                    ctx._click_pct(rx, ry, jitter_px=3)
                    time.sleep(random.uniform(1.5, 3.0))
                    _dismiss_reward_popup(ctx)

        active_x = bx

    _close_mail(ctx)


def _mail_btn_has_badge(frame) -> bool:
    """Check if the mail button on the bottom bar has a red notification badge."""
    if frame is None:
        return False
    fh, fw = frame.shape[:2]
    mx, my = BTN_POS["mail"]
    x1 = int((mx - 0.025) * fw)
    x2 = int((mx + 0.025) * fw)
    y1 = int((my - 0.035) * fh)
    y2 = int((my + 0.010) * fh)
    x1, x2 = max(0, x1), min(fw, x2)
    y1, y2 = max(0, y1), min(fh, y2)
    region = frame[y1:y2, x1:x2]
    if region.size == 0:
        return False
    red_px = int(((region[:, :, 2] > 150)
                  & (region[:, :, 1] < 100)
                  & (region[:, :, 0] < 100)).sum())
    if _DEBUG_BADGES:
        print(f"      mail btn badge ({x1},{y1})-({x2},{y2}) red_px={red_px}")
    return red_px > 30


def _detect_active_mail_tab_x(frame) -> float | None:
    """Detect the active mail tab by blue channel brightness in the tab row.

    Active tab is light blue (high blue value), inactive are darker.
    Uses blue channel to ignore red badge dots.
    Returns pct_x of the active tab center, or None.
    """
    if frame is None:
        return None
    fh, fw = frame.shape[:2]
    y1 = int(fh * 0.05)
    y2 = int(fh * 0.12)
    x1 = int(fw * 0.10)
    x2 = int(fw * 0.55)
    strip = frame[y1:y2, x1:x2]
    if strip.size == 0:
        return None
    blue = strip[:, :, 0].astype(np.float32)
    col_blue = blue.mean(axis=0)
    kernel = np.ones(30) / 30
    if len(col_blue) > 30:
        col_blue = np.convolve(col_blue, kernel, mode="same")
    peak_local_x = int(col_blue.argmax())
    peak_val = col_blue[peak_local_x]
    avg_val = col_blue.mean()
    if peak_val < avg_val + 10:
        return None
    return (x1 + peak_local_x) / fw


def _find_mail_tab_badges(frame) -> list[tuple[float, float]]:
    """Find red badge circles in the mail tab row.

    Returns list of (pct_x, pct_y) sorted left-to-right.
    Scans the top portion of the frame for circular red blobs
    that indicate unread tabs.
    """
    if frame is None:
        return []
    fh, fw = frame.shape[:2]
    y1 = int(fh * 0.03)
    y2 = int(fh * 0.10)
    x1 = int(fw * 0.10)
    x2 = int(fw * 0.60)
    strip = frame[y1:y2, x1:x2]

    red_mask = ((strip[:, :, 2] > 150)
                & (strip[:, :, 1] < 100)
                & (strip[:, :, 0] < 100))
    mask_u8 = red_mask.astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)

    badges = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < 15:
            continue
        x, y, w, h = cv2.boundingRect(c)
        aspect = min(w, h) / max(w, h) if max(w, h) > 0 else 0
        if aspect < 0.4:
            continue
        perimeter = cv2.arcLength(c, True)
        circ = (4 * np.pi * area / (perimeter ** 2)) if perimeter > 0 else 0
        if circ < 0.25:
            continue
        cx_px = x1 + x + w // 2
        cy_px = y1 + y + h // 2
        badges.append((cx_px / fw, cy_px / fh, area))

    badges.sort(key=lambda b: b[0])
    if _DEBUG_BADGES:
        for bx, by, ba in badges:
            print(f"      mail tab badge pct({bx:.3f},{by:.3f}) area={ba:.0f}")
    return [(bx, by) for bx, by, _ in badges]


def _find_mail_read_all(frame):
    """Find 'Doc va nhan tat' button at the bottom of the mail panel.

    Returns (pct_x, pct_y) or None.
    """
    if frame is None:
        return None
    return _match_on_frame(frame, "ui/mail_read_all_btn", threshold=0.55,
                           roi=(0.85, 1.0),
                           scales=[0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])


def _dismiss_reward_popup(ctx: PlayerActionCtx):
    """After reading mail, a reward popup may appear. Click XAC NHAN to dismiss."""
    frame = _grab_chat_frame(ctx)
    if frame is None:
        return
    m = _match_on_frame(frame, "ui/btn_confirm_reward", threshold=0.65,
                        roi=(0.4, 0.8),
                        scales=[0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
    if m:
        print(f"    -> reward popup, clicking confirm")
        ctx._click_pct(m[0], m[1], jitter_px=5)
        time.sleep(random.uniform(0.8, 1.5))


def _close_mail(ctx: PlayerActionCtx):
    """Close mail panel by clicking X button."""
    frame = _grab_chat_frame(ctx)
    if frame is not None:
        m = _match_on_frame(frame, "ui/btn_x_close_mail", threshold=0.60,
                            roi=(0.0, 0.15),
                            scales=[0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
        if m:
            print(f"    -> close mail X at pct({m[0]:.3f},{m[1]:.3f})")
            ctx._click_pct(m[0], m[1], jitter_px=3)
            ctx._wait(DELAY_AFTER_DISMISS)
            return
    _dismiss_panel(ctx)


def act_alliance(ctx: PlayerActionCtx):
    print(f"  [{INFO}] Distraction: checking alliance gifts")

    ctx._click_pct(*BTN_POS["alliance"])
    time.sleep(random.uniform(2.0, 4.0))

    frame = _grab_chat_frame(ctx)
    if frame is None:
        print("    no frame, aborting")
        _dismiss_panel(ctx)
        return

    gift = _match_on_frame(frame, "ui/btn_alliance_gift", threshold=0.55,
                           roi=(0.35, 0.90),
                           scales=[0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1])
    if not gift:
        print("    gift icon not found in alliance panel, skipping")
        _close_alliance(ctx)
        return

    has_badge = _check_red_badge_near(frame, gift[0], gift[1])
    if not has_badge:
        print(f"    gift icon found but no badge, skipping")
        _close_alliance(ctx)
        return

    print(f"    -> gift icon at pct({gift[0]:.3f},{gift[1]:.3f}) conf={gift[2]:.2f}")
    ctx._click_pct(gift[0], gift[1], jitter_px=5)
    time.sleep(random.uniform(1.5, 3.0))

    frame = _grab_chat_frame(ctx)
    if frame is None:
        _close_alliance_gift(ctx)
        _close_alliance(ctx)
        return

    _alliance_claim_tab(ctx, frame)

    frame = _grab_chat_frame(ctx)
    if frame is not None:
        tab_badges = _find_red_badges_in_region(frame, x_range=(0.20, 0.55), y_range=(0.25, 0.40))
        if tab_badges:
            tx, ty = tab_badges[0]
            print(f"    -> remaining tab badge at pct({tx:.3f},{ty:.3f}), switching")
            ctx._click_pct(tx, ty + 0.01, jitter_px=3)
            time.sleep(random.uniform(1.0, 2.0))
            frame2 = _grab_chat_frame(ctx)
            if frame2 is not None:
                _alliance_claim_tab(ctx, frame2)

    _close_alliance_gift(ctx)
    _close_alliance(ctx)


def _alliance_claim_tab(ctx, frame) -> bool:
    """Find and click NHAN TAT CA on the currently visible gift tab."""
    claim_btn = _match_on_frame(frame, "ui/btn_claim_all", threshold=0.45,
                                roi=(0.25, 0.45),
                                scales=[0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.8, 0.9, 1.0])
    if claim_btn:
        print(f"    -> claim all at pct({claim_btn[0]:.3f},{claim_btn[1]:.3f}) conf={claim_btn[2]:.2f}")
        ctx._click_pct(claim_btn[0], claim_btn[1], jitter_px=3)
        time.sleep(random.uniform(1.5, 3.0))
        _dismiss_alliance_reward(ctx)
        return True
    print("    claim all button not found on this tab")
    return False


def _find_red_badges_in_region(frame, x_range=(0.0, 1.0), y_range=(0.0, 1.0),
                               min_area=15, min_circ=0.25) -> list[tuple[float, float]]:
    """Find red badge circles in a specified region of the frame.

    Returns list of (pct_x, pct_y) sorted left-to-right.
    """
    if frame is None:
        return []
    fh, fw = frame.shape[:2]
    x1 = int(x_range[0] * fw)
    x2 = int(x_range[1] * fw)
    y1 = int(y_range[0] * fh)
    y2 = int(y_range[1] * fh)
    strip = frame[y1:y2, x1:x2]
    if strip.size == 0:
        return []

    red_mask = ((strip[:, :, 2] > 150)
                & (strip[:, :, 1] < 100)
                & (strip[:, :, 0] < 100))
    mask_u8 = red_mask.astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)

    badges = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        x, y, w, h = cv2.boundingRect(c)
        aspect = min(w, h) / max(w, h) if max(w, h) > 0 else 0
        if aspect < 0.4:
            continue
        perimeter = cv2.arcLength(c, True)
        circ = (4 * np.pi * area / (perimeter ** 2)) if perimeter > 0 else 0
        if circ < min_circ:
            continue
        cx_px = x1 + x + w // 2
        cy_px = y1 + y + h // 2
        badges.append((cx_px / fw, cy_px / fh))

    badges.sort(key=lambda b: b[0])
    return badges


def _check_red_badge_near(frame, pct_x: float, pct_y: float) -> bool:
    """Check if there's a red badge circle near a button position."""
    if frame is None:
        return False
    fh, fw = frame.shape[:2]
    cx, cy = int(pct_x * fw), int(pct_y * fh)
    x1 = max(0, cx - 40)
    x2 = min(fw, cx + 40)
    y1 = max(0, cy - 40)
    y2 = min(fh, cy + 10)
    region = frame[y1:y2, x1:x2]
    if region.size == 0:
        return False
    red_px = int(((region[:, :, 2] > 150)
                  & (region[:, :, 1] < 100)
                  & (region[:, :, 0] < 100)).sum())
    return red_px > 15


def _dismiss_alliance_reward(ctx: PlayerActionCtx):
    """After claiming alliance gifts, dismiss reward summary popup."""
    frame = _grab_chat_frame(ctx)
    if frame is None:
        return
    m = _match_on_frame(frame, "ui/btn_confirm_alliance", threshold=0.60,
                        roi=(0.4, 0.8),
                        scales=[0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
    if m:
        print(f"    -> reward summary, clicking confirm")
        ctx._click_pct(m[0], m[1], jitter_px=5)
        time.sleep(random.uniform(1.0, 2.0))


def _close_alliance_gift(ctx: PlayerActionCtx):
    """Close alliance gift popup by clicking X button."""
    frame = _grab_chat_frame(ctx)
    if frame is not None:
        m = _match_on_frame(frame, "ui/btn_x_close_alliance_gift", threshold=0.55,
                            roi=(0.10, 0.30),
                            scales=[0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
        if m and m[0] < 0.85:
            print(f"    -> close gift popup X at pct({m[0]:.3f},{m[1]:.3f})")
            ctx._click_pct(m[0], m[1], jitter_px=3)
            ctx._wait(DELAY_AFTER_DISMISS)
            return
    _dismiss_panel(ctx)


def _close_alliance(ctx: PlayerActionCtx):
    """Close alliance panel by clicking X button."""
    frame = _grab_chat_frame(ctx)
    if frame is not None:
        m = _match_on_frame(frame, "ui/btn_x_close_alliance", threshold=0.55,
                            roi=(0.0, 0.15),
                            scales=[0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
        if m and m[0] < 0.90:
            print(f"    -> close alliance X at pct({m[0]:.3f},{m[1]:.3f})")
            ctx._click_pct(m[0], m[1], jitter_px=3)
            ctx._wait(DELAY_AFTER_DISMISS)
            return
    _dismiss_panel(ctx)


def act_bag(ctx: PlayerActionCtx):
    print(f"  [{INFO}] Distraction: checking bag")
    ctx._click_pct(*BTN_POS["bag"])
    time.sleep(random.uniform(1.5, 3.5))
    if random.random() < 0.35:
        items = PANEL_ITEMS.get("bag", [])
        if items:
            for _ in range(random.randint(1, 2)):
                item = random.choice(items)
                ctx._click_pct(*item, jitter_px=5)
                time.sleep(random.uniform(0.8, 2.0))
    ctx._close_panel("bag")
    time.sleep(random.uniform(0.3, 0.8))


def act_events(ctx: PlayerActionCtx):
    print(f"  [{INFO}] Distraction: glancing at events")
    ctx._click_pct(*BTN_POS["events"])
    time.sleep(random.uniform(2.0, 5.0))
    if random.random() < 0.25:
        tab_y = 0.18
        tab_x = random.choice([0.30, 0.40, 0.50, 0.60, 0.70])
        ctx._click_pct(tab_x, tab_y, jitter_px=5)
        time.sleep(random.uniform(1.5, 3.0))
    ctx._close_panel("events")
    ctx._wait(DELAY_AFTER_ESCAPE)


def act_pan(ctx: PlayerActionCtx):
    cx, cy = ctx._center_screen()
    ww, wh = ctx.win["width"], ctx.win["height"]
    num_pans = random.choices([1, 2, 3], weights=[50, 35, 15])[0]
    print(f"  [{INFO}] Distraction: idle pan x{num_pans}")
    for _ in range(num_pans):
        dx = random.randint(-int(ww * 0.15), int(ww * 0.15))
        dy = random.randint(-int(wh * 0.10), int(wh * 0.10))
        ctx._human_drag(cx + dx, cy + dy, cx - dx, cy - dy,
                        speed_factor=random.uniform(2.0, 4.0))
        time.sleep(random.uniform(0.4, 1.5))


def act_zoom(ctx: PlayerActionCtx):
    direction = random.choice([-1, 1])
    notches = random.randint(1, 3)
    print(f"  [{INFO}] Distraction: idle zoom {'in' if direction > 0 else 'out'} x{notches}")
    ctx._scroll_at_center(direction, notches)
    time.sleep(random.uniform(0.8, 2.5))
    if random.random() < 0.4:
        time.sleep(random.uniform(1.0, 3.0))
    ctx._scroll_at_center(-direction, notches)
    time.sleep(random.uniform(0.3, 1.0))


def act_stare(ctx: PlayerActionCtx):
    cx, cy = ctx._center_screen()
    ww, wh = ctx.win["width"], ctx.win["height"]
    duration = random.uniform(1.5, 6.0)
    print(f"  [{INFO}] Distraction: staring {duration:.1f}s")
    if random.random() < 0.3:
        ctx._moveto(
            cx + random.randint(-int(ww * 0.3), int(ww * 0.3)),
            cy + random.randint(-int(wh * 0.2), int(wh * 0.2)))
    time.sleep(duration)


def _click_empty(ctx: PlayerActionCtx):
    """Close any popup by clicking an empty area -- how real players dismiss panels."""
    ww, wh = ctx.win["width"], ctx.win["height"]
    rx = random.uniform(0.25, 0.75)
    ry = random.uniform(0.25, 0.45)
    sx = ctx.win["left"] + int(ww * rx)
    sy = ctx.win["top"] + int(wh * ry)
    ctx._click(sx, sy)


CHAT_OPEN_POS = (0.15, 0.92)

CHAT_CH_TMPLS = [
    {"name": "world",
     "active": "ui/chat_ch_world_active",
     "inactive": "ui/chat_ch_world_inactive"},
    {"name": "kingdom",
     "active": "ui/chat_ch_kingdom_active",
     "inactive": "ui/chat_ch_kingdom_inactive"},
    {"name": "alliance",
     "active": "ui/chat_ch_alliance_active",
     "inactive": "ui/chat_ch_alliance_inactive"},
]
CHAT_ICON_SCALES = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]


def act_chat(ctx: PlayerActionCtx):
    print(f"  [{INFO}] Distraction: glancing at chat")

    ctx._click_pct(*CHAT_OPEN_POS, jitter_px=15)
    time.sleep(random.uniform(1.5, 3.0))

    frame = _grab_chat_frame(ctx)
    channels = _find_chat_channels(frame)

    if not channels:
        toggled = _try_expand_sidebar(ctx, frame)
        if toggled:
            time.sleep(random.uniform(0.8, 1.5))
            frame = _grab_chat_frame(ctx)
            channels = _find_chat_channels(frame)

    if not channels:
        print("    no chat channels found, closing")
        _close_chat_panel(ctx)
        return

    for ch in channels:
        ch["badge"] = _detect_channel_badge(frame, ch, debug=_DEBUG_BADGES)

    for ch in channels:
        tag = " (active)" if ch["is_active"] else ""
        print(f"    {ch['name']}: badge={ch['badge']}{tag}")

    max_visits = random.choices([1, 2], weights=[65, 35])[0]

    for visit in range(max_visits):
        if visit > 0:
            time.sleep(random.uniform(0.8, 1.5))
            frame = _grab_chat_frame(ctx)
            channels = _find_chat_channels(frame)
            for ch in channels:
                ch["badge"] = _detect_channel_badge(frame, ch)

        has_new = [ch for ch in channels if ch["badge"] > 0 and not ch["is_active"]]
        if not has_new:
            break

        target = max(has_new, key=lambda c: c["badge"])
        print(f"    -> click {target['name']} ({target['badge']})")
        ctx._click_pct(target["pct_x"], target["pct_y"], jitter_px=6)
        time.sleep(random.uniform(2.0, 5.0))
        scrolls = max(0, target["badge"] - 5) // 5
        if scrolls >= 1:
            actual = random.randint(max(1, scrolls - 1), scrolls + 1)
            _chat_scroll(ctx, scrolls=actual)
        time.sleep(random.uniform(1.0, 3.0))

    _close_chat_panel(ctx)


def _grab_chat_frame(ctx: PlayerActionCtx):
    try:
        if hasattr(ctx, '_grab'):
            return ctx._grab()
        from capture.screen_capture import ScreenCapture
        sc = ScreenCapture()
        return sc.grab_full()
    except Exception:
        return None


CHAT_SIDEBAR_X_MAX = 0.15
CHAT_SIDEBAR_Y_MAX = 0.55


def _find_chat_channels(frame) -> list[dict]:
    """Find channel icons in chat sidebar via template matching.

    Returns list of {name, pct_x, pct_y, is_active, tmpl_w, tmpl_h}.
    Only the channel with highest active-template confidence is marked active.
    Matches outside the sidebar region are rejected.
    """
    if frame is None:
        return []
    results = []
    for ch in CHAT_CH_TMPLS:
        best = None
        best_conf = 0.0
        active_conf = 0.0
        is_active = False
        for state, tmpl_name in [("active", ch["active"]),
                                  ("inactive", ch["inactive"])]:
            m = _match_on_frame(frame, tmpl_name, threshold=0.50,
                                roi=(0.0, CHAT_SIDEBAR_Y_MAX),
                                scales=CHAT_ICON_SCALES)
            if m and m[0] > CHAT_SIDEBAR_X_MAX:
                continue
            if m and m[2] > best_conf:
                best = m
                best_conf = m[2]
                is_active = (state == "active")
            if state == "active" and m and m[0] <= CHAT_SIDEBAR_X_MAX:
                active_conf = m[2]
        if best:
            if _DEBUG_BADGES:
                print(f"    ch-dbg {ch['name']}: conf={best_conf:.3f} "
                      f"pos=({best[0]:.3f},{best[1]:.3f}) "
                      f"active={'Y' if is_active else 'N'}")
            results.append({
                "name": ch["name"],
                "pct_x": best[0],
                "pct_y": best[1],
                "is_active": is_active,
                "active_conf": active_conf,
                "tmpl_w": best[3],
                "tmpl_h": best[4],
            })

    active_chs = [ch for ch in results if ch["is_active"]]
    if len(active_chs) > 1:
        best_active = max(active_chs, key=lambda c: c["active_conf"])
        for ch in results:
            ch["is_active"] = (ch is best_active)

    return results


def _detect_channel_badge(frame, ch_info, debug=False) -> int:
    """Detect red badge at top-right corner of a channel icon.

    Searches only the top-right quadrant to avoid picking up
    red pixels from the icon itself (e.g. alliance shield).
    Returns badge number (0 = no badge).
    """
    if frame is None:
        return 0
    try:
        fh, fw = frame.shape[:2]
        cx = int(ch_info["pct_x"] * fw)
        cy = int(ch_info["pct_y"] * fh)
        tw = ch_info["tmpl_w"]
        th = ch_info["tmpl_h"]

        half_w = max(tw, 35)
        half_h = max(th, 45)
        x1 = max(0, cx - half_w)
        x2 = min(fw, cx + half_w)
        y1 = max(0, cy - half_h)
        y2 = min(fh, cy)

        region = frame[y1:y2, x1:x2]
        if region.size == 0:
            return 0

        r_ch = region[:, :, 2].astype(np.float32)
        g_ch = region[:, :, 1].astype(np.float32)
        b_ch = region[:, :, 0].astype(np.float32)
        red_mask = (r_ch > 150) & (g_ch < 100) & (b_ch < 100)
        red_px = int(red_mask.sum())
        if debug:
            name = ch_info.get("name", "?")
            print(f"    badge-dbg {name}: icon@({cx},{cy}) tw={tw} th={th}"
                  f" region=({x1},{y1})-({x2},{y2}) red_px={red_px}")
        if red_px < 15:
            return 0

        circle = _find_badge_circle(red_mask, min_circularity=0.40)
        if circle is None:
            if debug:
                print(f"    badge-dbg {ch_info.get('name','?')}: no circular blob")
            return 0
        bx, by, bw, bh, area = circle
        aspect = min(bw, bh) / max(bw, bh) if max(bw, bh) > 0 else 0
        if debug:
            print(f"    badge-dbg {ch_info.get('name','?')}: "
                  f"circle area={area} size={bw}x{bh} aspect={aspect:.2f}")
        if area > 450 or aspect < 0.5 or max(bw, bh) > 28:
            return 0

        pad_b = 3
        bx1 = max(0, bx - pad_b)
        by1 = max(0, by - pad_b)
        bx2 = min(region.shape[1], bx + bw + pad_b)
        by2 = min(region.shape[0], by + bh + pad_b)
        badge_crop = region[by1:by2, bx1:bx2]
        red_mask_crop = red_mask[by1:by2, bx1:bx2]

        digits = _extract_badge_digits(badge_crop, red_mask_crop)
        if not digits:
            return 5

        number = 0
        for dimg, dbbox, darea in digits:
            number = number * 10 + _classify_badge_digit(dimg, dbbox)
        return min(max(1, number), 99)
    except Exception:
        return 0


def _close_chat_panel(ctx: PlayerActionCtx):
    """Close chat panel by template-matching the '<' close button,
    fallback to clicking game area outside the panel."""
    frame = _grab_chat_frame(ctx)
    if frame is not None:
        m = _match_on_frame(frame, "ui/chat_close_btn", threshold=0.50,
                            scales=[0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2])
        if m and m[0] < 0.40:
            ctx._click_pct(m[0], m[1], jitter_px=5)
            ctx._wait(DELAY_AFTER_ESCAPE)
            return
    _dismiss_panel(ctx)


def _find_badge_circle(red_mask, min_circularity=0.0):
    """Find the most circular red blob — that's the notification badge."""
    mask_u8 = red_mask.astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_score = -1
    for c in contours:
        area = cv2.contourArea(c)
        if area < 30:
            continue
        x, y, w, h = cv2.boundingRect(c)
        perimeter = cv2.arcLength(c, True)
        circularity = (4 * np.pi * area / (perimeter ** 2)) if perimeter > 0 else 0
        if circularity < min_circularity:
            continue
        aspect = min(w, h) / max(w, h) if max(w, h) > 0 else 0
        score = circularity * 2 + aspect
        if score > best_score:
            best_score = score
            best = (x, y, w, h, area)
    return best


def _extract_badge_digits(badge_crop, red_mask_crop):
    """Extract white digit contours from a badge circle crop."""
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


def _classify_badge_digit(digit_img, bbox):
    """Classify a single digit image using stem width, hole position, and shape analysis."""
    x, y, w, h = bbox
    binary = (digit_img > 0).astype(np.uint8)

    # Middle stem width (rows 30%-70%)
    r1, r2 = int(h * 0.30), int(h * 0.70)
    mid_width = float(binary[r1:r2, :].sum(axis=1).mean()) if r2 > r1 else w

    # Center-of-mass shift from top to bottom (negative = right-to-left like "2")
    row_centers = []
    for r in range(h):
        cols = np.where(binary[r, :] > 0)[0]
        row_centers.append(float(cols.mean()) if len(cols) > 0 else w / 2.0)
    top_center = np.mean(row_centers[:max(1, h // 3)])
    bot_center = np.mean(row_centers[max(1, 2 * h // 3):])
    center_shift = (bot_center - top_center) / w if w > 0 else 0

    # Hole detection + location
    padded = np.zeros((h + 2, w + 2), dtype=np.uint8)
    padded[1:h + 1, 1:w + 1] = binary * 255
    inv = cv2.bitwise_not(padded)
    n_labels, labels = cv2.connectedComponents(inv)
    holes = max(0, n_labels - 2)

    bot_fill = float(binary[-1, :].sum()) / w if w > 0 else 0
    top_fill = float(binary[0, :].sum()) / w if w > 0 else 0

    # "1": thin stem + narrow bbox or no shift
    if mid_width <= 2.5 and (w <= 5 or abs(center_shift) < 0.05):
        return 1

    # Hole-based digits
    if holes >= 1:
        hole_cy_list = []
        for lab in range(2, n_labels):
            ys_h = np.where(labels == lab)[0] - 1
            if len(ys_h) > 0:
                hole_cy_list.append(float(ys_h.mean()) / h)
        avg_hole_y = np.mean(hole_cy_list) if hole_cy_list else 0.5

        if holes >= 2:
            return 8
        if avg_hole_y < 0.40:
            return 9
        if avg_hole_y > 0.60:
            return 6
        if center_shift < -0.15:
            return 4
        return 0

    # No holes: 2, 3, 5, 7
    mid_h = h // 2
    top_px = int(binary[:mid_h, :].sum())
    total_px = int(binary.sum())
    top_frac = top_px / total_px if total_px > 0 else 0.5

    if top_frac > 0.55 and bot_fill < 0.5 and mid_width < w * 0.5:
        return 7
    if center_shift < -0.05 and bot_fill > 0.7:
        return 2

    mid_row_fill = float(binary[h // 2, :].sum()) / w if w > 0 else 0
    if center_shift > -0.05 and mid_row_fill > 0.3 and bot_fill > 0.5:
        return 3
    if center_shift > 0.10 and top_fill > 0.5:
        return 5
    if center_shift < -0.05:
        return 2
    if center_shift > 0.05:
        return 5
    return 3


def _scan_red_pixels(frame):
    """Scan left sidebar for red pixel clusters to locate badge positions."""
    fh, fw = frame.shape[:2]
    scan_w = int(fw * 0.15)
    scan_h = int(fh * 0.45)
    region = frame[:scan_h, :scan_w]

    r_ch = region[:, :, 2].astype(np.float32)
    g_ch = region[:, :, 1].astype(np.float32)
    b_ch = region[:, :, 0].astype(np.float32)
    red_mask = (r_ch > 150) & (g_ch < 100) & (b_ch < 100)
    count = int(red_mask.sum())
    print(f"    scan: region {scan_w}x{scan_h}, red pixels={count}")

    if count == 0:
        print("    scan: NO red pixels found in left sidebar!")
        return

    ys, xs = np.where(red_mask)
    from itertools import groupby
    clusters = []
    sorted_pts = sorted(zip(ys.tolist(), xs.tolist()))
    visited = set()
    for y, x in sorted_pts:
        if (y, x) in visited:
            continue
        cluster_pts = []
        stack = [(y, x)]
        while stack:
            cy, cx = stack.pop()
            if (cy, cx) in visited:
                continue
            if cy < 0 or cy >= scan_h or cx < 0 or cx >= scan_w:
                continue
            if not red_mask[cy, cx]:
                continue
            visited.add((cy, cx))
            cluster_pts.append((cy, cx))
            for dy, dx in [(-1,0),(1,0),(0,-1),(0,1)]:
                stack.append((cy+dy, cx+dx))
        if len(cluster_pts) >= 5:
            ys_c = [p[0] for p in cluster_pts]
            xs_c = [p[1] for p in cluster_pts]
            cy = sum(ys_c) // len(ys_c)
            cx = sum(xs_c) // len(xs_c)
            clusters.append((cx, cy, len(cluster_pts)))

    clusters.sort(key=lambda c: c[1])
    print(f"    scan: {len(clusters)} red cluster(s):")
    for cx, cy, size in clusters:
        pct_x = cx / fw
        pct_y = cy / fh
        print(f"      px({cx},{cy}) pct({pct_x:.3f},{pct_y:.3f}) size={size}")


SIDEBAR_TOGGLE_REGION = (0.00, 0.02, 0.25, 0.08)  # x1, y1, x2, y2 in frame pct


def _try_expand_sidebar(ctx: PlayerActionCtx, frame) -> bool:
    """If chat sidebar is collapsed, the toggle button shows a red total-unread badge.
    Detect it and click to expand the sidebar so channel badges become visible."""
    if frame is None:
        return False
    fh, fw = frame.shape[:2]
    x1 = int(SIDEBAR_TOGGLE_REGION[0] * fw)
    y1 = int(SIDEBAR_TOGGLE_REGION[1] * fh)
    x2 = int(SIDEBAR_TOGGLE_REGION[2] * fw)
    y2 = int(SIDEBAR_TOGGLE_REGION[3] * fh)
    region = frame[y1:y2, x1:x2]
    if region.size == 0:
        return False

    red_mask = ((region[:, :, 2] > 150)
                & (region[:, :, 1] < 100)
                & (region[:, :, 0] < 100))
    red_px = int(red_mask.sum())
    if red_px < 10:
        return False

    ys, xs = np.where(red_mask)
    cy = int(np.median(ys)) + y1
    cx = int(np.median(xs)) + x1
    print(f"    sidebar collapsed, toggle at pct({cx/fw:.3f},{cy/fh:.3f})")

    click_x = ctx.win["left"] + int(cx * ctx.win["width"] / fw)
    click_y = ctx.win["top"] + int(cy * ctx.win["height"] / fh)
    ctx._click(click_x, click_y)
    return True


def _chat_scroll(ctx: PlayerActionCtx, scrolls: int = 3):
    ww, wh = ctx.win["width"], ctx.win["height"]
    scroll_x = ctx.win["left"] + int(ww * random.uniform(0.12, 0.28))
    scroll_y = ctx.win["top"] + int(wh * random.uniform(0.25, 0.70))
    ctx._moveto(scroll_x, scroll_y)
    time.sleep(random.uniform(0.3, 0.6))
    for _ in range(scrolls):
        ctx.cmd.send("SCROLL", 1)
        time.sleep(random.uniform(0.08, 0.25))
    time.sleep(random.uniform(1.5, 4.0))


def act_alt_tab(ctx: PlayerActionCtx):
    if random.random() > 0.3:
        return
    print(f"  [{INFO}] Distraction: quick alt-tab")
    hold = random.randint(50, 120)
    ctx.cmd.send("COMBO", "ALT", "TAB", hold)
    time.sleep(random.uniform(3.0, 15.0))
    hold = random.randint(50, 120)
    ctx.cmd.send("COMBO", "ALT", "TAB", hold)
    time.sleep(random.uniform(1.0, 3.0))


def act_peek_poi(ctx: PlayerActionCtx):
    cx, cy = ctx._center_screen()
    ww, wh = ctx.win["width"], ctx.win["height"]
    print(f"  [{INFO}] Distraction: peeking at random POI")
    poi_x = cx + random.randint(-int(ww * 0.35), int(ww * 0.35))
    poi_y = cy + random.randint(-int(wh * 0.25), int(wh * 0.25))
    poi_x, poi_y = ctx._clamp_to_play_area(poi_x, poi_y)
    ctx._click(poi_x, poi_y)
    time.sleep(random.uniform(1.5, 4.0))
    if random.random() < 0.3:
        time.sleep(random.uniform(1.0, 3.0))
    _click_empty(ctx)
    ctx._wait(DELAY_AFTER_ESCAPE)


def act_check_troops(ctx: PlayerActionCtx):
    ww, wh = ctx.win["width"], ctx.win["height"]
    print(f"  [{INFO}] Distraction: checking march status")
    troop_x = ctx.win["left"] + int(ww * random.uniform(0.01, 0.06))
    troop_y = ctx.win["top"] + int(wh * random.uniform(0.30, 0.50))
    ctx._moveto(troop_x, troop_y)
    time.sleep(random.uniform(1.5, 4.0))
    if random.random() < 0.25:
        ctx._click(troop_x, troop_y)
        time.sleep(random.uniform(1.5, 3.5))
        _click_empty(ctx)
        ctx._wait(DELAY_AFTER_ESCAPE)


def act_hesitate(ctx: PlayerActionCtx):
    cx, cy = ctx._center_screen()
    ww, wh = ctx.win["width"], ctx.win["height"]
    print(f"  [{INFO}] Distraction: hesitating")
    target_x = cx + random.randint(-int(ww * 0.3), int(ww * 0.3))
    target_y = cy + random.randint(-int(wh * 0.2), int(wh * 0.2))
    ctx._moveto(target_x, target_y)
    time.sleep(random.uniform(0.3, 0.8))
    drift_x = target_x + random.randint(-30, 30)
    drift_y = target_y + random.randint(-20, 20)
    ctx._moveto(drift_x, drift_y)
    time.sleep(random.uniform(0.5, 2.0))
    away_x = cx + random.randint(-int(ww * 0.1), int(ww * 0.1))
    away_y = cy + random.randint(-int(wh * 0.1), int(wh * 0.1))
    ctx._moveto(away_x, away_y)
    time.sleep(random.uniform(0.3, 1.0))


def act_misclick(ctx: PlayerActionCtx):
    cx, cy = ctx._center_screen()
    ww, wh = ctx.win["width"], ctx.win["height"]
    print(f"  [{INFO}] Distraction: misclick + recover")
    miss_x = cx + random.randint(-int(ww * 0.35), int(ww * 0.35))
    miss_y = cy + random.randint(-int(wh * 0.25), int(wh * 0.25))
    miss_x, miss_y = ctx._clamp_to_play_area(miss_x, miss_y)
    ctx._click(miss_x, miss_y)
    time.sleep(random.uniform(0.4, 1.2))
    _click_empty(ctx)
    ctx._wait(DELAY_AFTER_ESCAPE)
    if random.random() < 0.3:
        _click_empty(ctx)
        ctx._wait(DELAY_AFTER_ESCAPE)


def act_scout_fog(ctx: PlayerActionCtx):
    """Pan toward a random edge then come back -- scouting unknown territory."""
    cx, cy = ctx._center_screen()
    ww, wh = ctx.win["width"], ctx.win["height"]
    margin = 80
    angle = random.uniform(0, 2 * math.pi)
    print(f"  [{INFO}] Distraction: scouting fog")
    for _ in range(random.randint(2, 4)):
        dist = random.uniform(0.22, 0.32)
        dx = int(math.cos(angle) * (ww // 2 - margin) * dist)
        dy = int(math.sin(angle) * (wh // 2 - margin) * dist)
        sx, sy = ctx._clamp_to_play_area(cx + dx, cy + dy)
        ex, ey = ctx._clamp_to_play_area(cx - dx, cy - dy)
        ctx._human_drag(sx, sy, ex, ey, speed_factor=random.uniform(2.5, 4.5))
        time.sleep(random.uniform(0.3, 0.8))
        angle += random.gauss(0, 0.25)
    time.sleep(random.uniform(0.5, 2.0))
    # drift back roughly
    ctx._human_drag(
        cx + random.randint(-40, 40), cy + random.randint(-30, 30),
        cx, cy, speed_factor=random.uniform(2.0, 3.5))
    time.sleep(random.uniform(0.3, 0.8))


def act_idle_drag(ctx: PlayerActionCtx):
    """Aimless slow drag -- like finger resting on mouse and drifting."""
    cx, cy = ctx._center_screen()
    ww, wh = ctx.win["width"], ctx.win["height"]
    drift_x = random.randint(-int(ww * 0.06), int(ww * 0.06))
    drift_y = random.randint(-int(wh * 0.04), int(wh * 0.04))
    print(f"  [{INFO}] Distraction: idle drift")
    ctx._human_drag(cx, cy, cx + drift_x, cy + drift_y,
                    speed_factor=random.uniform(1.0, 2.0))
    time.sleep(random.uniform(0.8, 2.5))


def act_micro_afk(ctx: PlayerActionCtx):
    """Short AFK -- cursor stops, player looks away from screen briefly."""
    duration = random.uniform(4.0, 15.0)
    print(f"  [{INFO}] Distraction: micro AFK {duration:.0f}s")
    if random.random() < 0.5:
        cx, cy = ctx._center_screen()
        ww, wh = ctx.win["width"], ctx.win["height"]
        ctx._moveto(
            cx + random.randint(-int(ww * 0.2), int(ww * 0.2)),
            cy + random.randint(-int(wh * 0.15), int(wh * 0.15)))
    time.sleep(duration)


# ---------------------------------------------------------------------------
# Action registry
# ---------------------------------------------------------------------------

ACTION_REGISTRY: dict[str, callable] = {
    "mail":         act_mail,
    "alliance":     act_alliance,
    "bag":          act_bag,
    "events":       act_events,
    "pan":          act_pan,
    "zoom":         act_zoom,
    "stare":        act_stare,
    "chat":         act_chat,
    "alt_tab":      act_alt_tab,
    "peek_poi":     act_peek_poi,
    "check_troops": act_check_troops,
    "hesitate":     act_hesitate,
    "misclick":     act_misclick,
    "scout_fog":    act_scout_fog,
    "idle_drag":    act_idle_drag,
    "micro_afk":    act_micro_afk,
}

CITY_FALLBACKS = sorted((ANYWHERE | CITY_ONLY) - {"alt_tab"})
WORLD_FALLBACKS = sorted((ANYWHERE | WORLD_ONLY) - {"alt_tab"})


# ---------------------------------------------------------------------------
# PlayerActions -- orchestrator
# ---------------------------------------------------------------------------

class PlayerActions:
    def __init__(self, ctx: PlayerActionCtx, persona: dict):
        self._ctx = ctx
        self._preferred = persona.get("preferred_idle", ["pan", "stare"])
        self._hesitation = persona.get("hesitation_level", 0.05)
        self._history: list[str] = []

    CONTEXT_CHANCE = {
        "after_world":  0.06,
        "during_scan":  0.02,
        "after_gather": 0.08,
        "after_march":  0.10,
        "before_next":  0.05,
        "general":      0.04,
    }

    def maybe_distract(self, context: str = "general") -> bool:
        base = self.CONTEXT_CHANCE.get(context, 0.08)
        if random.random() > base + self._hesitation:
            return False
        return self.do_random()

    def do_random(self) -> bool:
        action_name = random.choice(self._preferred)
        return self.do(action_name)

    def do(self, action_name: str) -> bool:
        on_world = self._ctx._find("buttons/city_btn", threshold=0.70) is not None

        if on_world and action_name in CITY_ONLY:
            action_name = random.choice(WORLD_FALLBACKS)
        elif not on_world and action_name in WORLD_ONLY:
            action_name = random.choice(CITY_FALLBACKS)

        fn = ACTION_REGISTRY.get(action_name)
        if fn is None:
            logger.warning("Unknown action: %s", action_name)
            return False

        try:
            fn(self._ctx)
            self._history.append(action_name)
            return True
        except Exception as e:
            logger.warning("Action %s failed: %s", action_name, e)
            return False

    @property
    def history(self) -> list[str]:
        return self._history

    @staticmethod
    def all_action_names() -> list[str]:
        return sorted(ACTION_REGISTRY.keys())

    @staticmethod
    def default_preferred_pool() -> list[str]:
        return sorted(ALL_ACTIONS)

    @staticmethod
    def random_preferred(k_min: int = 4, k_max: int = 7) -> list[str]:
        pool = sorted(ALL_ACTIONS)
        k = random.randint(k_min, min(k_max, len(pool)))
        return random.sample(pool, k=k)

    @staticmethod
    def focused_farmer_preferred() -> list[str]:
        """Pool for a hired/focused farmer -- minimal distractions, all functional."""
        core = ["micro_afk", "stare", "pan", "check_troops"]
        extras = ["chat", "zoom", "idle_drag", "peek_poi"]
        k = random.randint(1, 2)
        return core + random.sample(extras, k=k)


# ---------------------------------------------------------------------------
# CLI test runner
# ---------------------------------------------------------------------------

def _try_resize_game(sc, target_w):
    """Try to resize game window to target content width, keeping aspect ratio."""
    import ctypes
    import sys
    win = sc._window
    aspect = win["height"] / win["width"] if win["width"] > 0 else 0.56
    target_h = round(target_w * aspect)

    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "resize_window.py")
    python = sys.executable
    args = f'"{script}" {target_w} {target_h} --batch'

    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        is_admin = False

    if is_admin:
        os.system(f'"{python}" {args}')
    else:
        print(f"  Requesting admin to resize -> {target_w}x{target_h}")
        ctypes.windll.shell32.ShellExecuteW(None, "runas", python, args, None, 0)
        for _ in range(20):
            time.sleep(0.5)
            sc._window = None
            _w = sc.find_window()
            if _w and abs(_w["width"] - target_w) < 5:
                break


def _cli_main():
    import argparse
    import sys
    import os
    import ctypes

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()

    parser = argparse.ArgumentParser(description="Test player actions via ESP32")
    parser.add_argument("--port", type=str, help="Serial port (e.g. COM27)")
    parser.add_argument("--list", action="store_true", help="List all actions and exit")
    parser.add_argument("--action", type=str, help="Run specific action(s), comma-separated")
    parser.add_argument("--random", type=int, metavar="N", help="Run N random actions")
    parser.add_argument("--all", action="store_true", help="Run every action once")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="Delay between actions (default 2s)")
    parser.add_argument("--debug-badges", action="store_true",
                        help="Enable red-pixel scan in badge detection")
    args = parser.parse_args()

    global _DEBUG_BADGES
    if args.debug_badges:
        _DEBUG_BADGES = True

    if args.list:
        print("Available actions:")
        for name in sorted(ACTION_REGISTRY.keys()):
            where = ("city" if name in CITY_ONLY
                     else "world" if name in WORLD_ONLY
                     else "anywhere")
            print(f"  {name:18s} [{where}]")
        return

    if not args.port:
        print("--port required for running actions")
        return

    import win32gui
    from capture.screen_capture import ScreenCapture
    from capture.screen_info import get_cursor_pos, screen_to_hid, get_screen_resolution
    from vision.template_cache import TemplateCache
    from vision.template_matcher import TemplateMatcher, Match
    from anti_detection.profile_loader import ProfileLoader, DEFAULT_PROFILE
    from anti_detection.mouse_humanizer import MouseHumanizer
    from serial_comm.connection import SerialConnection
    from serial_comm.command_buffer import CommandBuffer

    TARGET_CONTENT_W = 1533

    sc = ScreenCapture()
    win = sc.find_window()
    if not win:
        print("Game window not found")
        return

    if win["width"] != TARGET_CONTENT_W:
        print(f"Game: {win['width']}x{win['height']} -> resizing to w={TARGET_CONTENT_W}")
        _try_resize_game(sc, TARGET_CONTENT_W)
        time.sleep(0.3)
        sc._window = None
        win = sc.find_window()
        if not win:
            print("Game window lost after resize")
            return

    print(f"Game: {win['width']}x{win['height']} at ({win['left']},{win['top']})")

    # Connect ESP32
    conn = SerialConnection(port=args.port)
    if not conn.connect():
        print(f"ESP32 connect failed on {args.port}")
        return
    cmd = CommandBuffer(conn)
    cmd.start()
    print(f"ESP32: {args.port} connected")

    # Calibrate mouse acceleration
    print("Calibrating mouse acceleration...")
    _cal_scales = []
    for _tdx in [80, -80, 120, -120]:
        time.sleep(0.15)
        _bx, _ = get_cursor_pos()
        cmd.send("MOVE", _tdx, 0, 50)
        time.sleep(0.15)
        _ax, _ = get_cursor_pos()
        _actual = _ax - _bx
        if abs(_tdx) > 5 and abs(_actual) > 5:
            _cal_scales.append(_actual / _tdx)
    for _tdy in [80, -80]:
        time.sleep(0.15)
        _, _by = get_cursor_pos()
        cmd.send("MOVE", 0, _tdy, 50)
        time.sleep(0.15)
        _, _ay = get_cursor_pos()
        _actual = _ay - _by
        if abs(_tdy) > 5 and abs(_actual) > 5:
            _cal_scales.append(_actual / _tdy)
    if _cal_scales:
        mouse_scale = max(0.5, min(3.0, sum(abs(s) for s in _cal_scales) / len(_cal_scales)))
    else:
        mouse_scale = 1.0
    print(f"Mouse scale: {mouse_scale:.2f}x")

    # Set up vision
    loader = ProfileLoader()
    profile = loader.load_random() if loader.list_profiles() else DEFAULT_PROFILE.copy()
    humanizer = MouseHumanizer(profile)
    cache = TemplateCache()
    matcher = TemplateMatcher(cache)

    class TestCtx:
        """Lightweight context for testing individual actions."""
        def __init__(self):
            self.win = win
            self.cmd = cmd

        def _center_screen(self):
            return (win["left"] + win["width"] // 2,
                    win["top"] + win["height"] // 2)

        def _clamp_to_play_area(self, sx, sy):
            wl, wt = win["left"], win["top"]
            ww, wh = win["width"], win["height"]
            x = max(wl + int(ww * 0.12), min(wl + int(ww * 0.88), sx))
            y = max(wt + int(wh * 0.22), min(wt + int(wh * 0.70), sy))
            return x, y

        def _clamp_to_window(self, sx, sy, pad=5):
            x = max(win["left"] + pad, min(win["left"] + win["width"] - pad, sx))
            top_pad = max(pad, TITLE_BAR_H)
            y = max(win["top"] + top_pad, min(win["top"] + win["height"] - pad, sy))
            return x, y

        def _moveto(self, sx, sy):
            sx, sy = self._clamp_to_window(sx, sy)
            cur_x, cur_y = get_cursor_pos()
            if abs(sx - cur_x) < 3 and abs(sy - cur_y) < 3:
                return True
            sc = mouse_scale
            path = humanizer.humanize_move(cur_x, cur_y, sx, sy)
            for px, py, step_ms in path:
                ax, ay = get_cursor_pos()
                mdx, mdy = px - ax, py - ay
                send_dx = int(mdx / sc) if sc != 1.0 else int(mdx)
                send_dy = int(mdy / sc) if sc != 1.0 else int(mdy)
                if abs(send_dx) > 0 or abs(send_dy) > 0:
                    dur = max(step_ms, max(abs(send_dx), abs(send_dy)))
                    cmd.send("MOVE", send_dx, send_dy, dur)
            return True

        def _click(self, sx, sy, hold_ms=0):
            self._moveto(sx, sy)
            time.sleep(random.uniform(0.15, 0.4))
            if hold_ms <= 0:
                hold_ms = random.randint(35, 90)
            cmd.send("CLICK", "L", hold_ms)
            time.sleep(random.uniform(0.1, 0.3))
            return True

        def _click_pct(self, pct_x, pct_y, jitter_px=10):
            sx = win["left"] + int(win["width"] * pct_x) + random.randint(-jitter_px, jitter_px)
            sy = win["top"] + int(win["height"] * pct_y) + random.randint(-jitter_px, jitter_px)
            return self._click(sx, sy)

        def _human_drag(self, sx, sy, ex, ey, button="L",
                        speed_factor=1.0, easing="in_out"):
            sx, sy = self._clamp_to_window(sx, sy)
            ex, ey = self._clamp_to_window(ex, ey)
            self._moveto(sx, sy)
            time.sleep(random.uniform(0.08, 0.2))
            path = humanizer.humanize_move(sx, sy, ex, ey)
            if speed_factor != 1.0:
                path = [(x, y, max(3, int(ms / speed_factor))) for x, y, ms in path]
            sc = mouse_scale
            cmd.send("MDOWN", button)
            time.sleep(random.uniform(0.01, 0.03))
            prev_x, prev_y = float(sx), float(sy)
            for px, py, step_ms in path:
                mdx = px - prev_x
                mdy = py - prev_y
                send_dx = int(mdx / sc) if sc != 1.0 else int(mdx)
                send_dy = int(mdy / sc) if sc != 1.0 else int(mdy)
                if abs(send_dx) > 0 or abs(send_dy) > 0:
                    cmd.send("MOVE", send_dx, send_dy, step_ms)
                prev_x, prev_y = float(px), float(py)
            time.sleep(random.uniform(0.01, 0.03))
            cmd.send("MUP", button)

        def _scroll_at_center(self, amount, count=1):
            cx, cy = self._center_screen()
            cx += random.randint(-int(win["width"] * 0.15), int(win["width"] * 0.15))
            cy += random.randint(-int(win["height"] * 0.10), int(win["height"] * 0.10))
            self._moveto(cx, cy)
            time.sleep(random.uniform(0.15, 0.4))
            direction = 1 if amount > 0 else -1
            for _ in range(abs(amount) * count):
                cmd.send("SCROLL", direction)
                time.sleep(random.uniform(0.04, 0.12))

        def _press_escape(self):
            hold = random.randint(30, 80)
            cmd.send("KEY", "ESC", hold)

        def _wait(self, spec, variance=0.0):
            if isinstance(spec, tuple):
                center = spec[0]
                spread = spec[1] if len(spec) > 1 else center * 0.15
            else:
                center = float(spec)
                spread = center * 0.15
            sigma = spread / center if center > 0 else 0.15
            actual = max(0.05, center * random.lognormvariate(0, sigma))
            time.sleep(actual)
            return actual

        def _grab(self):
            return sc.grab_full()

        def _find(self, template, threshold=0.65):
            frame = sc.grab_full()
            if frame is None:
                return None
            m = matcher.match_single(frame, template)
            if m and m.confidence >= threshold:
                return m
            return None

        def _close_panel(self, panel):
            _dismiss_panel(self)
            time.sleep(random.uniform(0.2, 0.5))

    ctx = TestCtx()
    pa = PlayerActions(ctx, {"preferred_idle": sorted(ALL_ACTIONS), "hesitation_level": 0})

    # Determine which actions to run
    actions_to_run = []
    if args.action:
        for name in args.action.split(","):
            name = name.strip()
            if name not in ACTION_REGISTRY:
                print(f"Unknown action: {name}")
                print(f"Available: {', '.join(sorted(ACTION_REGISTRY.keys()))}")
                return
            actions_to_run.append(name)
    elif args.random:
        pool = sorted(ACTION_REGISTRY.keys())
        actions_to_run = [random.choice(pool) for _ in range(args.random)]
    elif args.all:
        actions_to_run = sorted(ACTION_REGISTRY.keys())
    else:
        print("Specify --action, --random N, --all, or --list")
        return

    print(f"\nRunning {len(actions_to_run)} action(s): {', '.join(actions_to_run)}\n")

    for i, name in enumerate(actions_to_run):
        print(f"--- [{i+1}/{len(actions_to_run)}] {name} ---")
        try:
            ok = pa.do(name)
            status = "OK" if ok else "SKIPPED"
        except Exception as e:
            status = f"ERROR: {e}"
        print(f"  Result: {status}")
        if i < len(actions_to_run) - 1:
            time.sleep(args.delay)

    print(f"\nDone. History: {pa.history}")

    cmd.stop()
    conn.disconnect()


if __name__ == "__main__":
    _cli_main()
