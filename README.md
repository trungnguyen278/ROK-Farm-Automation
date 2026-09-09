# ROK Farm Automation

CLI-first gem farming automation for Rise of Kingdoms PC.

Entry point is `run_farm.py` at the repo root -- it parses CLI args and hands over
to the `rok_farm/` package. Everything under `tools/` is a dev helper, never
needed for a normal farm run.

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
| `run_farm.py` | Entry point: CLI args only |
| `rok_farm/` | The runner itself, split by responsibility (see below) |
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

### `rok_farm/`

`GemFarmRunner` is one object assembled from mixins, so the flow keeps calling
`self._click` / `self._grab` / `self._find` from anywhere and `PlayerActions`
can still use the runner as its action context.

| Module | Holds |
|---|---|
| `config.py` | Every tuned constant + the runtime knobs |
| `logging_setup.py`, `screenshots.py` | Logger/colour tokens, debug frame dumps |
| `persona.py` | Per-account motor traits that persist between runs |
| `input_hid.py` | Pointer/keyboard output over the ESP32 |
| `capture_svc.py` | Capture thread, frame access, window geometry |
| `detect.py` | Template/colour detection on a frame |
| `queue_ocr.py` | March queue "x/5" OCR |
| `recovery.py` | ESC back-out, reconnect popup |
| `game_process.py` | Launch / quit / restart the game client |
| `button_registry.py` | Where each fixed button has been; refuses stray clicks |
| `state_probe.py` | What is on screen, from the pixels alone (free, instant) |
| `vision_llm.py` | Vision-model escalation when the pixels are not enough |
| `flow_steps.py` | Per-mine flow, steps 1..7 |
| `phases.py` | Between-burst behaviour (city idle, alt-tab wait) |
| `runner.py` | Setup, main loop, teardown, report |

## Screen State

Three layers, cheapest first. Most of the time nothing leaves the machine.

| Layer | What it does | Cost |
|---|---|---|
| 0 `button_registry.py` | Learns where each fixed button lands and refuses a match far outside its own history | free |
| 1 `state_probe.py` | Modal detection (the game dims behind panels), client liveness, city vs world map | free, instant |
| 2 `vision_llm.py` | Asks a vision model, only when layer 1 returns an unknown view or low confidence | ~3 s, ~half a cent a day |

Layer 2 is off unless a provider is configured, and everything degrades to
today's behaviour when it is:

```powershell
# either an API key...
'{"openrouter": "sk-or-..."}' | Out-File -Encoding utf8 profiles\secrets.json
.venv\Scripts\python tools\dev\probe_openrouter.py --live

# ...or the free browser path (no key, ~43s a call)
.venv\Scripts\python -m pip install playwright
.venv\Scripts\python run_farm.py --port COM27 --oracle-provider ai_mode_web
```

Thresholds in `config.py` were measured on the live client, not guessed; the
table and its consequences are documented there. Re-measure with:

```powershell
.venv\Scripts\python tools\dev\measure_state_signals.py --label city
.venv\Scripts\python tools\dev\measure_state_signals.py --summary
```

## Game Lifecycle

The bot starts the game when its window is missing, and quits/relaunches it only
for a long break or a broken client. The ~15 minute march wait stays an alt-tab:
the "troops returned" Windows toast is emitted by the client while it runs in the
background, so quitting would trade a real signal for a blind timer.

```powershell
.venv\Scripts\python tools\capture_launcher_btn.py   # once: teach it the Play button
.venv\Scripts\python run_farm.py --port COM27 --loop --no-auto-launch
.venv\Scripts\python run_farm.py --port COM27 --loop --no-restart
```

`launcher.exe` needs administrator rights. Run the bot from an admin terminal and
the launcher inherits it silently; otherwise Windows shows a UAC prompt that the
bot waits for (it never clicks the prompt -- the secure desktop is invisible to
every capture backend). The launcher path is resolved from `--launcher-path`, the
`ROK_LAUNCHER_PATH` env var, `profiles/paths.json`, the Start Menu shortcut, then
the registry -- it is never hardcoded.

## Helper Tools

```powershell
.venv\Scripts\python tools\capture_launcher_btn.py --start
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

- Paths are anchored to the repo root (`rok_farm/__init__.py`), so it runs from any cwd.
- Runtime logs go to `logs/`, runner screenshots to `screenshots/gem_farm_test/`.
  Both are ignored by git.
- No tkinter dashboard, no orchestrator/state-machine pipeline.
