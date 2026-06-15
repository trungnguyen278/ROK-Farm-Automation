# PLAN

## Current Mode

CLI-first gem farm runner. The source of truth is `tools/test_gem_farm_flow.py`.

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
- [ ] Next live focus: run current gem flow and tune popup handling/detection only where the live runner needs it.

## Primary Command

```powershell
.venv\Scripts\python -m tools.test_gem_farm_flow --port COM27 --count 2
```

Useful variants:

```powershell
.venv\Scripts\python -m tools.test_gem_farm_flow --find-only
.venv\Scripts\python -m tools.test_gem_farm_flow --port COM27 --loop --max-marches 5 --no-screenshots
.venv\Scripts\python -m tools.test_gem_farm_flow --port COM27 --count 2 --auto-learn
```

## Keep List

| Area | Keep |
|---|---|
| Runner | `tools/test_gem_farm_flow.py` |
| Firmware | `esp32-s3/` |
| Host I/O | `capture/`, `serial_comm/` |
| Vision | `vision/`, `templates/`, `data/gem_classifier.npz`, `data/gem_patches/` |
| Behavior | `anti_detection/`, `profiles/default.json`, `data/mouse_training/` |
| Helpers | `tools/test_esp32.py`, `tools/bootstrap_gem_classifier.py`, `tools/train_gem_classifier.py`, `tools/generate_gem_template.py`, `tools/record_mouse.py`, `tools/train_mouse.py`, `tools/test_mouse_paths.py`, `tools/capture_templates.py`, `tools/read_cursor.py` |

Note: `tools/test_loop_3actions.py` is intentionally not part of the keep list. It was left in place only because it already had uncommitted changes before cleanup.

## Decisions

| Date | Decision | Reason |
|---|---|---|
| 2026-06-14 | Treat `tools/test_gem_farm_flow.py` as the main app | User mainly runs this and does not need UI complexity |
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

## Blockers

| Date | Blocker | Note |
|---|---|---|
| 2026-06-14 | Local `.venv` points to missing Python 3.10, system Python 3.12 has no project deps | `.venv\Scripts\python` fails before startup; `python -m pytest` fails because `pytest`/`numpy` are not installed |
