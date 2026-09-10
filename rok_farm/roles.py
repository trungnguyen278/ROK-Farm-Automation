"""How to start each of this project's long-lived processes, from either shape.

The farm, the watchdog and the Discord bot are separate OS processes that find
and control each other. From a source checkout each is a .py file run by the
venv's python; in the packaged app there is no venv and no .py file on disk --
one exe answers to a role name instead (`ROK Farm.exe farm`).

Both shapes are described here so nothing else has to care which one it is in.
Two things need it:

  * spawning       -- command() builds the argv
  * discovery      -- the bot and watchdog find a running farm by scanning
                      command lines, so needle() gives the substring that
                      identifies a role in either shape

Getting discovery wrong is the expensive failure: the bot would report "no farm
running" while a farm is running, and !start would launch a second one on top
of the first, two boards' worth of input into one client.
"""

from __future__ import annotations

import sys
from pathlib import Path

from rok_farm import PROJECT_ROOT

FROZEN = getattr(sys, "frozen", False)

# role -> path of the script that implements it, relative to the project root
SCRIPTS = {
    "farm": Path("tools") / "dev" / "overnight" / "farm_full.py",
    "watchdog": Path("tools") / "dev" / "overnight" / "watchdog2.py",
    "bot": Path("tools") / "remote" / "discord_bot.py",
    "report": Path("tools") / "dev" / "overnight" / "report.py",
}


def python_exe() -> Path:
    """The interpreter that runs this project's scripts.

    Frozen there is none, and callers must use command() instead. From source
    prefer the venv over sys.executable: the bot can be started by a bare
    `python discord_bot.py` from any interpreter, and the farm it spawns still
    has to be the one with opencv and the rest installed.
    """
    venv = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    return venv if venv.is_file() else Path(sys.executable)


def command(role: str, *args) -> list[str]:
    """argv that starts `role`, in whichever shape we are running."""
    if role not in SCRIPTS:
        raise KeyError(f"unknown role {role!r}; known: {sorted(SCRIPTS)}")
    if FROZEN:
        return [sys.executable, role, *(str(a) for a in args)]
    return [str(python_exe()), str(PROJECT_ROOT / SCRIPTS[role]),
            *(str(a) for a in args)]


def needle(role: str) -> str:
    """Substring that identifies `role` in a running process's command line.

    Frozen, every role shares one exe name, so the role word in argv is the
    only thing that tells them apart -- and it is padded with spaces so the
    "bot" role cannot match a path that merely contains "bot".
    """
    if FROZEN:
        return f" {role}"
    return SCRIPTS[role].name


def matches(role: str, cmdline: list[str] | None) -> bool:
    """True when `cmdline` belongs to a process running `role`."""
    if not cmdline:
        return False
    joined = " ".join(cmdline)
    if not FROZEN:
        return needle(role) in joined
    # Frozen: the role is argv[1] exactly. Substring matching on a single word
    # is what would let "report" match a --report flag somewhere.
    return len(cmdline) > 1 and cmdline[1] == role
