"""A one-bit channel from the remote control to a farm that is asleep.

The farm spends most of its time waiting out a gather -- tabbed away, or with
the client closed entirely. Until now the only way to make it look at the queue
sooner was to stop it and start it again, which throws away the march
bookkeeping and costs a client restart on top. The player watches the game on
their phone and often knows troops are home well before the bot's estimate says
so; this lets them say it.

A file, not a signal or a socket. The farm may have been started by the bot, by
the watchdog, or by hand, in a different console at a different time, and the
only thing both sides reliably agree on is where the project lives. A file also
survives the gap between "asked" and "noticed", which matters when the sleeping
side only looks every few seconds.

The note is carried through so the log can say who asked and why, rather than
the wait simply ending early for no recorded reason.
"""

from __future__ import annotations

import time

from rok_farm import PROJECT_ROOT
from rok_farm.logging_setup import logger

WAKE_FILE = PROJECT_ROOT / "data" / "wake.flag"


def request(note: str = "") -> bool:
    """Ask a sleeping farm to cut its wait short. Returns False if it could
    not be written, so the caller can say so rather than promise silently."""
    try:
        WAKE_FILE.parent.mkdir(parents=True, exist_ok=True)
        WAKE_FILE.write_text(f"{time.time():.0f}\n{note}", encoding="utf-8")
        return True
    except Exception as e:
        logger.warning("Could not write the wake flag: %s", e)
        return False


def consume() -> str | None:
    """The note, if a wake was asked for, removing the request.

    Consuming rather than reading: a flag left in place would end every
    subsequent wait too, which is the opposite of what was asked.
    """
    try:
        if not WAKE_FILE.exists():
            return None
        raw = WAKE_FILE.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        logger.warning("Could not read the wake flag: %s", e)
        return None
    finally:
        try:
            WAKE_FILE.unlink(missing_ok=True)
        except Exception:
            pass
    return (raw[1] if len(raw) > 1 and raw[1].strip() else "no reason given")


def clear() -> None:
    """Drop any request left over from a previous run.

    A flag written while the last farm was dying would otherwise be the first
    thing the new one finds, and it would skip a wait it never actually made.
    """
    try:
        WAKE_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def pending() -> bool:
    """Is a request waiting? Does not consume it -- for status reporting."""
    try:
        return WAKE_FILE.exists()
    except Exception:
        return False
