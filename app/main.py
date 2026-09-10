"""The packaged app: one executable that answers to a role name.

Double-clicked with no arguments it shows a menu. Given a role it becomes that
role, which is how the farm, the watchdog and the Discord bot start each other
without a venv or a .py file on disk:

    ROK Farm.exe                 -> menu
    ROK Farm.exe farm            -> the overnight farm loop
    ROK Farm.exe watchdog <pid>  -> the supervisor for that farm
    ROK Farm.exe bot             -> the Discord remote control
    ROK Farm.exe report          -> the post-run report
    ROK Farm.exe flash           -> detect and flash the ESP32
    ROK Farm.exe setup           -> the first-run wizard

Each role runs the SAME module the source checkout runs -- nothing is
reimplemented here. The one adjustment is sys.argv: those modules were written
as scripts and read their own arguments, so argv is rewritten to the shape
they expect before they are imported. The real process command line is
untouched, which matters because that is what roles.matches() scans to find a
running farm.
"""

from __future__ import annotations

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import ui
from app.ui import t


def _become(script_name: str, module: str, args: list[str], call_main: bool):
    """Run `module` as if it had been started as `script_name` with `args`."""
    import importlib
    sys.argv = [script_name, *args]
    mod = importlib.import_module(module)
    if call_main:
        return mod.main()
    return 0


def role_farm(args):
    # farm_full does its work at import: it redirects stdout to the run log
    # first, so anything printed after this line lands in the log, not here.
    return _become("farm_full.py", "tools.dev.overnight.farm_full", args, False)


def role_watchdog(args):
    if not args:
        ui.bad(t("Thiếu PID của farm. Dùng: watchdog <pid>",
                 "Missing the farm's pid. Usage: watchdog <pid>"))
        return 2
    # watchdog2 reads sys.argv[1] as the pid and loops at import time.
    return _become("watchdog2.py", "tools.dev.overnight.watchdog2", args, False)


def role_bot(args):
    return _become("discord_bot.py", "tools.remote.discord_bot", args, True)


def role_report(args):
    return _become("report.py", "tools.dev.overnight.report", args, True)


def role_flash(args):
    return _become("flash_board.py", "tools.flash_board", args, True)


def role_setup(args):
    from app import wizard
    return wizard.run()


def role_menu(args):
    from app import menu
    return menu.run()


ROLES = {
    "farm": role_farm,
    "watchdog": role_watchdog,
    "bot": role_bot,
    "report": role_report,
    "flash": role_flash,
    "setup": role_setup,
    "menu": role_menu,
}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    role = argv[0] if argv else "menu"
    if role in ("-h", "--help"):
        ui.say(__doc__)
        return 0
    fn = ROLES.get(role)
    if fn is None:
        ui.bad(t(f"Không biết chế độ '{role}'. Có: {', '.join(ROLES)}",
                 f"Unknown role '{role}'. Known: {', '.join(ROLES)}"))
        return 2
    return fn(argv[1:]) or 0


if __name__ == "__main__":
    raise SystemExit(main())
