# PLAN

## Current Mode

CLI-first gem farm runner. The source of truth is `run_farm.py` at the repo root.

## Active Status

- [x] ESP32 HID firmware exists and is used by the runner.
- [x] Serial protocol and command buffer are kept.
- [x] Capture, vision, gem classifier, mouse humanizer, and default profile are kept.
- [x] Old tkinter UI/dashboard removed.
- [x] Old `main.py` orchestrator and generic `logic/` pipeline removed.
- [x] Old YAML config loader/config file removed from the active workflow.
- [x] Old phase-roadmap docs and screenshot dumps removed.
- [x] README/AGENTS/PLAN rewritten to match the current CLI workflow.
- [x] Python syntax compile check passes for retained `.py` files.
- [x] Repo restructured 2026-08-14: runner moved to `run_farm.py`, dev scripts to `tools/dev/`, logs/screenshots purged.
- [ ] Next live focus: run current gem flow and tune popup handling/detection only where the live runner needs it.

## Primary Command

```powershell
.venv\Scripts\python run_farm.py --port COM27 --count 2
```

Useful variants:

```powershell
.venv\Scripts\python run_farm.py --find-only
.venv\Scripts\python run_farm.py --port COM27 --loop --max-marches 5 --no-screenshots
.venv\Scripts\python run_farm.py --port COM27 --count 2 --auto-learn
```

## Keep List

| Area | Keep |
|---|---|
| Runner | `run_farm.py` |
| Firmware | `esp32-s3/` |
| Host I/O | `capture/`, `serial_comm/` |
| Vision | `vision/`, `templates/`, `data/gem_classifier.npz`, `data/gem_patches/` |
| Behavior | `anti_detection/`, `profiles/default.json`, `data/mouse_training/` |
| Helpers | `tools/` (capture_templates, bootstrap/train_gem_classifier, generate_gem_template, record_mouse, train_mouse, resize_window) |
| Debug | `tools/dev/` (test_esp32, test_notification_listener, test_mouse_paths, test_loop_3actions, locate_ui, read_cursor) |

Note: `tools/dev/` holds spent or occasional-use scripts. `locate_ui.py` is hardcoded to old absolute screenshot paths and is a delete candidate.

## Decisions

| Date | Decision | Reason |
|---|---|---|
| 2026-06-14 | Treat the gem farm flow script as the main app | User mainly runs this and does not need UI complexity |
| 2026-08-14 | Rename runner to `run_farm.py` at repo root; anchor its paths to the repo root | Name `test_*` hid that it is the app; anchored paths let it run from any cwd |
| 2026-08-14 | Delete `tools/exp_*.py` calibration experiments | Thresholds they produced are already in `vision/color_filter.py` and the runner |
| 2026-08-14 | Move runner screenshots to `screenshots/gem_farm_test/` | Keeps `tools/` source-only; matches the dir `player_actions` already writes to |
| 2026-06-14 | Remove tkinter UI, old orchestrator, and generic `logic/` pipeline | They were stale and not part of the current live flow |
| 2026-06-14 | Remove old `config.yaml` workflow | Current runner takes CLI args directly and does not use the old config loader |
| 2026-06-14 | Remove old docs/roadmap and replace with concise README/AGENTS/PLAN | Old docs described phases and UI that no longer reflect the repo |
| 2026-06-14 | Keep classifier patches and mouse training data | They are useful for improving the current runner |

## Ad-hoc Tasks

| Task | Status | Note |
|---|---|---|
| Clean repo around current gem flow | Done | Removed UI/orchestrator/docs/debug dumps; kept runner dependencies |
| Smoke-test retained dependencies | Partial | `py_compile` passes; runtime smoke/pytest blocked by local Python env |
| Re-check live gem run | Pending | Use COM port from the actual ESP32 session |
| Restructure repo layout | Done | 2026-08-14: root entry point, `tools/dev/` split, 15MB of logs/screenshots removed |

## Blockers

| Date | Blocker | Note |
|---|---|---|
| 2026-06-14 | Local `.venv` points to missing Python 3.10, system Python 3.12 has no project deps | `.venv\Scripts\python` fails before startup; `python -m pytest` fails because `pytest`/`numpy` are not installed |
