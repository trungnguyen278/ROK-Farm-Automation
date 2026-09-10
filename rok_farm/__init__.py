"""ROK gem farm runner package.

The live entry point is `run_farm.py` at the repo root; it only parses CLI args
and hands over to `rok_farm.runner.GemFarmRunner`.

Layout:
    config.py        constants + runtime knobs
    logging_setup.py logger and console colour tokens
    screenshots.py   debug frame dumps
    persona.py       per-account persona traits
    input_hid.py     ESP32 pointer/keyboard output
    capture_svc.py   background capture thread + window geometry
    detect.py        template/colour detection on a frame
    queue_ocr.py     march queue "x/5" OCR
    recovery.py      unstick: ESC back-out, reconnect popup
    button_registry.py  learned button positions; refuses stray clicks
    state_probe.py   local screen state: modal, liveness, city vs world
    vision_llm.py    vision-model escalation when the pixels are not enough
    dismiss.py       closing a popup no template knows, with guardrails
    game_process.py  launch / quit / restart the game client
    flow_steps.py    per-mine flow, steps 1..7
    phases.py        between-burst behaviour (city idle, alt-tab wait)
    runner.py        GemFarmRunner: setup, main loop, teardown
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

# Match the DPI awareness the capture backends assume, before anything grabs a
# frame or reads a window rect.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# Where the project's files live. Everything else derives its paths from this,
# so it is the one place that has to know whether we are running from a source
# checkout or from the packaged app.
#
# Packaged (PyInstaller onedir), the exe sits at the top of the portable folder
# with templates/, profiles/, data/ and firmware/ beside it as plain directories
# -- deliberately NOT bundled into _internal/, so the runner writes learned
# templates and personas exactly where it does from source, and the user can
# see and edit those files. That keeps this the only frozen-aware line in the
# codebase.
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Allow `import capture`, `import vision`, ... regardless of the cwd the runner
# was launched from. Frozen, the packages are already inside the exe.
if not getattr(sys, "frozen", False) and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
