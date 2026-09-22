"""The server-maintenance screen, and how long it says it has left.

2026-09-22 14:21: three mines failed in a row and the reason was not the farm.
The game had gone into maintenance, the launcher had just applied a 374 MB
patch while the client was closed, and the client came back to a notice board
instead of a world. The farm has no idea what that screen is, so it scanned it
for gem deposits, found none, and logged NO_CANDIDATES three times.

The notice carries a countdown, which is the useful part:

    May chu dang bao tri. Thoi gian con lai: 00:38:27

Located by running OCR over the whole frame rather than reading coordinates
off a picture -- it sits at x 0.385-0.616, y 0.592-0.615 with confidence 0.99.
The band searched here is wider than that on every side, because the text
grows and shrinks with the remaining time.

The operator's warning shapes the rest: **the game extends that countdown**.
So it is a hint about when to look again, never a promise, and nothing here
should sleep through it blind.
"""

from __future__ import annotations

import re
import unicodedata

# Generous margins around the measured box: the line is centred, so it spreads
# both ways as the wording changes.
BAND = (0.50, 0.70, 0.22, 0.80)      # y1, y2, x1, x2 as fractions

# What the OCR actually returns for this screen, stripped of diacritics:
# "May chu dang bao tri. Thoi gian con lai: 00:38:27". Two independent marks,
# so a mangled character in one does not lose the screen.
MARKS = ("may chu dang bao tri", "thoi gian con lai")
CLOCK = re.compile(r"(\d{1,2}):([0-5]\d):([0-5]\d)")

# The notice's own refresh button, "LAM MOI". Measured across four kept
# frames its text centres on pct(0.4125, 0.663) with almost no spread --
# 0.412, 0.413, 0.413, 0.413 -- and the four clicks the farm landed on it by
# accident fell at rx 0.399 to 0.414, which is how we know the point is right
# even though the OCR only ever reads "AM MO" out of it. FACEBOOK sits at
# 0.591 on the same row; nothing here should go near it.
REFRESH_AT = (0.4125, 0.663)

# When to press it. The operator's rule, and it is how a person behaves: you
# do not poke a server that has just told you how long it needs. You wait for
# the clock to run out, press refresh once, and then either you are in or the
# notice comes back with more time on it -- "thoi gian tang len do nha phat
# hanh gap su co".
PRESS_WITHIN_S = 25.0
# How often to look while waiting. Randomised, because this can run the best
# part of an hour and a fixed beat is its own tell.
POLL_S = (60.0, 150.0)
# What to do when the screen is there but the clock is not readable.
BLIND_WAIT_S = 900.0
# An outer bound, so a notice that never resolves cannot hold the farm for
# ever without anyone hearing about it.
MAX_HOLD_S = 7200.0


def _flatten(text: str) -> str:
    """Lowercase, no diacritics -- the OCR drops most of them anyway.

    NFD is not enough on its own. Vietnamese d-with-stroke is its own letter,
    not a d carrying a combining mark, so decomposition leaves it standing and
    "dang" never matches "dang". The OCR happens to render it as a plain d,
    which is why the real frame matched while a correctly-typed string did
    not -- the sort of gap that only shows up the day someone pastes the real
    text in.
    """
    text = text.replace("đ", "d").replace("Đ", "D")
    norm = unicodedata.normalize("NFD", text)
    return "".join(c for c in norm if not unicodedata.combining(c)).lower()


def read_lines(frame, ocr) -> list[str]:
    """OCR the notice band. `ocr` is the callable the caller already has."""
    if frame is None:
        return []
    h, w = frame.shape[:2]
    y1, y2, x1, x2 = BAND
    band = frame[int(y1 * h):int(y2 * h), int(x1 * w):int(x2 * w)]
    if band.size == 0:
        return []
    try:
        return [t for t in ocr(band) if t]
    except Exception:
        return []


def is_maintenance(lines) -> bool:
    """True when the notice is on screen.

    Both marks have to appear somewhere in the band. One alone is too thin:
    the word for maintenance turns up in ordinary announcement mail too.
    """
    blob = _flatten(" ".join(lines))
    return all(mark in blob for mark in MARKS)


def seconds_left(lines) -> float | None:
    """The countdown, in seconds, or None if it could not be read."""
    blob = _flatten(" ".join(lines))
    m = CLOCK.search(blob)
    if not m:
        return None
    hours, minutes, secs = (int(g) for g in m.groups())
    total = hours * 3600 + minutes * 60 + secs
    # A clock reading over a day is a misread, not a maintenance window.
    return float(total) if 0 < total < 86400 else None
