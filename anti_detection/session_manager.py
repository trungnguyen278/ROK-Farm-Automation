from __future__ import annotations

import random
import time
from datetime import datetime, timedelta
from enum import Enum


class IdleAction(Enum):
    PAN_MAP = "pan_map"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    CHECK_ALLIANCE = "check_alliance"
    ALT_TAB = "alt_tab"


class NightSchedule:
    def __init__(self, config: dict):
        self._bed_time_str = config.get("bed_time", "01:00")
        self._wake_time_str = config.get("wake_time", "07:00")
        self._stop_margin_min = config.get("stop_margin_min", 30)
        self._jitter_start_min = config.get("jitter_start_min", 20)
        self._jitter_stop_min = config.get("jitter_stop_min", 15)
        self._day_variance_min = config.get("day_variance_min", 10)

        self._actual_start: datetime | None = None
        self._actual_stop: datetime | None = None

    def compute_tonight(self, day_drift: float = 0.0) -> dict:
        now = datetime.now()
        bed_h, bed_m = map(int, self._bed_time_str.split(":"))
        wake_h, wake_m = map(int, self._wake_time_str.split(":"))

        bed_base = now.replace(hour=bed_h, minute=bed_m, second=0, microsecond=0)
        wake_base = now.replace(hour=wake_h, minute=wake_m, second=0, microsecond=0)

        if bed_base > wake_base:
            wake_base += timedelta(days=1)
        if bed_base < now - timedelta(hours=2):
            bed_base += timedelta(days=1)
            wake_base += timedelta(days=1)

        start_jitter = self._clamp_gauss(0, self._jitter_start_min / 2,
                                         self._jitter_start_min)
        stop_jitter = self._clamp_gauss(0, self._jitter_stop_min / 2,
                                        self._jitter_stop_min)

        self._actual_start = bed_base + timedelta(minutes=day_drift + start_jitter)
        raw_stop = wake_base - timedelta(minutes=self._stop_margin_min)
        self._actual_stop = raw_stop + timedelta(minutes=day_drift * 0.5 + stop_jitter)

        if self._actual_stop <= self._actual_start:
            self._actual_stop = self._actual_start + timedelta(hours=3)

        return {
            "actual_start": self._actual_start,
            "actual_stop": self._actual_stop,
        }

    def is_active_now(self) -> bool:
        if self._actual_start is None or self._actual_stop is None:
            return False
        now = datetime.now()
        return self._actual_start <= now <= self._actual_stop

    def time_progress(self) -> float:
        if self._actual_start is None or self._actual_stop is None:
            return 0.0
        now = datetime.now()
        total = (self._actual_stop - self._actual_start).total_seconds()
        if total <= 0:
            return 0.0
        elapsed = (now - self._actual_start).total_seconds()
        return max(0.0, min(1.0, elapsed / total))

    def minutes_until_start(self) -> float:
        if self._actual_start is None:
            return 0.0
        delta = (self._actual_start - datetime.now()).total_seconds()
        return max(0.0, delta / 60.0)

    def schedule_summary(self) -> dict:
        fmt = "%H:%M"
        return {
            "start": self._actual_start.strftime(fmt) if self._actual_start else "?",
            "stop": self._actual_stop.strftime(fmt) if self._actual_stop else "?",
        }

    @staticmethod
    def update_day_drift(current_drift: float, variance: float) -> float:
        new_drift = current_drift + random.gauss(0, variance / 3)
        return max(-variance, min(variance, new_drift))

    @staticmethod
    def _clamp_gauss(mu: float, sigma: float, limit: float) -> float:
        v = random.gauss(mu, sigma)
        return max(-limit, min(limit, v))


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
        # A break long enough that a real player would CLOSE the game rather
        # than leave it sitting there. Without one of these the client stays
        # logged in for the whole session: breaks are drawn from
        # gauss(break_duration_mean, ...) which for this profile is 2 minutes,
        # and the quit/relaunch path only triggers at RESTART_BREAK_MINUTES
        # (30), so it was mathematically unreachable -- the game was never once
        # closed across a ten-hour day. That, not the clicking, is the part a
        # human never does. Defaults sit clear of the 30min quit threshold.
        self._long_break_chance = s.get("long_break_chance", 0.25)
        self._long_break_min = s.get("long_break_min_minutes", 35)
        self._long_break_max = s.get("long_break_max_minutes", 110)

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
        # Occasionally stop properly instead of taking another breather. The
        # caller quits the client for any break past RESTART_BREAK_MINUTES, so
        # this is what actually gets the game closed during a long day.
        if random.random() < self._long_break_chance:
            return random.uniform(self._long_break_min * 60,
                                  self._long_break_max * 60)
        dur = max(60, random.gauss(self._break_mean * 60, self._break_std * 60))
        return dur

    def should_stop_daily(self) -> bool:
        self._update_daily_active()
        if self._daily_active_seconds / 3600.0 >= self._daily_max:
            return True
        return not self._in_active_window()

    _DAY_IDLE_ACTIONS = [
        IdleAction.PAN_MAP, IdleAction.ZOOM_IN, IdleAction.ZOOM_OUT,
        IdleAction.CHECK_ALLIANCE, IdleAction.ALT_TAB,
    ]

    def get_idle_action(self) -> IdleAction | None:
        if random.random() >= self._idle_chance:
            return None
        return random.choice(self._DAY_IDLE_ACTIONS)

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

    def in_active_window(self) -> bool:
        """Public: is now inside the persona's declared playing hours?

        `should_stop_daily` already answered this but was never called from
        anywhere -- so the profile advertised 09:00-22:00 while the bot farmed
        straight through the night. A persona whose stated habits and actual
        habits disagree is worse than no persona at all.
        """
        return self._in_active_window()

    def seconds_until_active_window(self) -> float:
        """How long until the play window opens again (0 if it is open)."""
        if self._in_active_window():
            return 0.0
        if len(self._active_window) < 2:
            return 0.0
        now = datetime.now()
        h, m = (int(x) for x in self._active_window[0].split(":"))
        start = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if start <= now:
            start += timedelta(days=1)
        return max(0.0, (start - now).total_seconds())

    def _in_active_window(self) -> bool:
        if len(self._active_window) < 2:
            return True
        now = datetime.now().strftime("%H:%M")
        start, end = self._active_window
        if start <= end:
            return start <= now <= end
        return now >= start or now <= end
