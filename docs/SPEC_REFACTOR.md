# SPEC: Module Split + Game Lifecycle

Two changes, one pass:

1. Break the 2500-line `run_farm.py` god class into a `rok_farm/` package of mixins.
2. Add game process control: auto-launch at start, restart on recovery / long break.

Decisions taken 2026-08-14 (see PLAN.md > Decisions).

---

## Part 1 -- Module split

### Rule

Mixin split, not composition. `GemFarmRunner` still ends up as ONE runtime object
with the same `self._click`, `self._grab`, `self._find` API, so:

- no call site inside the flow changes,
- `PlayerActions(self, persona)` keeps working (it needs 14 runner methods, see
  `PlayerActionCtx` in `anti_detection/player_actions.py`),
- the move is mechanical and reviewable.

Method bodies are moved verbatim. Behavior changes belong to Part 2 only.

### Layout

```text
run_farm.py                 - argparse + main() only (~60 lines)
rok_farm/
  __init__.py
  config.py                 - every module-level constant + mutable runtime knobs
  logging_setup.py          - logging config, logger, PASS/FAIL/WARN/INFO tokens
  screenshots.py            - save_screenshot, save_annotated
  persona.py                - PersonaMixin
  input_hid.py              - HidInputMixin
  capture_svc.py            - CaptureMixin (capture thread + window geometry)
  detect.py                 - DetectMixin
  queue_ocr.py              - QueueMixin (march queue OCR)
  recovery.py               - RecoveryMixin
  game_process.py           - GameProcess class + GameLifecycleMixin  [NEW]
  flow_steps.py             - GemFlowMixin (steps 1..7)
  phases.py                 - PhasesMixin (burst rhythm, alt-tab, city idle)
  runner.py                 - GemFarmRunner(all mixins): __init__/_setup/run/_teardown
  find_only.py              - run_find_only (vision-only debug path)
```

Built as specified except: persona stayed a mixin (`PersonaMixin`) instead of
becoming module functions -- as functions its five methods would have needed
rewriting, and a verbatim move cannot go wrong. No separate `timing.py`; `_wait`
stayed in `input_hid.py` where its callers are.

### Method map (from current `run_farm.py`)

| Target | Methods moved |
|---|---|
| `config.py` | all constants L92-L172, `_BTN_POS`, `_X_CLOSE_POS`, `_PANEL_ITEMS`, `MARCH_TEMPLATES`, `GEM_MINE_TEMPLATES`, `OCCUPIED_TEMPLATES` |
| `screenshots.py` | `save_screenshot`, `save_annotated` |
| `persona.py` | `_persona_path`, `_load_or_create_persona`, `_save_persona`, `_jitter`, `_apply_persona` |
| `input_hid.py` | `_wait`, `_probe_moveto`, `_calibrate_mouse_scale`, `_restore_cursor_to_window`, `_path_to_hid`, `_send_path`, `_moveto`, `_in_no_click_zone`, `_click`, `_click_match`, `_click_pct`, `_human_drag`, `_scroll_at_center`, `_press_escape` |
| `capture_svc.py` | `_start_capture_thread`, `_stop_capture_thread`, `_capture_loop`, `_grab`, `_gem_icon_threshold`, `_refresh_window`, `_screen_xy`, `_center_screen`, `_clamp_to_window`, `_clamp_to_play_area`, `_zoom_scrolls` |
| `detect.py` | `_find`, `_find_on_frame`, `_match_verify`, `_find_city_btn`, `_on_world_map`, `_wait_until_world_map`, `_find_new_troop_btn`, `_find_all_gems`, `_find_all_icons`, `_extract_icon_patch`, `_is_clickable_zone`, `_is_fog`, `_has_march_line`, `_check_icon_occupied`, `_is_mine_occupied`, `_has_incoming_march`, `_find_march_btn`, `_is_troop_panel_open` |
| `queue_ocr.py` | `_detect_march_queue` (+ the OCR backend import block) |
| `recovery.py` | `_on_clean_view`, `_check_reconnect_popup`, `_attempt_recovery` |
| `flow_steps.py` | `_mine_flow`, `_step_to_world_map`, `_step_stay_and_rezoom`, `_step_scan_and_verify_gem`, `_step_click_gather`, `_step_click_march`, `_step_return_city`, `_click_icon_and_verify`, `_recenter_edge_gem`, `_recenter_to_safe_zone`, `_return_to_icon_zoom` |
| `phases.py` | `_tab_out`, `_tab_away`, `_tab_back`, `_close_panel`, `_check_session`, `_phase_full_cycle`, `_phase_city_idle`, `_phase_wait_return` |
| `runner.py` | `__init__`, `_setup`, `_initial_prepare`, `run`, `_record`, `_teardown`, `_print_report` |

