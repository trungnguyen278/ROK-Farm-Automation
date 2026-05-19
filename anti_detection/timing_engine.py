from __future__ import annotations

import math
import random


class TimingEngine:
    def __init__(self, profile: dict):
        t = profile.get("timing", {})
        self._delay_mean = t.get("action_delay_mean", 1200)
        self._delay_std = t.get("action_delay_std", 400)
        self._pause_chance = t.get("micro_pause_chance", 0.05)
        self._pause_range = t.get("micro_pause_range", [200, 800])
        self._typing_delay = t.get("typing_delay", [30, 120])

    def action_delay(self) -> float:
        delay = random.gauss(self._delay_mean, self._delay_std)
        return max(100, delay) / 1000.0

    def micro_pause(self) -> float | None:
        if random.random() >= self._pause_chance:
            return None
        lo, hi = self._pause_range
        return random.uniform(lo, hi) / 1000.0

    def typing_delay(self) -> float:
        lo, hi = self._typing_delay
        return random.uniform(lo, hi) / 1000.0

    def apply_fatigue(self, session_minutes: float) -> float:
        t = session_minutes / 60.0
        base = 1.0 + 0.3 * (1.0 / (1.0 + math.exp(-6.0 * (t - 0.4))))
        return base * random.uniform(0.9, 1.15)

    def apply_night_fatigue(self, session_minutes: float,
                            time_progress: float,
                            is_transition: bool = False) -> float:
        if is_transition:
            base = 0.95 + 0.15 * time_progress
        elif time_progress < 0.3:
            base = 1.0 + 1.0 * (time_progress / 0.3)
        elif time_progress < 0.7:
            t = (time_progress - 0.3) / 0.4
            base = 1.3 + 0.5 * t
        elif time_progress < 0.9:
            t = (time_progress - 0.7) / 0.2
            base = 1.8 + 0.7 * t
        else:
            t = (time_progress - 0.9) / 0.1
            base = 2.5 + 1.5 * min(t, 1.0)

        session_fatigue = 1.0 + 0.15 * (
            1.0 / (1.0 + math.exp(-6.0 * (session_minutes / 60.0 - 0.4))))
        combined = base * session_fatigue

        noise_scale = 0.05 + 0.10 * time_progress
        combined *= random.uniform(1.0 - noise_scale, 1.0 + noise_scale)
        return combined

    def night_micro_pause(self, time_progress: float) -> float | None:
        chance = self._pause_chance + 0.20 * time_progress
        if random.random() >= chance:
            return None
        lo, hi = self._pause_range
        scale = 1.0 + 2.0 * time_progress
        return random.uniform(lo * scale, hi * scale) / 1000.0

    def should_micro_sleep(self, time_progress: float) -> float | None:
        if time_progress < 0.3:
            return None
        chance = 0.01 + 0.04 * time_progress
        if random.random() >= chance:
            return None
        duration = random.lognormvariate(2.3, 0.6)
        return min(60.0, max(5.0, duration))
