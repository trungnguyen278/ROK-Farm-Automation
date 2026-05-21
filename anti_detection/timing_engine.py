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


