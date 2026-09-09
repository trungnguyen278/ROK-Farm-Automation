"""Per-account persona: stable, slightly unique motor/behaviour traits.

The persona is stored outside the repo (``%APPDATA%/.rok_data/<hash>.dat``) and
survives across runs, so the same account always moves the same way instead of
re-rolling human traits every session.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
from datetime import datetime
from pathlib import Path

from anti_detection.player_actions import PlayerActions

from rok_farm.logging_setup import logger


class PersonaMixin:
    """Persona load/save/apply. Mixed into GemFarmRunner."""

    # --- Persistent persona ---

    def _persona_path(self) -> Path:
        base = Path(os.environ.get("APPDATA", Path.home())) / ".rok_data"
        base.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256(self._account_id.encode()).hexdigest()[:12]
        return base / f"{h}.dat"

    def _load_or_create_persona(self) -> dict:
        path = self._persona_path()
        if path.exists():
            try:
                with open(path, "r") as f:
                    persona = json.load(f)
                persona.setdefault("session_count", 0)
                persona["session_count"] += 1
                if persona["session_count"] % 20 == 0:
                    persona["speed_base"] = max(1200, min(2000,
                        persona["speed_base"] + random.randint(-30, 30)))
                    persona["curve_spread"] = max(0.03, min(0.10,
                        persona["curve_spread"] + random.uniform(-0.01, 0.01)))
                with open(path, "w") as f:
                    json.dump(persona, f, indent=2)
                logger.info("Loaded persona: %s (session #%d)", path.name,
                            persona["session_count"])
                return persona
            except Exception as e:
                logger.warning("Failed to load persona %s: %s", path, e)

        persona = {
            "speed_base": random.randint(1300, 1800),
            "speed_variance": random.randint(50, 120),
            "curve_spread": round(random.uniform(0.03, 0.08), 3),
            "overshoot_chance": round(random.uniform(0.02, 0.06), 3),
            "click_bias_x": round(random.gauss(0, 0.015), 4),
            "click_bias_y": round(random.gauss(0, 0.012), 4),
            "scroll_overshoot": round(random.uniform(0.08, 0.25), 3),
            "hesitation_level": round(random.uniform(0.02, 0.12), 3),
            "fatigue_sensitivity": round(random.uniform(0.7, 1.3), 2),
            "afk_frequency": round(random.uniform(0.02, 0.08), 3),
            "bezier_points": 2,
            "jitter_px": 0,
            "preferred_idle": PlayerActions.focused_farmer_preferred(),
            "session_count": 1,
            "created": datetime.now().isoformat(),
        }
        try:
            with open(path, "w") as f:
                json.dump(persona, f, indent=2)
            logger.info("Created new persona: %s", path.name)
        except Exception as e:
            logger.warning("Failed to save persona: %s", e)
        return persona

    def _save_persona(self):
        try:
            with open(self._persona_path(), "w") as f:
                json.dump(self._persona, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save persona: %s", e)

    @staticmethod
    def _jitter(value: float, pct: float = 0.06) -> float:
        return value * random.uniform(1 - pct, 1 + pct)

    def _apply_persona(self):
        p = self._persona
        self._profile.setdefault("mouse", {})
        self._profile["mouse"]["speed_base"] = int(self._jitter(p["speed_base"]))
        self._profile["mouse"]["speed_variance"] = int(self._jitter(p["speed_variance"]))
        self._profile["mouse"]["bezier_control_points"] = p["bezier_points"]
        self._profile["mouse"]["jitter_px"] = p["jitter_px"]
        self._profile["mouse"]["curve_spread"] = self._jitter(p["curve_spread"])
        self._profile["mouse"]["overshoot_chance"] = self._jitter(p["overshoot_chance"])
