"""The frozen executable's entry point.

Thin on purpose: PyInstaller needs a script, and everything real lives in
app.main so the same code path runs from a source checkout.
"""

import multiprocessing
import sys

if __name__ == "__main__":
    # Without this, any library that spawns a process would re-run this script
    # from the top in the child and fork bombs the machine.
    multiprocessing.freeze_support()

    from app.main import main
    sys.exit(main())
