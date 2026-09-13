"""Mail and alliance gifts are checked on the way OUT, and nowhere else.

Both used to run during the city idle and both were removed for the same
reason: they open a panel, and a panel that fails to close strands the bot in
a screen no step knows how to leave. It was the alliance panel it was seen
hanging on.

That reasoning holds everywhere except immediately before a planned quit. The
next thing that runs there is ALT+F4, which closes the window whatever panel
is open, and the client comes back with none -- which is the operator's own
argument for putting alliance back on 2026-09-13. The one failure that removed
these cannot happen on that path, and that is the whole point of the
condition.
"""

import ast

from rok_farm import PROJECT_ROOT

PHASES = (PROJECT_ROOT / "rok_farm" / "phases.py").read_text(encoding="utf-8")
ACTIONS = (PROJECT_ROOT / "anti_detection" / "player_actions.py").read_text(
    encoding="utf-8")


def calls_in(src, name):
    """Line numbers where `name` is called, from the parse tree."""
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        attr = getattr(f, "attr", None) or getattr(f, "id", None)
        if attr == name:
            out.append(node.lineno)
    return out


def test_the_mail_check_exists_and_is_called_once():
    assert "_check_panels_before_quit" in PHASES
    assert len(calls_in(PHASES, "_check_panels_before_quit")) == 1, \
        "mail is checked from more than one place, so the condition is not " \
        "'only before quitting'"


def test_it_runs_on_the_planned_quit_and_not_the_recovery_one():
    """_restart_game is also the recovery path, where the client may be the
    broken thing and poking a panel into it is the worst possible moment."""
    at = PHASES.index("_check_panels_before_quit()")
    after = PHASES[at:at + 400]
    assert "_restart_game(" in after, \
        "the mail check is not immediately before a quit"
    assert "waiting " in after, \
        "the quit it precedes is not the PLANNED one"

    runner = (PROJECT_ROOT / "rok_farm" / "runner.py").read_text(encoding="utf-8")
    assert "_check_panels_before_quit" not in runner, \
        "the recovery restarts in runner.py now check mail too"


def test_it_runs_before_the_quit_not_after():
    at = PHASES.index("_check_panels_before_quit()")
    assert at < PHASES.index('_restart_game(f"waiting'), \
        "mail is checked after the client has already been told to close"


def test_a_failure_in_it_cannot_stop_the_quit():
    """A nicety must never block the real work."""
    start = PHASES.index("def _check_panels_before_quit")
    body = PHASES[start:PHASES.index("\n    def ", start + 10)]
    assert "try:" in body and "except Exception" in body, \
        "an exception in the mail routine would propagate and skip the quit"
    assert "raise" not in body


def test_it_opens_nothing_when_there_is_no_new_mail():
    """The badge gate is what keeps this from being a fixed ritual before
    every quit, and what keeps the log an honest record of when mail arrived."""
    start = ACTIONS.index("def act_mail")
    head = ACTIONS[start:start + 600]
    assert "_mail_btn_has_badge" in head
    assert "return" in head


def test_what_it_finds_reaches_the_log_not_only_the_terminal():
    """The account owner reads this to see how often recall and warning
    letters arrive; a print only reaches whoever was watching at the time."""
    start = ACTIONS.index("def act_mail")
    body = ACTIONS[start:ACTIONS.index("\ndef ", start + 10)]
    assert "logger.info" in body, "the mail check leaves no record in the log"
    assert body.count("logger.info") >= 3, (
        "not enough of the outcome is logged to compare frequency later: "
        "expected at least 'no badge', 'how many tabs' and 'read all'")


# --- alliance, back on the operator's call 2026-09-13 --------------------

def test_alliance_is_opened_here_and_only_here():
    """It stays out of the random idle pools; this is its one caller."""
    from anti_detection.player_actions import SELECTABLE, ACTION_REGISTRY

    assert "alliance" not in SELECTABLE, \
        "alliance is selectable again, so it can fire at any moment instead " \
        "of only on the way out"
    assert "alliance" in ACTION_REGISTRY, \
        "the implementation is gone, so the deliberate call cannot work"

    start = PHASES.index("def _check_panels_before_quit")
    body = PHASES[start:PHASES.index("\n    def ", start + 10)]
    assert '"alliance"' in body


def test_alliance_is_not_every_single_exit():
    """The operator asked for it back but "khong can qua thuong xuyen".

    Mail is every time, because the point of mail is an honest record of when
    recall letters arrive and a patchy record is no record. Alliance carries
    no record, so it can be thinned.
    """
    from rok_farm.phases import PhasesMixin

    assert 0 < PhasesMixin.ALLIANCE_BEFORE_QUIT_CHANCE < 1, \
        "alliance runs on every exit or never; neither is what was asked"


def test_mail_is_not_thinned():
    start = PHASES.index("def _check_panels_before_quit")
    body = PHASES[start:PHASES.index("\n    def ", start + 10)]
    at = body.index('jobs = ["mail"]')
    assert "random.random()" not in body[:at], \
        "mail is now behind a chance too, which breaks the frequency record"


def test_the_order_is_not_fixed():
    """Two panels in the same sequence before every exit is itself a pattern."""
    start = PHASES.index("def _check_panels_before_quit")
    body = PHASES[start:PHASES.index("\n    def ", start + 10)]
    assert "shuffle" in body


def test_one_failing_panel_does_not_skip_the_other_or_the_quit():
    start = PHASES.index("def _check_panels_before_quit")
    body = PHASES[start:PHASES.index("\n    def ", start + 10)]
    loop = body[body.index("for job in jobs:"):]
    assert "try:" in loop and "except Exception" in loop, \
        "the try sits outside the loop, so the first failure skips the rest"
    assert "raise" not in loop
