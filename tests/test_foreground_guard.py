"""Every check for "is the game actually in front" threw its answer away.

The capture stack hides this failure completely: WGC grabs the game window's
own pixels, so the log shows a perfectly healthy game frame while another
window sits on top and every HID click goes to that window instead.

Three places asked the question. All three called _ensure_game_focused for
its side effect and ignored the bool it returns, including the one whose own
comment reads "cheapest possible insurance in the most expensive place".

Counted over the whole log: 90 focus losses, 74 fixed by the first ALT+TAB,
11 recovered by SetForegroundWindow, and 5 where the game never came forward
at all. All 5 of those ended in a mine failing on "Not on world map after
toggling" -- three fixed clicks each, landing on whatever the user had open.
"""

import re

from rok_farm import PROJECT_ROOT

FLOW = (PROJECT_ROOT / "rok_farm" / "flow_steps.py").read_text(encoding="utf-8")
CAP = (PROJECT_ROOT / "rok_farm" / "capture_svc.py").read_text(encoding="utf-8")


def test_no_caller_discards_the_verdict():
    """A bare statement call is the bug, in every file that makes one."""
    offenders = []
    for path in ("flow_steps.py", "capture_svc.py", "phases.py"):
        src = (PROJECT_ROOT / "rok_farm" / path).read_text(encoding="utf-8")
        for m in re.finditer(r"^(\s*)(self\._ensure_game_focused\(.*)$",
                             src, re.M):
            offenders.append(f"{path}: {m.group(2).strip()}")
    # phases.py is allowed one: it hands the question on by setting
    # _client_just_returned, and the next mine start is where it is answered.
    allowed = 1
    assert len(offenders) <= allowed, (
        "these calls throw away the focus verdict and click anyway:\n  "
        + "\n  ".join(offenders))


def test_the_mine_start_refuses_to_click_when_it_is_not_in_front():
    start = FLOW.index("start of mine {idx}")
    block = FLOW[start:start + 2400]
    assert "if not focused:" in block, \
        "the mine starts clicking without checking whether the game is in front"
    assert "return False" in block
    assert "NO_FOCUS" in block, "nothing is saved to show what WAS in front"


def test_the_backoff_grows_but_stays_bounded():
    """A human using the machine must not meet a bot retrying every 6 seconds.

    Nor may it back off so far that it misses them leaving.
    """
    # Evaluate the expression the SOURCE uses, not a copy of it here -- a test
    # that restates the formula proves only that it can copy.
    start = FLOW.index("streak = getattr(self, \"_focus_fail_streak\", 0) + 1")
    src = FLOW[start:FLOW.index("return False", start)]
    m = re.search(r"back_off = (.+)", src)
    assert m, "the backoff expression has been renamed or removed"
    expr = m.group(1).strip()

    waits = [eval(expr, {}, {"streak": s}) for s in range(1, 9)]
    assert waits[0] <= 10, "the first retry waits too long to be useful"
    assert waits == sorted(waits), "the backoff does not grow"
    assert waits[3] > waits[0], "it grows too slowly to spare a human working"
    assert max(waits) <= 60, "a minute is long enough to notice they are done"


def test_the_streak_resets_on_success():
    """Otherwise one bad morning makes every later mine wait a minute."""
    assert "self._focus_fail_streak = 0" in FLOW, \
        "the backoff never resets, so it only ever grows"


def test_the_deploy_chain_is_not_fired_blind():
    """The most expensive place: three fixed clicks with no template check."""
    at = FLOW.index("before deploy chain")
    block = FLOW[at - 200:at + 700]
    assert "if not self._ensure_game_focused(\"before deploy chain\")" in block, \
        "the deploy chain still fires whether or not the game is in front"
    assert "return False" in block


def test_client_ready_means_drawing_AND_in_front():
    """Its own docstring lists the foreground failure first, then never checks.

    "the window had not taken the foreground yet, so every click went to
    whatever was in front" -- that is the bug this test pins down.
    """
    at = CAP.index("def _wait_client_ready")
    body = CAP[at:CAP.index("\n    def ", at + 10)]
    assert "focused = self._ensure_game_focused(reason)" in body, \
        "the focus verdict is still discarded"
    assert "FOCUS_RETRIES" in body, "one try is not patience"
    assert "return focused" in body, \
        "ready is still reported without regard to the foreground"


def test_the_retry_count_is_patient_not_infinite():
    from rok_farm.config import FOCUS_RETRIES
    assert 2 <= FOCUS_RETRIES <= 5, (
        f"{FOCUS_RETRIES} rounds of two ALT+TABs each is either not worth "
        f"trying or an ALT+TAB storm")


def test_the_retries_are_paced():
    """An ALT+TAB storm is a tell, and a good way to land on a third window."""
    at = CAP.index("def _wait_client_ready")
    body = CAP[at:CAP.index("\n    def ", at + 10)]
    loop = body[body.index("for _ in range(FOCUS_RETRIES)"):]
    assert "time.sleep(" in loop, "the retries fire back to back"
