"""A day's mood: the farm's own behavioural parameters, drifting.

Randomness with FIXED parameters is still a fixed fingerprint. A lognormal
click pause with constant mu and sigma is, over nine thousand samples, MORE
identifiable than a constant would be -- the parameters can be estimated to
several decimal places. What a person actually has is not randomness but
drift: tired today, hurried tomorrow, absorbed the day after.

Measured on this farm's own logs, 2026-09-22, the daily median click gap ran
4.99s to 8.70s across fourteen days -- a CV of 0.17, which looks healthy until
you read the sequence. It falls almost monotonically from 8.70 in early
September to 4.99 today, because the code kept being edited underneath it.
That is not drift, it is a development artefact, and it stops the day the code
settles. The operator asked for the real thing instead.

Two walks, because a person is not one dial:

  * pace     -- how quickly they act between decisions
  * restless -- how readily they get up and leave

Each is a bounded random walk carried across days rather than re-rolled, so
consecutive days resemble each other the way a person's do, and the whole
thing wanders instead of jittering around one centre.

WHAT IT MAY NOT TOUCH. Safety limits are not behaviour: the auto's 180s VIP
warm-up, the run window, maintenance waits, every detector threshold. Drifting
into those turns an anti-detection feature into a fault generator. This module
returns multipliers; the call sites decide what deserves one.
"""

from __future__ import annotations

import json
import random
from datetime import date

from rok_farm import PROJECT_ROOT
from rok_farm.logging_setup import logger

STATE = PROJECT_ROOT / "data" / "mood.json"

# How far a mood may wander from ordinary, and how fast.
#
# A fifth either way: enough to move a distribution's centre visibly across a
# week, small enough that no single day looks like a different bot. The step
# is a quarter of that, so crossing the range takes several days rather than
# one -- a walk, not a re-roll.
BOUNDS = (0.80, 1.25)
STEP = 0.09

DIALS = ("pace", "restless")


def _clamp(v: float) -> float:
    lo, hi = BOUNDS
    return max(lo, min(hi, v))


def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        logger.debug("mood: could not save", exc_info=True)


def today(account_id: str = "", when: date | None = None) -> dict:
    """This day's multipliers, one step on from the last day's.

    Stable within a day: asked twice on the same date it answers the same,
    so a farm restarted six times does not re-roll its mood six times. That
    matters -- a mood that changes every restart is noise, not character.
    """
    day = (when or date.today()).isoformat()
    data = _load()
    if data.get("day") == day and all(k in data for k in DIALS):
        return {k: float(data[k]) for k in DIALS}

    rng = random.Random(f"{account_id}:{day}")
    out = {}
    for dial in DIALS:
        prev = float(data.get(dial, 1.0))
        out[dial] = round(_clamp(prev + rng.gauss(0.0, STEP)), 4)
    _save({"day": day, **out})
    logger.info("mood for %s: %s", day,
                ", ".join(f"{k} {v:.2f}" for k, v in out.items()))
    return out


def pace(account_id: str = "") -> float:
    """Multiplier for how long the farm pauses between its own actions."""
    return today(account_id)["pace"]


def restless(account_id: str = "") -> float:
    """Multiplier for how readily it gets up and leaves the client."""
    return today(account_id)["restless"]
