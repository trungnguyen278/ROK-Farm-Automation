# Anti-Detection Engine

> **AI Note:** 4 file Python: mouse_humanizer (Bézier+jitter+overshoot), timing_engine (Gaussian delays), session_manager (farm/rest cycles + fatigue), profile_loader (JSON behavior sets). Mọi action phải qua engine trước khi gửi serial.

## Layer 1: Mouse Humanizer

```python
# anti_detection/mouse_humanizer.py
class MouseHumanizer:
    def __init__(self, profile: dict)
    def humanize_move(self, x1, y1, x2, y2) -> list[tuple[int,int,int]]
        # Returns: [(x, y, duration_ms), ...] — path steps
    def humanize_click(self, x, y) -> tuple[int, int, int]
        # Returns: (offset_x, offset_y, hold_ms)
    def should_overshoot(self) -> bool       # ~15% chance
    def should_misclick(self) -> bool        # ~1-2% chance
```

### Bézier Curve Path
```python
# 3-4 control points, randomized
P0 = (x1, y1)                          # start
P1 = random_offset(midpoint, ±50px)    # control 1
P2 = random_offset(midpoint, ±30px)    # control 2 (optional)
P3 = (x2, y2)                          # end

# Speed profile: ease-in-out
# t: 0→1, speed = sin(t * pi) → slow at start/end, fast in middle
```

### Overshoot & Correction
```python
if should_overshoot():  # ~15%
    overshoot_dist = gauss(10, 5)  # pixels past target
    overshoot_angle = atan2(dy, dx) + gauss(0, 0.3)  # slight angle offset
    # Move to overshoot point, pause 50-150ms, then correct to target
```

### Click Offset
```python
offset_x = gauss(0, click_spread)  # click_spread from profile, default ±8px
offset_y = gauss(0, click_spread)
hold_ms = uniform(50, 150)
```

## Layer 2: Timing Engine

```python
# anti_detection/timing_engine.py
class TimingEngine:
    def __init__(self, profile: dict)
    def action_delay(self) -> float         # between actions (800-2000ms gaussian)
    def micro_pause(self) -> float | None   # 2-5s, ~20% chance between action chains
    def typing_delay(self) -> float         # between keystrokes (30-120ms)
    def apply_fatigue(self, session_minutes: float) -> float  # multiplier 1.0→1.5
```

### Fatigue Model
```python
# After 20min: delays increase 10%
# After 40min: delays increase 25%
# After 60min: delays increase 50%
fatigue_multiplier = 1.0 + 0.5 * min(session_minutes / 60, 1.0)
```

## Layer 3: Session Manager

```python
# anti_detection/session_manager.py
class SessionManager:
    def __init__(self, profile: dict)
    def should_take_break(self) -> bool
    def get_break_duration(self) -> float   # seconds
    def should_stop_daily(self) -> bool
    def get_idle_action(self) -> IdleAction | None  # random map pan, zoom
    def session_stats(self) -> dict

class IdleAction(Enum):
    PAN_MAP = "pan_map"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    CHECK_ALLIANCE = "check_alliance"
```

### Session Patterns
| Param | Range | Distribution |
|---|---|---|
| Farm duration | 15-40 min | Gaussian(25, 8) |
| Break duration | 5-15 min | Gaussian(8, 3) |
| Daily active hours | 4-10 hrs | From profile |
| Active time window | 08:00-23:00 | From profile |
| Idle action chance | 5-10% | Per action cycle |

## Layer 4: Profile System

```python
# anti_detection/profile_loader.py
class ProfileLoader:
    def __init__(self, profile_dir: str = "profiles/")
    def load(self, name: str) -> dict
    def load_random(self) -> dict
    def list_profiles(self) -> list[str]
```

### Profile JSON Schema
```json
{
  "name": "cautious",
  "mouse": {
    "bezier_control_points": 3,
    "speed_base": 400,
    "speed_variance": 150,
    "overshoot_chance": 0.15,
    "overshoot_distance": [5, 15],
    "misclick_chance": 0.01,
    "click_spread": 8,
    "hold_ms": [50, 150],
    "jitter_px": 2
  },
  "timing": {
    "action_delay_mean": 1200,
    "action_delay_std": 400,
    "micro_pause_chance": 0.2,
    "micro_pause_range": [2000, 5000],
    "typing_delay": [30, 120]
  },
  "session": {
    "farm_duration_mean": 25,
    "farm_duration_std": 8,
    "break_duration_mean": 8,
    "break_duration_std": 3,
    "daily_hours_max": 6,
    "active_window": ["08:00", "23:00"],
    "idle_action_chance": 0.08
  }
}
```

### Preset Profiles
| Profile | Style | Risk |
|---|---|---|
| `cautious.json` | Slow, many pauses, short sessions | Lowest |
| `default.json` | Balanced | Medium |
| `aggressive.json` | Fast, fewer breaks, long sessions | Higher |

## Integration Flow

```python
# In main decision loop:
action = state_machine.next_action()
if action:
    # 1. Timing
    delay = timing_engine.action_delay()
    delay *= timing_engine.apply_fatigue(session.elapsed_minutes)
    time.sleep(delay)
    
    # 2. Session check
    if session_manager.should_take_break():
        time.sleep(session_manager.get_break_duration())
        return
    
    # 3. Humanize
    if action.type == "click":
        ox, oy, hold = humanizer.humanize_click(action.x, action.y)
        path = humanizer.humanize_move(current_x, current_y, action.x + ox, action.y + oy)
        for step in path:
            serial.send("MOVE", step.x, step.y, step.duration)
        serial.send("CLICK", "L", hold)
```
