"""Console plumbing for the packaged app: encoding, colour, prompts, text.

Two problems this solves before anything is printed.

**Encoding.** The UI is Vietnamese, and the legacy Windows console code page
(cp1252) cannot encode a single accented Vietnamese vowel -- printing one
raises UnicodeEncodeError and takes the process down. So the console is put
into UTF-8 at import, and `say()` still folds text to ASCII if a write fails
anyway (an old console, a redirected pipe, a terminal that ignores the code
page). A setup wizard that crashes on its own first line is worse than one
that prints "Bat dau".

**Language.** Vietnamese by default, English via ROK_LANG=en, because the
person setting this up and the person reading the source are not always the
same. Every user-facing string is a (vi, en) pair -- see t().
"""

from __future__ import annotations

import os
import sys
import unicodedata

LANG = (os.environ.get("ROK_LANG") or "vi").lower()[:2]
if LANG not in ("vi", "en"):
    LANG = "vi"


def _init_console() -> None:
    """Put stdout/stderr and the Windows console itself into UTF-8."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    # stdin too, and not for symmetry: the frozen build was decoding input as
    # cp1252, so a UTF-8 BOM (PowerShell puts one in front of anything it
    # pipes) arrived as the three characters "i>¿" and every menu choice
    # missed. errors="replace" so a stray byte cannot kill the prompt.
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


_init_console()


def fold(s: str) -> str:
    """Vietnamese without the diacritics, for a console that cannot show them."""
    s = s.replace("đ", "d").replace("Đ", "D")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def say(*parts, **kw) -> None:
    """print(), but a console that cannot encode the text loses accents, not the run."""
    text = " ".join(str(p) for p in parts)
    try:
        print(text, **kw)
    except UnicodeEncodeError:
        print(fold(text), **kw)


def t(vi: str, en: str) -> str:
    """Pick the active language's wording."""
    return vi if LANG == "vi" else en


# ------------------------------------------------------------------ colour

def _colour_ok() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.name != "nt":
        return sys.stdout.isatty()
    try:
        import ctypes
        h = ctypes.windll.kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not ctypes.windll.kernel32.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        ctypes.windll.kernel32.SetConsoleMode(h, mode.value | 0x0004)
        return True
    except Exception:
        return False


COLOUR = _colour_ok()


def _c(code: str) -> str:
    return code if COLOUR else ""


RESET = _c("\033[0m")
DIM = _c("\033[2m")
BOLD = _c("\033[1m")
GREEN = _c("\033[32m")
YELLOW = _c("\033[33m")
RED = _c("\033[31m")
CYAN = _c("\033[36m")


def ok(msg: str) -> None:
    say(f"{GREEN}[OK]{RESET} {msg}")


def warn(msg: str) -> None:
    say(f"{YELLOW}[!]{RESET} {msg}")


def bad(msg: str) -> None:
    say(f"{RED}[X]{RESET} {msg}")


def info(msg: str) -> None:
    say(f"{CYAN}[i]{RESET} {msg}")


def step(n: int, total: int, msg: str) -> None:
    say(f"\n{BOLD}=== {n}/{total}  {msg}{RESET}")


def title(msg: str) -> None:
    line = "=" * max(len(msg) + 4, 46)
    say(f"\n{BOLD}{line}\n  {msg}\n{line}{RESET}")


def rule() -> None:
    say(DIM + "-" * 46 + RESET)


# ------------------------------------------------------------------ input

class Closed(Exception):
    """stdin ended: the window was closed, or there was never a console.

    Raised rather than returned so no caller can mistake "the user pressed
    Enter" for "there is nobody there". A menu that treats EOF as an empty
    answer loops forever at full speed, which is exactly what it did.
    """


def ask(prompt: str, default: str = "") -> str:
    """One line of input. Raises Closed on EOF or Ctrl+C."""
    suffix = f" [{default}]" if default else ""
    try:
        say(f"{prompt}{suffix}: ", end="")
        sys.stdout.flush()
        got = input()
    except (EOFError, KeyboardInterrupt):
        say("")
        raise Closed from None
    # PowerShell puts a UTF-8 BOM in front of anything it pipes into a child
    # process. Strip it decoded (﻿) and, belt and braces, in the mojibake
    # form an 8-bit stdin would have produced.
    got = got.lstrip("﻿")
    if got.startswith("ï»¿"):
        got = got[3:]
    return got.strip() or default


def confirm(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    got = ask(f"{prompt} ({hint})").lower()
    if not got:
        return default
    return got[0] in "yc"  # y / yes, c / co ("có")


def pause() -> None:
    """Wait for Enter, but never block a run with no console behind it."""
    try:
        ask(t("Nhấn Enter để tiếp tục", "Press Enter to continue"))
    except Closed:
        pass
