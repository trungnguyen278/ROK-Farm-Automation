from __future__ import annotations

import json
import logging
import random
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PROFILE: dict = {
    "name": "default",
    "mouse": {
        "bezier_control_points": 3,
        "speed_base": 400,
        "speed_variance": 150,
        "overshoot_chance": 0.15,
        "overshoot_distance": [5, 15],
        "misclick_chance": 0.01,
        "click_spread": 8,
        "hold_ms": [50, 150],
        "jitter_px": 2,
    },
    "timing": {
        "action_delay_mean": 1200,
        "action_delay_std": 400,
        "micro_pause_chance": 0.2,
        "micro_pause_range": [2000, 5000],
        "typing_delay": [30, 120],
    },
    "session": {
        "farm_duration_mean": 25,
        "farm_duration_std": 8,
        "break_duration_mean": 8,
        "break_duration_std": 3,
        "daily_hours_max": 6,
        "active_window": ["08:00", "23:00"],
        "idle_action_chance": 0.08,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


class ProfileLoader:
    def __init__(self, profile_dir: str = "profiles/"):
        self._dir = Path(profile_dir)

    def load(self, name: str) -> dict:
        path = self._dir / f"{name}.json"
        if not path.exists():
            logger.warning("Profile %s not found, using defaults", name)
            return DEFAULT_PROFILE.copy()

        with open(path, encoding="utf-8") as f:
            raw = json.load(f)

        profile = _deep_merge(DEFAULT_PROFILE, raw)
        profile["name"] = raw.get("name", name)
        logger.info("Loaded profile: %s", profile["name"])
        return profile

    def load_random(self) -> dict:
        names = self.list_profiles()
        if not names:
            return DEFAULT_PROFILE.copy()
        return self.load(random.choice(names))

    def list_profiles(self) -> list[str]:
        if not self._dir.exists():
            return []
        return [p.stem for p in self._dir.glob("*.json")]
