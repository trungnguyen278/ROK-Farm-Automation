"""The frozen executable's entry point.

Thin on purpose: PyInstaller needs a script, and everything real lives in
app.main so the same code path runs from a source checkout.

The one thing it does add is a crash net. The build is windowed, so a
traceback has nowhere to print -- without this, a startup failure looks like
double-clicking the exe and nothing happening at all, which is the single
worst thing that can happen to someone non-technical.
"""

import multiprocessing
import sys
import traceback
from datetime import datetime
from pathlib import Path


def _report_crash(exc_text: str) -> None:
    """Write the traceback somewhere findable, then say so in a dialog."""
    where = Path(sys.executable).resolve().parent / "logs" / "crash.log"
    try:
        where.parent.mkdir(parents=True, exist_ok=True)
        with where.open("a", encoding="utf-8") as fh:
            fh.write(f"\n{'=' * 60}\n{datetime.now():%Y-%m-%d %H:%M:%S}\n")
            fh.write(exc_text)
    except Exception:
        pass
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror(
            "ROK Farm",
            "Ung dung gap loi khi khoi dong.\n\n"
            f"Chi tiet da ghi vao:\n{where}\n\n"
            f"{exc_text.strip().splitlines()[-1] if exc_text.strip() else ''}")
        root.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    # Without this, any library that spawns a process would re-run this script
    # from the top in the child and fork bomb the machine.
    multiprocessing.freeze_support()

    try:
        from app.main import main
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        _report_crash(traceback.format_exc())
        sys.exit(1)
