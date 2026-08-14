# ROK Farm Automation - Agent Notes

## Workflow Rules

1. Read `PLAN.md` before starting any task.
2. Update `PLAN.md` after finishing a task.
3. Communicate with the user in Vietnamese.
4. Keep code and code comments in English.
5. Treat `run_farm.py` (repo root) as the primary entry point unless the user explicitly says otherwise. It only parses CLI args; the runner lives in `rok_farm/`.
6. Never guess a UI position from a screenshot. Add a capture tool and ask the user to run it.
7. Thresholds are measured on the live client, never guessed. Add a tool under `tools/dev/`, record the numbers in a comment next to the constant, and lock them with a test.

## Current Shape

This repo is now a lean CLI runner for gem farming in Rise of Kingdoms PC.

```text
Game Window -> capture -> vision/classifier -> gem farm flow -> serial -> ESP32-S3 -> USB HID
```

There is no tkinter UI and no `main.py` orchestrator. The old state-machine/dashboard docs were removed because they were stale.

## Active Modules

```text
run_farm.py                        - entry point, CLI args only (repo root)
rok_farm/config.py                 - constants + runtime knobs
rok_farm/logging_setup.py          - logger + console colour tokens
rok_farm/screenshots.py            - debug frame dumps
rok_farm/persona.py                - per-account persona traits
rok_farm/input_hid.py              - ESP32 pointer/keyboard output
rok_farm/capture_svc.py            - capture thread + window geometry
rok_farm/detect.py                 - template/colour detection
rok_farm/queue_ocr.py              - march queue OCR
rok_farm/recovery.py               - ESC back-out, reconnect popup
rok_farm/button_registry.py        - learned button positions, refuses stray clicks
rok_farm/state_probe.py            - local screen state (modal, liveness, view)
rok_farm/vision_llm.py             - vision-model escalation (OpenRouter, AI Mode)
rok_farm/dismiss.py                - close an unknown popup, guardrails + learning
templates/ui/learned/              - close buttons the bot taught itself
rok_farm/game_process.py           - launch / quit / restart the client
rok_farm/flow_steps.py             - per-mine flow, steps 1..7
rok_farm/phases.py                 - between-burst behaviour
rok_farm/runner.py                 - GemFarmRunner: setup, loop, teardown
rok_farm/find_only.py              - vision-only debug scan
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
profiles/paths.json                - discovered launcher path + Play button pct (gitignored)
templates/                         - OpenCV template assets
data/gem_classifier.npz            - trained classifier model
data/gem_patches/                  - labeled classifier patches
tools/                             - capture/train/calibration helpers
tools/dev/                         - one-off debug + hardware probe scripts
```

## Common Commands

```powershell
.venv\Scripts\python run_farm.py --port COM27 --count 2
.venv\Scripts\python run_farm.py --find-only
.venv\Scripts\python run_farm.py --port COM27 --loop --max-marches 5 --no-screenshots
.venv\Scripts\python run_farm.py --port COM27 --loop --no-auto-launch --no-restart
.venv\Scripts\python tools\capture_launcher_btn.py --start
.venv\Scripts\python tools\bootstrap_gem_classifier.py
.venv\Scripts\python tools\dev\test_esp32.py COM27
.venv\Scripts\python -m pytest
```

## Cleanup Policy

- Do not reintroduce UI/dashboard code unless the user asks for it.
- Do not add new roadmap docs unless they are short and current.
- Keep generated screenshots/logs out of git (`logs/`, `screenshots/`).
- Keep the repo root to the entry point + docs; dev scripts belong in `tools/` or `tools/dev/`.
- Prefer improving the live gem flow over reviving old generic farming abstractions.
