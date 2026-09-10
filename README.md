# ROK Farm Automation

Gem farming for Rise of Kingdoms PC. Vision on the screen, real USB HID out
through an ESP32-S3, driven from a terminal or from Discord.

```text
game window -> capture -> vision/classifier -> flow -> serial -> ESP32-S3 -> USB HID
```

**Just want to use it?** → **[docs/SETUP.vi.md](docs/SETUP.vi.md)** (tiếng Việt)
· **[docs/SETUP.en.md](docs/SETUP.en.md)** (English)

Those cover the packaged app, which needs no Python and no PlatformIO: it
detects the board, flashes the prebuilt firmware itself, and walks the Discord
setup. The rest of this file is for working on the code.

## Run it

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

.venv\Scripts\python -m app.main            # the menu, same as the packaged app
.venv\Scripts\python run_farm.py --count 2  # straight to the farm
```

`--port` is optional everywhere: the board is found by its bridge's VID:PID,
because Windows reassigns COM numbers across reboots and re-plugs.

Useful options:

```powershell
.venv\Scripts\python run_farm.py --find-only
.venv\Scripts\python run_farm.py --loop --max-marches 5 --no-screenshots
.venv\Scripts\python run_farm.py --count 2 --auto-learn
```

## Layout

| Path | Purpose |
|---|---|
| `run_farm.py` | Entry point: CLI args only |
| `rok_farm/` | The runner itself, split by responsibility (see below) |
| `app/` | The packaged app's face: menu, first-run wizard, console plumbing |
| `capture/` | Window finding and screen capture |
| `vision/` | Template matching, gem colour filter, k-NN gem classifier |
| `anti_detection/` | Mouse movement, timing/session helpers, distraction actions |
| `serial_comm/` | Text protocol, serial connection, command buffer |
| `esp32-s3/` | PlatformIO firmware source |
| `firmware/` | **Prebuilt** board images + `manifest.json`, committed |
| `packaging/` | PyInstaller spec and the build script |
| `templates/` | OpenCV templates used by the runner |
| `profiles/` | Behaviour profiles; `paths.json` and `secrets.json` are local |
| `docs/` | Setup guides, plan, specs |
| `tools/` | Capture/train/flash/calibration helpers |
| `tools/dev/` | One-off debug and hardware probes |
| `tools/remote/` | The Discord bot |
| `tests/` | pytest |

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
| `roles.py` | How to start the farm/watchdog/bot, from source or frozen |
| `session_control.py` | Start, stop, find and inspect a run — no Discord involved |
| `runner.py` | Setup, main loop, teardown, report |

## Processes

Three that outlive each other, found by scanning command lines rather than a
remembered pid — so any of them can be restarted without losing the others.

| Role | Does | Started by |
|---|---|---|
| `farm` | The run itself | menu item 2, `!start`, or the watchdog |
| `watchdog` | Restarts a wedged farm | alongside the farm |
| `bot` | Discord remote control | menu item 4, or `start_bot.bat` |

`rok_farm/roles.py` is the one place that knows a role is a `.py` file under a
venv from source, and an argument to a single exe when packaged.
`rok_farm/session_control.py` is the switchboard both the menu and the Discord
bot drive, so those two cannot drift apart.

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
.venv\Scripts\python run_farm.py --oracle-provider ai_mode_web
```

Thresholds in `config.py` were measured on the live client, not guessed; the
table and its consequences are documented there. Re-measure with:

```powershell
.venv\Scripts\python tools\dev\measure_state_signals.py --label city
.venv\Scripts\python tools\dev\measure_state_signals.py --summary
```

## Game Lifecycle

The bot starts the game when its window is missing, and quits/relaunches it
only for a long break or a broken client. The ~15 minute march wait stays an
alt-tab: the "troops returned" Windows toast is emitted by the client while it
runs in the background, so quitting would trade a real signal for a blind timer.

```powershell
.venv\Scripts\python tools\capture_launcher_btn.py   # once: teach it the Play button
.venv\Scripts\python run_farm.py --loop --no-auto-launch
.venv\Scripts\python run_farm.py --loop --no-restart
```

`launcher.exe` needs administrator rights. Run from an admin terminal and the
launcher inherits it silently; otherwise Windows shows a UAC prompt that the
bot waits for (it never clicks the prompt — the secure desktop is invisible to
every capture backend). The launcher path is resolved from `--launcher-path`,
the `ROK_LAUNCHER_PATH` env var, `profiles/paths.json`, the Start Menu
shortcut, then the registry — it is never hardcoded.

## Firmware

`firmware/` holds the four flashable images and a `manifest.json` naming their
offsets, so a user flashes with `tools/flash_board.py` and never installs a C++
toolchain. The flasher auto-detects the board, refuses to touch the wrong USB
socket, and skips a board that already answers PING.

Rebuild after changing `esp32-s3/src/main.cpp`:

```powershell
cd esp32-s3
pio run            # the post-build hook rewrites ../firmware/
```

Two constraints are pinned in `platformio.ini` and worth not rediscovering:

- The platform is **pioarduino**, not `platformio/espressif32`. `main.cpp`
  needs `USBHIDAbsoluteMouse`, which arrived in arduino-esp32 3.1; the
  registry's espressif32 still resolves to core 2.0.17 at every version tried.
- Run `pio` from **PowerShell or CMD**. The pioarduino installer refuses
  MSys/Git Bash, and `pio run` reports an unknown board with **exit code 0** —
  so a broken toolchain looks like a successful build.

## Packaging

```powershell
.venv\Scripts\python packaging\build.py            # folder + zip
.venv\Scripts\python packaging\build.py --no-zip   # while iterating
```

Produces `dist/ROK Farm/` — a portable folder with `ROK Farm.exe` at the top
and `templates/`, `profiles/`, `data/`, `firmware/` beside it as ordinary
directories. That layout is not incidental: frozen, `rok_farm/__init__.py`
resolves `PROJECT_ROOT` to the exe's own folder, so the runner reads and writes
those paths exactly as it does from source.

## Helper Tools

```powershell
.venv\Scripts\python tools\flash_board.py --check
.venv\Scripts\python tools\capture_launcher_btn.py --start
.venv\Scripts\python tools\capture_templates.py
.venv\Scripts\python tools\bootstrap_gem_classifier.py
.venv\Scripts\python tools\train_gem_classifier.py
.venv\Scripts\python tools\dev\test_esp32.py COM13
.venv\Scripts\python tools\dev\test_mouse_paths.py --save
```

## Notes

- Paths are anchored to `PROJECT_ROOT` in `rok_farm/__init__.py`, so it runs
  from any cwd and from inside the packaged exe.
- Runtime logs go to `logs/`, runner screenshots to `screenshots/gem_farm_test/`.
  Both are ignored by git.
- No tkinter dashboard, no orchestrator/state-machine pipeline.
