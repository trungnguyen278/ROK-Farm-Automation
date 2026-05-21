# Anti-Detection Engine

> **Philosophy:** Farm fast when focused, alt-tab away between bursts. Game client cannot collect input data when window loses focus. Server only sees "player active -> player idle -> player active" — identical to millions of casual players who multitask between game and browser/Discord/YouTube.

## Why Alt-Tab Works

1. **Client-side blind spot:** When ROK window loses focus, the game client stops processing input events entirely. No mouse telemetry, no timing data, no behavioral fingerprint during idle periods.
2. **Server sees nothing suspicious:** The server only knows "last action timestamp" vs "next action timestamp". A 3-minute gap looks identical whether the player alt-tabbed to Chrome or went to the kitchen.
3. **Real player pattern:** Millions of ROK PC players multitask. Tab in, do some stuff quickly, tab out. This is the most common play pattern for casual farmers.
4. **No statistical signature:** Delay-based anti-detection (Gaussian noise, fatigue curves, micro-pauses) creates detectable patterns because the noise itself has a distribution. Alt-tab creates zero data points during idle — there's nothing to analyze.

## Architecture

```
[Active burst]                    [Idle - invisible to game]
click-click-click (1-3 mines) -> ALT+TAB out -> wait 1.5-12 min -> ALT+TAB back -> repeat
      ^                                                                    |
      |                                                                    v
  Fast, focused                                              Check reconnect popup
  No artificial delays                                       Re-find game window
  Real mouse paths (Bezier)                                  Maybe drag map (30%)
```

## Layer 1: Hardware HID (ESP32-S3)

The bot sends commands via UART to an ESP32-S3 which emits real USB HID packets. The OS sees a genuine Logitech USB Receiver (VID=046D, PID=C52B). No driver hooks, no API calls — indistinguishable from a real mouse/keyboard at the OS level.

```
Python host -> UART (COM28) -> ESP32-S3 -> USB HID -> OS -> Game
```

## Layer 2: Screen Capture (WGC)

Windows Graphics Capture API — the same API that Game Bar uses. Not flagged by any anti-cheat because it's a standard Windows feature. The game cannot detect that screenshots are being taken.

## Layer 3: Mouse Humanizer

```python
# anti_detection/mouse_humanizer.py
class MouseHumanizer:
    def humanize_move(self, x1, y1, x2, y2) -> list[tuple[int,int,int]]
    def humanize_click(self, x, y) -> tuple[int, int, int]
```

Real mouse paths via Bezier curves with overshoot and jitter. Not for "looking human to a timing analyzer" — for looking human to a replay viewer. If a game master watches a session recording, the cursor should move naturally.

- **Bezier curves:** 3-4 control points, ease-in-out speed profile
- **Overshoot:** ~15% chance, 5-15px past target, then correct
- **Click spread:** Gaussian offset +-8px from center
- **Hold duration:** 50-150ms per click

## Layer 4: Alt-Tab Burst Pattern

The core anti-detection mechanism. Instead of adding artificial delays between actions, the bot works in fast bursts separated by real idle periods.

### Burst Mining
```python
# Random 1-3 mines per burst, weighted
burst_size = random.choices([1, 2, 3], weights=[60, 25, 15])[0]

# After each burst: alt-tab away
_night_tab_away()   # ALT+TAB out, sleep 1.5-12 min
_night_tab_back()   # ALT+TAB in, check reconnect, re-find window
```

### Away Duration (scales with night progress)
| Night Progress | Away Range | Avg |
|---|---|---|
| Early (0-30%) | 90-240s | ~2.5 min |
| Mid (30-70%) | 180-480s | ~5.5 min |
| Late (70-100%) | 300-720s | ~8.5 min |

### Tab Back Sequence
1. Send ALT+TAB (hold 50-120ms)
2. Wait 1.5-3s for window focus
3. Re-find game window handle
4. Check for disconnect/reconnect popup (game drops connection during long idle)
5. If popup found: dismiss, wait 2-4s for reconnection
6. Optional: drag map slightly (30% chance) — simulates "looking around"

### Focused-Play Delays (during active burst)
All delays are minimal — simulating a player who knows exactly what they're doing:

| Action | Delay | Note |
|---|---|---|
| After click | 0.15s | Just waiting for UI response |
| After escape | 0.18s | Menu close animation |
| After scroll | 0.30s | Map zoom animation |
| Zoom in | 0.50s | Camera animation |
| Mine click | 0.30s | Popup open |
| Between mines | 1.0s | Quick context switch |
| Verify template | 0.35s | Screen settle |

No Gaussian noise on these — just `uniform(center * 0.8, center * 1.4)`. The variance is realistic for a focused player, not artificially inflated.

## Layer 5: Night Schedule

The bot runs on a night schedule with randomized start/stop times to avoid exact patterns.

### Schedule Randomization
```python
class NightSchedule:
    # Base times from profile (default: 01:00 - 07:00)
    # Gaussian jitter per session: +/- 15-30 min
    # Persistent day_drift: drifts by gauss(0, variance/3) each day, clamped
    # Result: schedule varies 10-30 min day-to-day, never exact same time
```

### Profile Night Mode Config
```json
"night_mode": {
    "bed_time": "01:00",
    "wake_time": "07:00",
    "stop_margin_min": 30,
    "jitter_start_min": 20,
    "jitter_stop_min": 15,
    "day_variance_min": 10
}
```

- `stop_margin_min`: Stop this many minutes before wake_time (buffer for shutdown)
- `jitter_*_min`: Per-session random offset range
- `day_variance_min`: Day-to-day drift range (persistent across sessions)

### Session Check
```python
def _check_session(self) -> str | None:
    if self._night_schedule and not self._night_schedule.is_active_now():
        return "stop_night"
    return None
```

When night schedule ends: ALT+TAB out and exit. No wind-down, no fake sleepiness — just stop.

## What Was Removed (and Why)

The original design had 4 software layers of delay-based anti-detection. These were removed because they create detectable statistical patterns rather than preventing detection:

| Removed | Reason |
|---|---|
| Gaussian action delays (800-2000ms) | Creates detectable distribution; real focused players are faster |
| Fatigue model (delays increase over time) | Artificial pattern; real players don't slow down linearly |
| Session breaks (farm 25min, rest 8min) | Fixed-ratio pattern; alt-tab is more natural |
| Daily hour limits | Unnecessary; night schedule already constrains runtime |
| Idle actions (pan map, check alliance) | Purposeless actions are suspicious; focused play is normal |
| Micro-pauses (2-5s random) | Detectable noise injection; real pauses are alt-tabs |
| Typing delays | Not applicable; bot doesn't type |
| Active time window | Replaced by night schedule |

## Files

| File | Purpose |
|---|---|
| `anti_detection/mouse_humanizer.py` | Bezier paths, overshoot, click offset, jitter |
| `anti_detection/timing_engine.py` | Minimal — `action_delay()`, `apply_fatigue()` kept for stats |
| `anti_detection/session_manager.py` | `NightSchedule` (jitter+drift), `SessionManager` (stats only) |
| `anti_detection/profile_loader.py` | Load JSON profile, deep merge defaults |
| `profiles/*.json` | Mouse params + night_mode schedule per profile |
