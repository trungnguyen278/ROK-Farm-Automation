"""Layer 1: work out what is on screen from the pixels alone.

Free, instant, no network. Answers two questions the flow keeps needing:

    is something covering the game?   -> the background dims behind a modal
    city or world map?                -> one template, not a margin comparison

Every threshold here was measured on the live client; see the table in
config.py. A third question -- "is the client frozen?" -- was attempted from
frame motion and removed once the measurements showed the world map at icon zoom
sits at 0.001, i.e. a healthy screen is indistinguishable from a dead one. The
reasoning is kept in config.py so it is not rebuilt by accident.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from rok_farm.config import (CITY_WMCB_MIN, MODAL_RATIO_MIN,
                             ORACLE_ESCALATE_BELOW, WORLD_CITY_BTN_MIN)
from rok_farm.logging_setup import INFO

ACTIVITY_SIZE = (160, 90)


@dataclass(frozen=True)
class ScreenState:
    """What the local probe believes, plus how sure it is."""

    view: str           # "city" | "world_map" | "unknown"
    overlay: str        # "none" | "modal" | "unknown"
    confidence: float   # 0..1; below ORACLE_ESCALATE_BELOW asks layer 2
    note: str = ""

    @property
    def blocked(self) -> bool:
        return self.overlay == "modal"


def dim_ratio(frame: np.ndarray) -> float:
    """Centre brightness over border brightness.

    ROK darkens everything behind a modal, so a covered screen has a bright
    panel in the middle and a dark rim. Measured: 1.06-1.18 clean, 4.97 with the
    bag open (border brightness fell from ~130 to 22.9).
    """
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mx, my = int(w * 0.10), int(h * 0.10)
    ring = np.ones(gray.shape, dtype=bool)
    ring[my:h - my, mx:w - mx] = False
    centre = gray[int(h * 0.22):int(h * 0.78), int(w * 0.28):int(w * 0.72)]
    border_mean = float(gray[ring].mean())
    if border_mean <= 0:
        return 0.0
    return float(centre.mean()) / border_mean


class StateProbeMixin:
    """Local screen-state reasoning. Mixed into GemFarmRunner."""

    def _probe_state(self, frame=None) -> ScreenState:
        """Read the current screen without touching the network."""
        if frame is None:
            frame = self._grab()
        if frame is None:
            return ScreenState("unknown", "unknown", confidence=0.0,
                               note="no frame")

        ratio = dim_ratio(frame)
        if ratio >= MODAL_RATIO_MIN:
            # Something is covering the game. What is behind it cannot be read
            # and does not matter: the action is to clear it either way.
            return ScreenState("unknown", "modal", confidence=0.85,
                               note=f"dim {ratio:.2f}")

        # --- city or world map? ---
        raw = self._raw_frame if self._raw_frame is not None else frame
        wmcb = self._find_on_frame(raw, "buttons/world_map_city_btn", threshold=0.0)
        city_btn = self._find_on_frame(raw, "buttons/city_btn", threshold=0.0)
        wmcb_conf = wmcb.confidence if wmcb else 0.0
        city_conf = city_btn.confidence if city_btn else 0.0

        if wmcb_conf >= CITY_WMCB_MIN:
            view, conf = "city", min(1.0, wmcb_conf)
        elif city_conf >= WORLD_CITY_BTN_MIN:
            view, conf = "world_map", min(1.0, city_conf)
        else:
            view, conf = "unknown", max(wmcb_conf, city_conf)

        note = (f"dim {ratio:.2f} wmcb {wmcb_conf:.3f} "
                f"city_btn {city_conf:.3f}")
        return ScreenState(view, "none", confidence=conf, note=note)

    # --- escalation to layer 2 ---

    def _needs_oracle(self, state: ScreenState) -> bool:
        """Layer 1 is unsure enough to be worth a network call."""
        if state.overlay == "modal":
            # The dim ratio settles this locally, and the view BEHIND a modal is
            # both unknowable and irrelevant -- the action is "clear it" either
            # way. Escalating here would spend a call and let the model overrule
            # a measurement that is not in doubt.
            return False
        return state.view == "unknown" or state.confidence < ORACLE_ESCALATE_BELOW

    def _resolve_state(self, frame=None, reason: str = "") -> ScreenState:
        """Layer 1, escalated to layer 2 only when layer 1 cannot tell.

        The model's answer replaces what it can actually see (the view and what
        covers it) and never overrides `alive`, which is a timing judgement the
        model has no way to make from a single frame.
        """
        state = self._probe_state(frame)
        if not self._needs_oracle(state):
            return state

        oracle = getattr(self, "oracle", None)
        if oracle is None or not oracle.enabled:
            return state

        if frame is None:
            frame = self._raw_frame
        verdict = oracle.classify_state(frame) if frame is not None else None
        if verdict is None:
            return state

        print(f"  [{INFO}] Oracle[{verdict.source}]: view={verdict.view} "
              f"overlay={verdict.overlay} (local was {state.view}/"
              f"{state.overlay} @ {state.confidence:.2f}{', ' + reason if reason else ''})")
        overlay = "modal" if verdict.blocked else "none"
        return ScreenState(view=verdict.view, overlay=overlay, confidence=0.8,
                           note=f"{state.note} | oracle:{verdict.source}")
