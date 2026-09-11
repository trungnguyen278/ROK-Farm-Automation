"""Reading the farm log: the pure functions the watchdog decides on.

Split out of watchdog2 so they can be tested. watchdog2 runs its poll loop at
module level, so importing it starts supervising -- which meant none of the
analysis it halts a run on could ever be exercised by a test, and the bugs in it
had to be found by watching production.

Nothing here touches a process or the clock. Given log text, it answers
questions about it.
"""
import re

PATTERNS = {
    "mine_done":    r"Mine \d+ DONE",
    "mine_failed":  r"Mine \d+ FAILED",
    "empty_scan":   r"no icons",
    "scan_giveup":  r"consecutive empty scans",
    "fog_bail":     r"FOG \(out of kingdom\)",
    "clf_reject":   r"Classifier reject|Classifier REJECT",
    "color_reject": r"Color reject|color REJECT",
    "gather_miss":  r"gather_btn not found",
    "refused":      r"Refusing click",
    "march_sent":   r"March sent",
    # Only FAULT restarts. The farm now quits the client on purpose while
    # troops are out ("waiting Nmin for troops"), and counting those as
    # failures would trip the 5-per-hour halt on a perfectly healthy run.
    "restart":      r"Restarting the game: (?!waiting )",
    "world_fail":   r"Not on world map after toggling",
    "recovery":     r"attempting recovery",
    "skip_clicked": r"Skip already-clicked icon",
    "occupied":     r"occupied \(",
    # A PLANNED wait: the farm quit the client on purpose and is sleeping
    # out a gather. It produces no mines and no flow steps BY DESIGN, so
    # every "is it stuck" clock must count it as activity. Three separate
    # thresholds tripped on this before it was handled.
    "planned_wait": r"Staying out for|Still out, \d+ min to go",
    # The farm quit its client for a planned wait and then could not get it
    # back: the launcher would not come to the front, the Play button matched
    # at 0.634, and after 180s there was no game window. Terminal -- on
    # 2026-09-11 the farm produced no mine and no client-ready line afterwards
    # and sat there until a human stopped it by hand.
    #
    # Nothing else here would have caught it. The log kept growing (relaunch
    # attempts), no mine was failing because none could start, and the
    # 75-minute stuck clock had barely begun. Rare -- once in three weeks --
    # but it costs the rest of the night every time.
    "client_dead":  r"Game did not come back up|No game window after \d+s",
}

# Lines the CAPTURE THREAD emits. It is a daemon that grabs frames forever,
# entirely independently of whether the flow is making progress, so its output
# is not evidence of life -- and counting it as such is what blinded the silence
# check on 2026-08-18: the main thread sat in a 1025s sleep in front of a
# reconnect dialog, the client died underneath it, and the log still grew by a
# "Window 'Rise of Kingdoms' not found" line every 10s for 17 minutes. Byte
# growth said healthy the whole time. Silence is judged on everything else.
#
# The trailing \n matters and its absence made the original fix ineffective:
# `^.*$` under MULTILINE stops BEFORE the newline, so blanking the line left
# the newline behind and the stripped log still grew by exactly one byte per
# capture line. The capture thread logs every ~10s forever, so `size !=
# last_size` stayed true on every poll and the silence check could never fire
# -- the same "byte growth is not life" failure it was written to fix, one
# character smaller.
CAPTURE_NOISE = re.compile(
    r"^.*(?:capture\.screen_capture|vision\.template_cache):.*$\n?",
    re.MULTILINE)

# A dead command channel means the farm stays alive and stops clicking, so it
# is worth watching for directly. But "Access is denied" on its own is a
# GENERIC Windows error string, and on this machine it is overwhelmingly
# SetForegroundWindow being refused -- which is expected here, because the
# foreground lock timeout is effectively infinite so a background process can
# never take focus. Measured over the whole log: 13 lines matched the old
# pattern and 12 of them were SetForegroundWindow, one was a real serial fault.
# A 92% false-positive rate on a rule that can trigger a farm restart.
#
# So: the serial exceptions by name, plus an access denial only when it comes
# from the serial subsystem itself -- which is the case that matters, a COM
# port held by another process.
SERIAL_FAULT = re.compile(
    r"SerialException|Serial lost during|serial_comm\.[\w.]+:.*Access is denied")

CLICK_RE = re.compile(
    r"\[(\d+)\] Clicking icon conf=[\d.]+ at \((\d+), (\d+)\)")

ATTEMPT_RE = re.compile(
    r"\[(\d+)\] (?:gather_btn|re-check|after mine click)")

# Two clicks this close are the same node. Measured, not chosen: across 217
# consecutive-attempt pairs in the whole log, the CLOSEST two distinct nodes
# ever clicked were 81px apart (p5=122, median=405). Nothing legitimate has
# ever come within 60px, so this cannot fire on ordinary play.
CIRCLE_PX = 60

# A count so far outside the record that it is worth saying regardless of where
# the clicks landed. The highest attempt index in the entire log is 7.
EXTREME_ATTEMPTS = 8

TAIL = 6000


def counts(text):
    return {k: len(re.findall(p, text)) for k, p in PATTERNS.items()}


def flow_size(text):
    """Length of the log with capture-thread chatter removed."""
    return len(CAPTURE_NOISE.sub("", text))


def current_run(text):
    """Just the newest run. The log is append-mode across restarts on purpose.

    Counting over the whole file meant the 14 failures that triggered a
    relaunch were still the newest events a second later, so a freshly started
    farm inherited the verdict on its predecessor and was halted again before
    producing a single line of its own.
    """
    marker = "=== farm start "
    return text[text.rfind(marker):] if marker in text else text


def max_attempt_index(text, tail_chars=TAIL):
    """Highest per-mine attempt number seen recently.

    The flow prints "[3] gather_btn ..." where the bracket counts attempts
    within one mine. Only the tail is scanned so an old spike does not shadow
    the current state.
    """
    return max((int(h) for h in ATTEMPT_RE.findall(text[-tail_chars:])),
               default=0)


def circling_evidence(text, tail_chars=TAIL):
    """Is the bot clicking the SAME node over and over? Reason, or None.

    The old alert fired on the attempt COUNT alone, on the theory that a high
    count meant "it kept going back to the same area". Measured against the
    log, that theory is simply false: 160 of 1398 readings reached 3 or more,
    and of the 217 consecutive-attempt pairs, not one clicked the same place.
    A high count is the ordinary business of trying successive occupied mines.
    So the alert fired roughly every eleventh reading and had never once been
    right -- noise in the channel where a real ban-shaped behaviour would show.

    What circling actually looks like is two attempts in a row landing on the
    same pixel, so that is what is tested. The count survives only as a
    fallback, above anything ever recorded.
    """
    clicks = [(int(a), int(x), int(y))
              for a, x, y in CLICK_RE.findall(text[-tail_chars:])]
    for prev, cur in zip(clicks, clicks[1:]):
        if cur[0] != prev[0] + 1:
            continue                      # not consecutive attempts on one mine
        gap = max(abs(cur[1] - prev[1]), abs(cur[2] - prev[2]))
        if gap <= CIRCLE_PX:
            return (f"attempts {prev[0]} and {cur[0]} clicked {gap}px apart "
                    f"-- same node twice")
    n = max_attempt_index(text, tail_chars)
    if n >= EXTREME_ATTEMPTS:
        return f"{n} attempts within one mine (record is 7)"
    return None
