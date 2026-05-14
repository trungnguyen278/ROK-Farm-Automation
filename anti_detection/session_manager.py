from __future__ import annotations

import random
import time
from datetime import datetime
from enum import Enum


class IdleAction(Enum):
    PAN_MAP = "pan_map"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    CHECK_ALLIANCE = "check_alliance"


class SessionManager:
    def __init__(self, profile: dict):
        s = profile.get("session", {})
        self._farm_mean = s.get("farm_duration_mean", 25)
        self._farm_std = s.get("farm_duration_std", 8)
        self._break_mean = s.get("break_duration_mean", 8)
        self._break_std = s.get("break_duration_std", 3)
        self._daily_max = s.get("daily_hours_max", 6)
        self._active_window = s.get("active_window", ["08:00", "23:00"])
        self._idle_chance = s.get("idle_action_chance", 0.08)

        self._session_start: float = time.monotonic()
        self._daily_start: float = time.monotonic()
        self._daily_active_seconds: float = 0.0
        self._current_farm_duration: float = self._roll_farm_duration()
        self._on_break: bool = False
        self._break_end: float = 0.0
        self._action_count: int = 0

    def should_take_break(self) -> bool:
        if self._on_break:
            if time.monotonic() >= self._break_end:
                self._on_break = False
                self._session_start = time.monotonic()
                self._current_farm_duration = self._roll_farm_duration()
                return False
            return True

        elapsed = (time.monotonic() - self._session_start) / 60.0
        if elapsed >= self._current_farm_duration:
            self._start_break()
            return True

        return False

    def get_break_duration(self) -> float:
        if self._on_break:
            remaining = max(0, self._break_end - time.monotonic())
            return remaining
        dur = max(60, random.gauss(self._break_mean * 60, self._break_std * 60))
        return dur

    def should_stop_daily(self) -> bool:
        self._update_daily_active()
        if self._daily_active_seconds / 3600.0 >= self._daily_max:
            return True
        return not self._in_active_window()

    def get_idle_action(self) -> IdleAction | None:
        if random.random() >= self._idle_chance:
            return None
        return random.choice(list(IdleAction))

    def record_action(self):
        self._action_count += 1

    @property
    def elapsed_minutes(self) -> float:
        return (time.monotonic() - self._session_start) / 60.0

    def session_stats(self) -> dict:
        self._update_daily_active()
        return {
            "session_minutes": round(self.elapsed_minutes, 1),
            "daily_active_hours": round(self._daily_active_seconds / 3600.0, 2),
            "daily_max_hours": self._daily_max,
            "on_break": self._on_break,
            "action_count": self._action_count,
            "current_farm_target_min": round(self._current_farm_duration, 1),
        }

    def reset(self):
        self._session_start = time.monotonic()
        self._current_farm_duration = self._roll_farm_duration()
        self._on_break = False
        self._action_count = 0

    def reset_daily(self):
        self._daily_start = time.monotonic()
        self._daily_active_seconds = 0.0
        self.reset()

    def _roll_farm_duration(self) -> float:
        return max(1, random.gauss(self._farm_mean, self._farm_std))

    def _start_break(self):
        dur = self.get_break_duration()
        self._on_break = True
        self._break_end = time.monotonic() + dur

    def _update_daily_active(self):
        if not self._on_break:
            self._daily_active_seconds = time.monotonic() - self._daily_start

    def _in_active_window(self) -> bool:
        if len(self._active_window) < 2:
            return True
        now = datetime.now().strftime("%H:%M")
        start, end = self._active_window
        if start <= end:
            return start <= now <= end
        return now >= start or now <= end
