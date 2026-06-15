# ROK Farm Automation

CLI-first gem farming automation for Rise of Kingdoms PC.

Current workflow is centered on `tools/test_gem_farm_flow.py`. The old tkinter dashboard, orchestrator/state-machine pipeline, and phase-roadmap docs were removed because they no longer match how the project is actually used.

## Run

```powershell
.venv\Scripts\python -m tools.test_gem_farm_flow --port COM27 --count 2
```

Useful options:

```powershell
.venv\Scripts\python -m tools.test_gem_farm_flow --find-only
.venv\Scripts\python -m tools.test_gem_farm_flow --port COM27 --loop --max-marches 5 --no-screenshots
.venv\Scripts\python -m tools.test_gem_farm_flow --port COM27 --count 2 --auto-learn
```

## What Stays

| Path | Purpose |
|---|---|
| `tools/test_gem_farm_flow.py` | Main live runner: capture -> detect gem -> click/gather/march -> return city |
| `capture/` | Window finding and screen capture |
| `vision/` | Template matching, gem color filter, k-NN gem classifier |
| `anti_detection/` | Mouse movement, timing/session helpers, player distraction actions |
| `serial_comm/` | Text protocol, serial connection, command buffer |
| `esp32-s3/` | PlatformIO firmware for real USB HID |
| `templates/` | OpenCV templates used by the runner |
| `data/gem_classifier.npz` | Persisted gem classifier |
| `data/gem_patches/` | Labeled patches for retraining |
| `profiles/default.json` | Main behavior profile |

## Helper Tools

```powershell
.venv\Scripts\python -m tools.test_esp32 COM27
.venv\Scripts\python -m tools.bootstrap_gem_classifier
.venv\Scripts\python -m tools.train_gem_classifier --port COM27
.venv\Scripts\python -m tools.test_mouse_paths --save
```

## Setup

```powershell
py -3.10 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Flash firmware:

```powershell
cd esp32-s3
pio run -t upload
```

## Notes

- No `main.py` entry point anymore.
- No tkinter dashboard.
- Runtime logs go to `logs/`.
- Runner screenshots go to `tools/screenshots/gem_farm_test/` and are ignored by git.
