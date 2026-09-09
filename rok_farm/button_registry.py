"""Where a fixed button has always been -- and rejecting clicks that stray.

Template matching is stateless: each match returns the best hit on one frame,
with no memory of where that button has ever been. That is fine for things that
move (gem icons, mines) and dangerous for things that do not: a rare event icon
once out-scored the real `city_btn` from the opposite corner, and two paths still
match the whole frame and then click the result
(`_step_click_gather`, `_check_reconnect_popup`).

Fixed UI buttons land in the same place every time. So record where each one has
been, as a fraction of the window, and reject a detection that suddenly appears
far outside its own history. Each button calibrates its own tolerance: a truly
fixed button ends up with a tight gate, one that rides on a popup ends up with a
loose one -- no hand-tuned regions.

The registry starts empty and learns from a normal run: the first
REGISTRY_WARMUP detections of a button are only recorded, never rejected.
"""

from __future__ import annotations

import json
import math
from datetime import datetime

from rok_farm.config import (REGISTRY_ENABLED, REGISTRY_FILE,
                             REGISTRY_MIN_RADIUS, REGISTRY_SIGMA,
                             REGISTRY_WARMUP)
from rok_farm.logging_setup import logger

# Templates whose on-screen position is fixed by the UI. Anything that moves with
# the world (gem icons, mines, the occupied pickaxe) must NOT be listed here.
FIXED_BUTTONS = frozenset({
    "buttons/gather_btn",
    "buttons/city_btn",
    "buttons/world_map_city_btn",
    "buttons/new_troop_btn",
    "buttons/march_btn",
    "buttons/march_btn_orange",
    "ui/btn_confirm_reconnect",
    "ui/btn_confirm_reward",
    "ui/btn_confirm_alliance",
    "ui/btn_mail",
    "ui/btn_alliance",
    "ui/btn_alliance_gift",
    "ui/btn_claim_all",
    "ui/btn_x_close_mail",
    "ui/btn_x_close_alliance",
    "ui/btn_x_close_alliance_gift",
    "ui/btn_x_close_bag",
    "ui/mail_close_btn",
    "ui/chat_close_btn",
})

SAVE_EVERY = 10


class ButtonRegistry:
    """Running position statistics per fixed button, persisted as JSON."""

    def __init__(self, path=REGISTRY_FILE):
        self._path = path
        self._data: dict[str, dict] = {}
        self._since_save = 0
        self.load()

    # --- persistence ---

    def load(self):
        try:
            if self._path.exists():
                self._data = json.loads(self._path.read_text(encoding="utf-8-sig"))
                logger.info("Button registry: %d button(s) known", len(self._data))
        except Exception as e:
            logger.warning("Cannot read button registry %s: %s", self._path, e)
            self._data = {}

    def save(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, indent=2),
                                  encoding="utf-8")
            self._since_save = 0
        except Exception as e:
            logger.warning("Cannot write button registry %s: %s", self._path, e)

    # --- helpers ---

    @staticmethod
    def is_fixed(template: str) -> bool:
        return template in FIXED_BUTTONS

    @staticmethod
    def to_window_pct(sx: int, sy: int, win: dict) -> tuple[float, float] | None:
        """Screen point -> fraction of the client area."""
        if not win or not win.get("width") or not win.get("height"):
            return None
        return ((sx - win["left"]) / win["width"],
                (sy - win["top"]) / win["height"])

    def stats(self, template: str) -> dict | None:
        return self._data.get(template)

    def radius(self, template: str) -> float | None:
        """Current reject radius, or None while still warming up."""
        e = self._data.get(template)
        if not e or e["n"] < REGISTRY_WARMUP:
            return None
        sx, sy = self._std(e)
        return max(REGISTRY_MIN_RADIUS, REGISTRY_SIGMA * math.hypot(sx, sy))

    @staticmethod
    def _std(entry: dict) -> tuple[float, float]:
        n = entry["n"]
        if n < 2:
            return 0.0, 0.0
        return (math.sqrt(max(0.0, entry["m2"][0] / (n - 1))),
                math.sqrt(max(0.0, entry["m2"][1] / (n - 1))))

    # --- the check ---

    def check(self, template: str, pct: tuple[float, float]) -> tuple[bool, str]:
        """Should a click on this detection be allowed?

        Accepts anything that is not a registered fixed button, and anything
        still inside the warmup window -- an empty registry never blocks a run.
        """
        if not REGISTRY_ENABLED or not self.is_fixed(template):
            return True, "not policed"
        entry = self._data.get(template)
        if not entry or entry["n"] < REGISTRY_WARMUP:
            n = entry["n"] if entry else 0
            return True, f"warmup {n}/{REGISTRY_WARMUP}"

        dist = math.hypot(pct[0] - entry["mean"][0], pct[1] - entry["mean"][1])
        limit = self.radius(template) or REGISTRY_MIN_RADIUS
        if dist > limit:
            return False, (f"{dist:.3f} from mean "
                           f"({entry['mean'][0]:.3f},{entry['mean'][1]:.3f}), "
                           f"limit {limit:.3f}, n={entry['n']}")
        return True, f"{dist:.3f} <= {limit:.3f}"

    # --- learning ---

    def record(self, template: str, pct: tuple[float, float]):
        """Fold an accepted detection into the running mean/variance (Welford)."""
        if not REGISTRY_ENABLED or not self.is_fixed(template):
            return
        e = self._data.setdefault(template, {"n": 0, "mean": [0.0, 0.0],
                                             "m2": [0.0, 0.0], "last_seen": ""})
        e["n"] += 1
        for i in (0, 1):
            delta = pct[i] - e["mean"][i]
            e["mean"][i] += delta / e["n"]
            e["m2"][i] += delta * (pct[i] - e["mean"][i])
        e["last_seen"] = datetime.now().isoformat(timespec="seconds")

        self._since_save += 1
        if self._since_save >= SAVE_EVERY:
            self.save()

    def summary(self) -> list[str]:
        lines = []
        for name, e in sorted(self._data.items()):
            sx, sy = self._std(e)
            r = self.radius(name)
            lines.append(f"{name:32s} n={e['n']:4d} "
                         f"mean=({e['mean'][0]:.3f},{e['mean'][1]:.3f}) "
                         f"std=({sx:.3f},{sy:.3f}) "
                         f"radius={'warmup' if r is None else f'{r:.3f}'}")
        return lines
