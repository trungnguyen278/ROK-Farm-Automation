from __future__ import annotations

import logging
from enum import Enum

import numpy as np

from .template_matcher import Match, TemplateMatcher

logger = logging.getLogger(__name__)


class GameScreen(Enum):
    UNKNOWN = "unknown"
    CITY_VIEW = "city_view"
    WORLD_MAP = "world_map"
    MARCH_SCREEN = "march_screen"
    POPUP_DIALOG = "popup_dialog"
    COMMANDER_SELECT = "commander_select"
    ALLIANCE_SCREEN = "alliance_screen"


SCREEN_TEMPLATES: dict[GameScreen, list[str]] = {
    GameScreen.CITY_VIEW: ["states/city_view"],
    GameScreen.WORLD_MAP: ["states/world_map"],
    GameScreen.MARCH_SCREEN: ["states/march_screen"],
    GameScreen.POPUP_DIALOG: ["popups/march_confirm", "popups/scout_report"],
    GameScreen.COMMANDER_SELECT: ["states/commander_select"],
    GameScreen.ALLIANCE_SCREEN: ["states/alliance_screen"],
}


class StateDetector:
    def __init__(self, matcher: TemplateMatcher, min_confidence: float = 0.8):
        self._matcher = matcher
        self._min_confidence = min_confidence

    def detect(self, frame: np.ndarray) -> GameScreen:
        best_screen = GameScreen.UNKNOWN
        best_conf = 0.0

        for screen, templates in SCREEN_TEMPLATES.items():
            try:
                match = self._matcher.match_best(frame, templates)
            except Exception:
                logger.debug("Template match failed for %s", screen.value, exc_info=True)
                continue
            if match and match.confidence > best_conf:
                best_conf = match.confidence
                best_screen = screen

        if best_conf < self._min_confidence:
            return GameScreen.UNKNOWN

        logger.debug("Detected: %s (%.2f)", best_screen.value, best_conf)
        return best_screen

    def detect_with_match(
        self, frame: np.ndarray
    ) -> tuple[GameScreen, Match | None]:
        best_screen = GameScreen.UNKNOWN
        best_match: Match | None = None

        for screen, templates in SCREEN_TEMPLATES.items():
            try:
                match = self._matcher.match_best(frame, templates)
            except Exception:
                logger.debug("Template match failed for %s", screen.value, exc_info=True)
                continue
            if match and (best_match is None or match.confidence > best_match.confidence):
                best_match = match
                best_screen = screen

        if best_match and best_match.confidence < self._min_confidence:
            return GameScreen.UNKNOWN, None

        return best_screen, best_match
