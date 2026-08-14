# ROK Farm Automation

CLI-first gem farming automation for Rise of Kingdoms PC.

Entry point is `run_farm.py` at the repo root. Everything under `tools/` is a dev
helper, never needed for a normal farm run.

## Run

```powershell
.venv\Scripts\python run_farm.py --port COM27 --count 2
```

Useful options:

```powershell
.venv\Scripts\python run_farm.py --find-only
.venv\Scripts\python run_farm.py --port COM27 --loop --max-marches 5 --no-screenshots
.venv\Scripts\python run_farm.py --port COM27 --count 2 --auto-learn
```

## Layout

| Path | Purpose |
|---|---|
| `run_farm.py` | Main live runner: capture -> detect gem -> click/gather/march -> return city |
| `capture/` | Window finding and screen capture |
| `vision/` | Template matching, gem color filter, k-NN gem classifier |
| `anti_detection/` | Mouse movement, timing/session helpers, player distraction actions |
| `serial_comm/` | Text protocol, serial connection, command buffer |
| `esp32-s3/` | PlatformIO firmware for real USB HID |
| `templates/` | OpenCV templates used by the runner |
| `data/gem_classifier.npz` | Persisted gem classifier |
| `data/gem_patches/` | Labeled patches for retraining |
| `profiles/default.json` | Main behavior profile |
| `tools/` | Capture/train/calibration helpers |
| `tools/dev/` | One-off debug and hardware probe scripts |
| `tests/` | pytest dependency smoke test |

## Helper Tools

```powershell
.venv\Scripts\python tools\capture_templates.py
.venv\Scripts\python tools\bootstrap_gem_classifier.py
.venv\Scripts\python tools\train_gem_classifier.py --port COM27
.venv\Scripts\python tools\dev\test_esp32.py COM27
.venv\Scripts\python tools\dev\test_mouse_paths.py --save
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

- Paths inside `run_farm.py` are anchored to the repo root, so it runs from any cwd.
- Runtime logs go to `logs/`, runner screenshots to `screenshots/gem_farm_test/`.
  Both are ignored by git.
- No tkinter dashboard, no orchestrator/state-machine pipeline.
