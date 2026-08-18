"""Overnight full run: loop mode until the march queue is full, wait for troops,
repeat. Vision oracle stays ON (the user has openrouter + ai_mode keys) and game
restart stays enabled so a broken client recovers itself by quitting and pressing
Play again -- both verified working earlier tonight.
"""
import sys
from pathlib import Path

LOG = Path(r"d:\ROK Farm Automation\logs\overnight\farm_run.log")
_fh = open(LOG, "w", encoding="utf-8", buffering=1)
sys.stdout = _fh
sys.stderr = _fh

PROJECT = r"d:\ROK Farm Automation"
sys.path.insert(0, PROJECT)
sys.argv = ["run_farm.py", "--port", "COM13", "--loop", "--max-marches", "5"]

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
