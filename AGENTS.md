# ROK Farm Automation - Agent Notes

## Workflow Rules

1. Read `PLAN.md` before starting any task.
2. Update `PLAN.md` after finishing a task.
3. Communicate with the user in Vietnamese.
4. Keep code and code comments in English.
5. Treat `tools/test_gem_farm_flow.py` as the primary entry point unless the user explicitly says otherwise.

## Current Shape

This repo is now a lean CLI runner for gem farming in Rise of Kingdoms PC.

```text
Game Window -> capture -> vision/classifier -> gem farm flow -> serial -> ESP32-S3 -> USB HID
```

There is no tkinter UI and no `main.py` orchestrator. The old state-machine/dashboard docs were removed because they were stale.

## Active Modules

```text
tools/test_gem_farm_flow.py        - main live runner
capture/screen_capture.py          - ROK window capture
capture/screen_info.py             - cursor/screen/HID coordinate helpers
vision/template_cache.py           - template loading
vision/template_matcher.py         - OpenCV template matching
vision/state_detector.py           - city/world hints
vision/color_filter.py             - gem color filtering
vision/gem_classifier.py           - k-NN gem/not-gem classifier
anti_detection/mouse_humanizer.py  - generated mouse trajectories
anti_detection/timing_engine.py    - action delay helpers
anti_detection/session_manager.py  - session/night helpers
anti_detection/profile_loader.py   - JSON behavior profile loader
anti_detection/player_actions.py   - optional distraction/idle actions
serial_comm/                       - protocol, serial connection, command queue
esp32-s3/                          - PlatformIO USB HID firmware
profiles/default.json              - active behavior profile
templates/                         - OpenCV template assets
data/gem_classifier.npz            - trained classifier model
data/gem_patches/                  - labeled classifier patches
```

## Common Commands

```powershell
.venv\Scripts\python -m tools.test_gem_farm_flow --port COM27 --count 2
.venv\Scripts\python -m tools.test_gem_farm_flow --find-only
.venv\Scripts\python -m tools.test_gem_farm_flow --port COM27 --loop --max-marches 5 --no-screenshots
.venv\Scripts\python -m tools.bootstrap_gem_classifier
.venv\Scripts\python -m tools.test_esp32 COM27
.venv\Scripts\python -m pytest
```

## Cleanup Policy

- Do not reintroduce UI/dashboard code unless the user asks for it.
- Do not add new roadmap docs unless they are short and current.
- Keep generated screenshots/logs out of git.
- Prefer improving the live gem flow over reviving old generic farming abstractions.
