"""The watchdog must not be the thing that dies.

2026-09-13, 03:30: a NameError in the hourly summary -- introduced by a
refactor of this very file -- killed the watchdog process outright. The farm
then ran unsupervised until morning. The health monitor noticed; the code
could not. A supervisor that exits on its own bug is worse than no supervisor,
because everyone believes something is watching.

Checked on the parse tree, not on the text: the point is the SHAPE of the
loop, and a string search would pass on a comment that says the right thing.
"""

import ast

from rok_farm import PROJECT_ROOT

SRC = (PROJECT_ROOT / "tools" / "dev" / "overnight" / "watchdog2.py").read_text(
    encoding="utf-8")
TREE = ast.parse(SRC)


def poll_loop():
    for node in TREE.body:
        if isinstance(node, ast.While) and isinstance(node.test, ast.Constant) \
                and node.test.value is True:
            return node
    raise AssertionError("the module-level `while True:` poll loop is gone")


def names_in(node):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def test_the_poll_body_is_guarded():
    loop = poll_loop()
    tries = [n for n in loop.body if isinstance(n, ast.Try)]
    assert tries, ("nothing in the poll loop is wrapped in try/except, so any "
                   "exception anywhere in it kills the supervisor")


def test_the_handler_continues_instead_of_dying():
    loop = poll_loop()
    guard = [n for n in loop.body if isinstance(n, ast.Try)][-1]
    assert guard.handlers, "the guard has no except clause"
    for h in guard.handlers:
        body = list(ast.walk(ast.Module(body=h.body, type_ignores=[])))
        assert any(isinstance(n, ast.Continue) for n in body), \
            "the handler does not continue, so the loop still ends"
        assert not any(isinstance(n, ast.Raise) for n in body), \
            "the handler re-raises, which kills the supervisor anyway"
        assert not any(isinstance(n, ast.Break) for n in body), \
            "the handler breaks out of the poll loop, which kills the supervisor"


def test_it_catches_everything_not_just_the_expected():
    """The 03:30 death was a NameError -- nobody would have listed it."""
    loop = poll_loop()
    guard = [n for n in loop.body if isinstance(n, ast.Try)][-1]
    caught = {getattr(h.type, "id", None) for h in guard.handlers}
    assert caught <= {"Exception", "BaseException", None}, \
        f"the guard only catches {caught}; the bug that killed it was a NameError"


def test_the_two_answers_that_must_survive_stay_outside_the_guard():
    """A degraded poll may still not notice the farm is dead or the deadline
    has passed. Those two checks run before anything that can throw."""
    loop = poll_loop()
    before = []
    for n in loop.body:
        if isinstance(n, ast.Try):
            break
        before.append(n)
    used = set()
    for n in before:
        used |= names_in(n)
    assert "farm_alive" in used, \
        "the 'has the farm exited' check is inside the guard, so a persistent " \
        "poll error would hide a dead farm for ever"
    assert "DEADLINE" in used, "the deadline check moved inside the guard"


def test_the_error_count_is_reported_not_swallowed():
    """Silently continuing forever is its own kind of blind."""
    loop = poll_loop()
    guard = [n for n in loop.body if isinstance(n, ast.Try)][-1]
    logged = False
    for h in guard.handlers:
        for n in ast.walk(ast.Module(body=h.body, type_ignores=[])):
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "log":
                logged = True
    assert logged, "the handler swallows the exception without saying so"
    assert "poll_errors" in names_in(guard), \
        "nothing counts how often the poll is failing"


def test_the_consecutive_failure_scan_still_breaks_its_own_for():
    """The one `break` in there that does NOT mean "stop supervising".

    It walks backwards through the run's mine results and stops at the first
    DONE. Re-indenting the loop body must not have changed which loop it
    leaves.
    """
    loop = poll_loop()
    fors = [n for n in ast.walk(loop) if isinstance(n, ast.For)]
    assert fors, "the consecutive-failure scan is gone"
    counted = [f for f in fors if "consec" in names_in(f)]
    assert counted, "no loop counts `consec` any more"
    for f in counted:
        assert any(isinstance(n, ast.Break) for n in ast.walk(f)), \
            "the backwards scan no longer stops at the first DONE, so it " \
            "counts failures from anywhere in the run"
