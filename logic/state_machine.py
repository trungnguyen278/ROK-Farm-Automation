from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Callable

from vision.state_detector import GameScreen

logger = logging.getLogger(__name__)


class GameState(Enum):
    INIT = "init"
    CITY_VIEW = "city_view"
    WORLD_MAP = "world_map"
    MARCHING = "marching"
    POPUP = "popup"
    COMMANDER_SELECT = "commander"
    LOADING = "loading"
    DISCONNECTED = "disconnected"
    IDLE = "idle"
    ERROR = "error"


SCREEN_TO_STATE: dict[GameScreen, GameState] = {
    GameScreen.CITY_VIEW: GameState.CITY_VIEW,
    GameScreen.WORLD_MAP: GameState.WORLD_MAP,
    GameScreen.MARCH_SCREEN: GameState.MARCHING,
    GameScreen.POPUP_DIALOG: GameState.POPUP,
    GameScreen.COMMANDER_SELECT: GameState.COMMANDER_SELECT,
    GameScreen.ALLIANCE_SCREEN: GameState.CITY_VIEW,
}

VALID_TRANSITIONS: dict[GameState, set[GameState]] = {
    GameState.INIT: {GameState.CITY_VIEW, GameState.WORLD_MAP, GameState.DISCONNECTED},
    GameState.CITY_VIEW: {
        GameState.WORLD_MAP, GameState.COMMANDER_SELECT,
        GameState.POPUP, GameState.LOADING, GameState.DISCONNECTED,
        GameState.IDLE, GameState.ERROR,
    },
    GameState.WORLD_MAP: {
        GameState.CITY_VIEW, GameState.MARCHING,
        GameState.POPUP, GameState.LOADING, GameState.DISCONNECTED,
        GameState.IDLE, GameState.ERROR,
    },
    GameState.MARCHING: {
        GameState.CITY_VIEW, GameState.WORLD_MAP,
        GameState.POPUP, GameState.LOADING, GameState.DISCONNECTED,
        GameState.IDLE, GameState.ERROR,
    },
    GameState.POPUP: {
        GameState.CITY_VIEW, GameState.WORLD_MAP, GameState.MARCHING,
        GameState.COMMANDER_SELECT, GameState.LOADING, GameState.DISCONNECTED,
        GameState.IDLE, GameState.ERROR,
    },
    GameState.COMMANDER_SELECT: {
        GameState.MARCHING, GameState.CITY_VIEW,
        GameState.POPUP, GameState.LOADING, GameState.DISCONNECTED,
        GameState.IDLE, GameState.ERROR,
    },
    GameState.LOADING: {
        GameState.CITY_VIEW, GameState.WORLD_MAP, GameState.MARCHING,
        GameState.POPUP, GameState.COMMANDER_SELECT, GameState.DISCONNECTED,
        GameState.IDLE, GameState.ERROR,
    },
    GameState.DISCONNECTED: {GameState.INIT},
    GameState.IDLE: {
        GameState.CITY_VIEW, GameState.WORLD_MAP,
        GameState.DISCONNECTED, GameState.ERROR,
    },
    GameState.ERROR: {
        GameState.CITY_VIEW, GameState.WORLD_MAP, GameState.MARCHING,
        GameState.POPUP, GameState.COMMANDER_SELECT,
        GameState.DISCONNECTED, GameState.IDLE,
    },
}


class StateMachine:
    def __init__(self, unknown_state_timeout: float = 5.0):
        self._state = GameState.INIT
        self._previous_state = GameState.INIT
        self._state_entered_at = time.monotonic()
        self._unknown_since: float | None = None
        self._unknown_timeout = unknown_state_timeout
        self._listeners: list[Callable[[GameState, GameState], None]] = []

    @property
    def state(self) -> GameState:
        return self._state

    @property
    def previous_state(self) -> GameState:
        return self._previous_state

    @property
    def state_entered_at(self) -> float:
        return self._state_entered_at

    def time_in_state(self) -> float:
        return time.monotonic() - self._state_entered_at

    def add_listener(self, callback: Callable[[GameState, GameState], None]):
        self._listeners.append(callback)

    def update(self, screen: GameScreen | None) -> GameState:
        if screen is None:
            self._handle_disconnected()
            return self._state

        if screen == GameScreen.UNKNOWN:
            self._handle_unknown()
            return self._state

        self._unknown_since = None
        target = SCREEN_TO_STATE.get(screen)
        if target and target != self._state:
            self._transition(target)

        return self._state

    def force_state(self, target: GameState):
        if target != self._state:
            self._transition(target)

    def can_transition(self, target: GameState) -> bool:
        return target in VALID_TRANSITIONS.get(self._state, set())

    def _transition(self, target: GameState):
        if not self.can_transition(target):
            logger.warning(
                "Invalid transition %s -> %s, forcing",
                self._state.value, target.value,
            )

        old = self._state
        self._previous_state = old
        self._state = target
        self._state_entered_at = time.monotonic()
        logger.info("State: %s -> %s", old.value, target.value)

        for cb in self._listeners:
            try:
                cb(old, target)
            except Exception:
                logger.exception("State listener error")

    def _handle_disconnected(self):
        if self._state != GameState.DISCONNECTED:
            self._transition(GameState.DISCONNECTED)

    def _handle_unknown(self):
        now = time.monotonic()
        if self._unknown_since is None:
            self._unknown_since = now
            return

        if now - self._unknown_since >= self._unknown_timeout:
            if self._state != GameState.ERROR:
                self._transition(GameState.ERROR)