### Mutable globals

`_SAVE_SCREENSHOTS` and `ICON_ZOOM_SCROLLS` are rebound by `main()` at runtime.
`from config import X` would freeze the old value in every importer, so these two
live in `config.py` and are always read through the module:

```python
from rok_farm import config as cfg
if cfg.SAVE_SCREENSHOTS: ...
n = cfg.ICON_ZOOM_SCROLLS
```

Plain constants (thresholds, delays, pct positions) may be imported by name.

### Acceptance -- all met 2026-08-14

- `import run_farm` clean; `pyflakes` reports no undefined names across the package.
- `run_farm.py --find-only` behaves as before.
- `pytest` green (5 passed), including a new test asserting the runner still
  satisfies the `PlayerActionCtx` protocol.
- All 85 methods of the old class still resolve on `GemFarmRunner`.
- Largest module 482 lines (`flow_steps.py`), down from 2491 in one file.

---

## Part 2 -- Game lifecycle

### Policy (chosen)

| Situation | Action |
|---|---|
| Startup, game window missing | Launch the game, wait until the city is loaded |
| Waiting for troops to return (~15 min) | **Alt-tab only** -- unchanged |
| Short session break (< `RESTART_BREAK_MINUTES`) | Alt-tab away, unchanged |
| Long break (>= `RESTART_BREAK_MINUTES`, default 30) | Quit game, sleep, relaunch |
| Client broken (see triggers) | Quit game, short cooldown, relaunch |

Why not restart between every burst: the "troops returned" Windows toast that
`_phase_wait_return` waits on is emitted by the running game process while it is
backgrounded. Quitting kills the toast and forces a blind 15-minute timer, while
adding a login/logout event every ~15 minutes -- a stronger server-side signal
than staying alt-tabbed.

### Restart triggers (recovery)

Any of these, checked in `run()`:

1. `consecutive_fails >= RESTART_AFTER_FAILS` (default 8) -- replaces today's
   "long break then retry" branch.
2. Game window not found for > `WINDOW_LOST_TIMEOUT` (default 60 s).
3. Capture thread produced no frame for > `FRAME_STALL_TIMEOUT` (default 45 s).
4. `_check_reconnect_popup` failed to clear the popup twice in a row.

### `rok_farm/game_process.py`

```python
class GameProcess:
    def __init__(self, launcher_path: str | None = None): ...

    # discovery
    @staticmethod
    def discover_launcher() -> Path | None
    def is_game_running(self) -> bool          # MASS.exe
    def is_launcher_running(self) -> bool      # launcher.exe
    def launcher_window(self) -> dict | None   # rect of launcher.exe top-level window

    # actions (hid = the runner, for HID clicks)
    def start_launcher(self) -> bool           # cold start, needs elevation
    def press_play(self, hid) -> bool          # click Play in the launcher window
    def quit_game(self, hid) -> bool           # graceful close, taskkill fallback
```

`GameLifecycleMixin` on the runner wires it to the flow:

```python
def _ensure_game_running(self) -> bool     # called from _setup when window missing
def _restart_game(self, reason: str, cooldown: float = 0.0) -> bool
```

### Launcher path -- never hardcoded

Resolution order, first hit wins; the result is cached back to
`profiles/paths.json`:

1. `--launcher-path` CLI argument
2. `ROK_LAUNCHER_PATH` environment variable
3. `profiles/paths.json` -> `{"launcher": "..."}`
4. Start Menu shortcut `Rise of Kingdoms.lnk` under `%ProgramData%` and
   `%APPDATA%`, resolved with `win32com.client.Dispatch("WScript.Shell")`
5. Registry `HKLM/HKCU ...\Uninstall\*` where `DisplayName` matches
   `Rise of Kingdoms` -> `InstallLocation\launcher.exe`

On this machine step 4 resolves to `D:\Game\Rise of Kingdoms\launcher.exe`, with
the game binary at `Rise of Kingdoms Game\MASS.exe`. Nothing about those paths is
written into the source.

### Elevation (UAC)

`launcher.exe` requires admin. Two paths:

- **Bot already elevated** (recommended): run the terminal as administrator.
  `subprocess.Popen(launcher)` inherits the token, no UAC dialog, fully
  automatic. `ctypes.windll.shell32.IsUserAnAdmin()` reports this.
