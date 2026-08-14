"""Closing a popup the bot has no template for.

This is the only place a model-derived coordinate ever becomes a click, so it is
also where every guardrail lives. The rules, in the order they are applied:

  1. Only ever run when a modal is actually detected locally (the dim ratio),
     so there is a real thing to close.
  2. Try the LOCAL answer first -- close buttons learned on previous runs are
     matched with templates, which costs nothing.
  3. Ask the model only if that fails, and only for a DISMISS target. No
     gameplay click is ever derived from a model.
  4. Reject a point that lands in the deploy region, or outside the upper part
     of the screen where close buttons live.
  5. Verify by result, not by faith: a real dismissal makes the dimming go away.
     If it does not, stop -- never click around looking for the button.
  6. On success, save the crop so the next occurrence is handled locally.

Measured before building any of this (see SPEC_STATE_ORACLE.md): a
grounding-capable model put the close button within ~1% of the frame, while
Google Search AI Mode was 15.5% out and would have clicked a research node.
"""

from __future__ import annotations

import random
import time
from pathlib import Path

import cv2

from rok_farm.config import (DISMISS_CROP_PCT, DISMISS_DANGER_MARGIN,
                             DISMISS_MAX_Y_PCT, LEARNED_CLOSE_DIR,
                             MARCH_BTN_PCT, MODAL_RATIO_MIN, NEW_TROOP_BTN_PCT,
                             TEMPLATE_DIR)
from rok_farm.logging_setup import INFO, PASS, WARN, logger
from rok_farm.screenshots import save_screenshot
from rok_farm.state_probe import dim_ratio

LEARNED_PREFIX = "ui/learned"
DANGER_POINTS = (NEW_TROOP_BTN_PCT, MARCH_BTN_PCT)


class DismissMixin:
    """Close an unknown popup. Mixed into GemFarmRunner."""

    # --- guardrails ---

    @staticmethod
    def _in_danger_zone(pct_x: float, pct_y: float) -> str | None:
        """Deploy buttons. A misplaced click here marches troops."""
        for dx, dy in DANGER_POINTS:
            if (abs(pct_x - dx) < DISMISS_DANGER_MARGIN
                    and abs(pct_y - dy) < DISMISS_DANGER_MARGIN):
                return f"within {DISMISS_DANGER_MARGIN} of deploy button ({dx},{dy})"
        return None

    def _guard_dismiss_point(self, frame, point: tuple[int, int]) -> tuple[bool, str]:
        fh, fw = frame.shape[:2]
        x, y = point
        if not (0 <= x < fw and 0 <= y < fh):
            return False, f"({x},{y}) outside the frame"
        pct_x, pct_y = x / fw, y / fh
        danger = self._in_danger_zone(pct_x, pct_y)
        if danger:
            return False, danger
        if pct_y > DISMISS_MAX_Y_PCT:
            return False, (f"y={pct_y:.2f} below {DISMISS_MAX_Y_PCT} -- close "
                           f"buttons sit in the upper part of a panel")
        return True, f"ok at ({pct_x:.3f},{pct_y:.3f})"

    # --- learned templates ---

    @staticmethod
    def _learned_close_templates() -> list[str]:
        directory = Path(TEMPLATE_DIR) / "ui" / "learned"
        if not directory.exists():
            return []
        return [f"{LEARNED_PREFIX}/{p.stem}" for p in sorted(directory.glob("*.png"))]

    def _learn_close_button(self, frame, point: tuple[int, int]):
        """Save the crop around a close button that demonstrably worked."""
        fh, fw = frame.shape[:2]
        half = max(12, int(fw * DISMISS_CROP_PCT))
        x, y = point
        x1, y1 = max(0, x - half), max(0, y - half)
        x2, y2 = min(fw, x + half), min(fh, y + half)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return
        LEARNED_CLOSE_DIR.mkdir(parents=True, exist_ok=True)
        name = f"close_{int(time.time())}"
        path = LEARNED_CLOSE_DIR / f"{name}.png"
        cv2.imwrite(str(path), crop)
        print(f"  [{INFO}] Learned this close button -> {path.name}; the next one "
              f"is handled locally")
        logger.info("Learned close button %s at (%d,%d)", path.name, x, y)

    # --- the flow ---

    def _dismiss_modal(self) -> bool:
        """Close whatever is covering the game. Returns True only if it went away."""
        frame = self._grab()
        if frame is None:
            return False
        before = dim_ratio(frame)
        if before < MODAL_RATIO_MIN:
            return False   # nothing is covering the game

        if self._dismiss_with_learned(frame, before):
            return True

        oracle = getattr(self, "oracle", None)
        if oracle is None or not oracle.enabled:
            return False

        point = oracle.locate_dismiss(frame)
        if point is None:
            return False

        ok, why = self._guard_dismiss_point(frame, point)
        if not ok:
            print(f"  [{WARN}] Refusing the located close button: {why}")
            logger.warning("Dismiss point rejected: %s", why)
            save_screenshot(frame, "dismiss_rejected")
            return False
        print(f"  [{INFO}] Located close button at {point} ({why})")

        sx, sy = self._screen_xy(*point)
        with self._pointer_scope(self.win):
            self._click(sx, sy)

        if not self._modal_cleared(before):
            # One shot only. A miss means the model was wrong about this popup,
            # and clicking around to find out would be exactly the "dumb click"
            # this whole path exists to avoid.
            print(f"  [{WARN}] Popup did not close -- leaving it to the flow")
            return False

        print(f"  [{PASS}] Popup closed")
        self._learn_close_button(frame, point)
        return True

    def _dismiss_with_learned(self, frame, before: float) -> bool:
        """Try close buttons learned on earlier runs. Free, no network."""
        for name in self._learned_close_templates():
            match = self._find_on_frame(frame, name, threshold=0.75)
            if not match:
                continue
            print(f"  [{INFO}] Known close button {name} (conf={match.confidence:.3f})")
            if not self._click_match(match):
                continue
            if self._modal_cleared(before):
                print(f"  [{PASS}] Popup closed with a learned button, no API call")
                return True
        return False

    def _modal_cleared(self, before: float) -> bool:
        """Did the dimming actually go away? The only honest success signal."""
        time.sleep(random.uniform(1.0, 2.0))
        after_frame = self._grab()
        if after_frame is None:
            return False
        after = dim_ratio(after_frame)
        logger.info("Dismiss check: dim ratio %.2f -> %.2f", before, after)
        return after < MODAL_RATIO_MIN
