"""Overnight full run: loop mode until the march queue is full, wait for troops,
repeat. Vision oracle stays ON when a key is configured, and game restart stays
enabled so a broken client recovers itself by quitting and pressing Play again.

This is the process the Discord bot and the watchdog start and supervise, so
its identity matters: they find it by command line (see rok_farm/roles.py).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from rok_farm import PROJECT_ROOT

LOG = PROJECT_ROOT / "logs" / "overnight" / "farm_run.log"
LOG.parent.mkdir(parents=True, exist_ok=True)
# APPEND, never truncate. The watchdog restarts this script when the farm gets
# stuck, and "w" meant every restart erased the log that showed WHY -- the one
# artefact worth keeping at that exact moment. Appending also keeps the
# watchdog's cumulative counters monotonic across a restart.
_fh = open(LOG, "a", encoding="utf-8", buffering=1)
_fh.write(f"\n{'=' * 62}\n=== farm start {__import__('datetime').datetime.now():%Y-%m-%d %H:%M:%S}\n")
sys.stdout = _fh
sys.stderr = _fh

# No --port. Windows reassigns COM numbers across reboots and re-plugs, so a
# pinned number is a promise the OS does not keep; SerialConnection finds the
# board by its CH340 VID:PID instead.
#
# Pin the PROFILE though. It used to be re-rolled at random every launch, and
# the 2026-08-18 run that drew "aggressive" (07:00-01:00, 10h/day, 1.5min
# breaks) is the one that stayed logged in ~10 hours and earned a scripting
# warning.
sys.argv = ["run_farm.py", "--loop", "--max-marches", "5",
            "--profile", "cautious"]

# Import rather than runpy(<path>): packaged there is no run_farm.py on disk,
# only the module compiled into the exe.
import run_farm
try:
    run_farm.main()
except SystemExit:
    pass
except Exception:
    import traceback
    traceback.print_exc()
finally:
    print(">>> FARM EXITED <<<", flush=True)
    _fh.flush()
