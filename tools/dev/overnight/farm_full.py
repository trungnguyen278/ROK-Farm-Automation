"""Overnight full run: loop mode until the march queue is full, wait for troops,
repeat. Vision oracle stays ON (the user has openrouter + ai_mode keys) and game
restart stays enabled so a broken client recovers itself by quitting and pressing
Play again -- both verified working earlier tonight.
"""
import sys
from pathlib import Path

LOG = Path(r"d:\ROK Farm Automation\logs\overnight\farm_run.log")
LOG.parent.mkdir(parents=True, exist_ok=True)
# APPEND, never truncate. The watchdog restarts this script when the farm gets
# stuck, and "w" meant every restart erased the log that showed WHY -- the one
# artefact worth keeping at that exact moment. Appending also keeps the
# watchdog's cumulative counters monotonic across a restart.
_fh = open(LOG, "a", encoding="utf-8", buffering=1)
_fh.write(f"\n{'=' * 62}\n=== farm start {__import__('datetime').datetime.now():%Y-%m-%d %H:%M:%S}\n")
sys.stdout = _fh
sys.stderr = _fh

PROJECT = r"d:\ROK Farm Automation"
sys.path.insert(0, PROJECT)
# Pin the profile. It used to be re-rolled at random every launch, and the
# 2026-08-18 run that drew "aggressive" (07:00-01:00, 10h/day, 1.5min breaks)
# is the one that stayed logged in ~10 hours and earned a scripting warning.
sys.argv = ["run_farm.py", "--port", "COM13", "--loop", "--max-marches", "5",
            "--profile", "cautious"]

import runpy
try:
    runpy.run_path(str(Path(PROJECT) / "run_farm.py"), run_name="__main__")
except SystemExit:
    pass
except Exception:
    import traceback
    traceback.print_exc()
finally:
    print(">>> FARM EXITED <<<", flush=True)
    _fh.flush()