- **Bot not elevated**: `ShellExecuteW(None, "runas", launcher, ...)` raises the
  UAC dialog. The dialog lives on the secure desktop, which the capture backend
  cannot see, so the bot must NOT click blind -- it prints a prompt and polls for
  the launcher window for up to `LAUNCHER_UAC_TIMEOUT` (default 120 s) while the
  user accepts.

Warm restart after a game exit needs no elevation at all: the launcher window is
still open, so the restart path is only `press_play` -> wait for game window.

### Launcher Play button

The launcher is a CEF window; its Play button position is NOT guessed. Capture it
once with `tools/capture_launcher_btn.py`, which:

- finds the `launcher.exe` window, screenshots it,
- lets the user click the Play button in an OpenCV preview,
- stores `templates/launcher/play_btn.png` plus the click position as a % of the
  launcher window into `profiles/paths.json` -> `{"play_btn_pct": [x, y]}`.

At runtime `press_play` template-matches inside the launcher window first and
falls back to the stored percentage. If neither exists it prints a clear
instruction to run the capture tool, and auto-launch is skipped (the run
continues if the game happens to be open already).

### Quit game

1. Bring the game forward (alt-tab), `COMBO ALT F4` via HID.
2. ROK asks for confirmation -> template `ui/btn_confirm_exit` (also captured by
   the user; optional).
3. If `MASS.exe` is still alive after `QUIT_TIMEOUT` (default 30 s):
   `taskkill /IM MASS.exe /F`.

Graceful exit is preferred: a hard kill looks like a client crash server-side.

### Ready states after launch

```python
_wait_for_game_window(timeout=GAME_LAUNCH_TIMEOUT)  # default 180 s
    -> _rebind_capture()      # WGC binds to a hwnd; a new client needs a new one
    -> _ensure_target_size()  # resize to TARGET_CONTENT_W BEFORE anything is detected
_wait_until_in_city(timeout=CITY_READY_TIMEOUT)     # default 300 s
```

`_wait_until_in_city` accepts any of `ui/city_food`, `ui/city_wood`,
`buttons/world_map_city_btn`, `buttons/city_btn` (the last because a session can
resume onto the world map instead of the city). All four only answer on a view
with the HUD visible, so **a timeout is not fatal**: an event popup or a panel
left open after login hides every one of them while the client is perfectly
healthy. It logs and hands back to the flow, which navigates with live frames and
runs its own ESC back-out after 3 failed mines.

No blind ESC back-out here on purpose -- around a restart the capture is paused,
so the "is a panel open" guard would read stale frames, and ESC on a clean view
opens the profile panel.

After a successful relaunch: `self._view_is_world` follows whichever view
answered, re-read the march queue by OCR, resume the loop.

### New config knobs (`rok_farm/config.py`)

```python
AUTO_LAUNCH_GAME       = True
RESTART_ON_RECOVERY    = True
RESTART_AFTER_FAILS    = 8
RESTART_BREAK_MINUTES  = 30      # break >= this -> quit game instead of alt-tab
WINDOW_LOST_TIMEOUT    = 60.0
FRAME_STALL_TIMEOUT    = 45.0
GAME_LAUNCH_TIMEOUT    = 180.0
CITY_READY_TIMEOUT     = 300.0
LAUNCHER_UAC_TIMEOUT   = 120.0
QUIT_TIMEOUT           = 30.0
RESTART_COOLDOWN       = (20.0, 60.0)   # random pause between quit and relaunch
```

### New CLI flags

```text
--launcher-path PATH   override launcher location
--no-auto-launch       never start the game, fail if the window is missing
--no-restart           never quit/relaunch the game (recovery falls back to today's long break)
```

### Acceptance -- code complete, live run pending

- With the game already open: behavior identical to today.
- With the game closed and the bot elevated: `run_farm.py --port COMxx --count 1`
  starts the launcher, presses Play, waits for the city, then farms.
- With the game closed and the bot NOT elevated: prints the UAC instruction,
  waits, then continues once the launcher appears.
- `--no-auto-launch` with the game closed: fails at setup exactly as today.
- Killing the game mid-run triggers exactly one restart, not a restart loop
  (guard: at most `MAX_RESTARTS_PER_HOUR = 3`).

Verified so far without the game running: the launcher resolves through the
Start Menu shortcut to `D:\Game\Rise of Kingdoms\launcher.exe` and is cached to
`profiles/paths.json`. Still needs a live pass: capturing the Play button, one
cold start, and one mid-run restart.
