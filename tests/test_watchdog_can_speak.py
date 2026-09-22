"""The watchdog had no way to tell anyone anything.

2026-09-22: the game went into maintenance and the farm failed mine after
mine for an hour. The operator asked why the watchdog said nothing. It had
nothing to say it WITH -- it wrote only to logs/overnight/watchdog.log, which
nothing tails, so every judgement it had ever made was invisible unless
someone opened the file.

And it would not have judged anyway. CONSEC_FAIL_LIMIT was 14, and measured
over the whole farm log -- 294 consecutive-failure runs -- only 5 ever reached
14. The limit sat near the 98th percentile of failure runs, so it almost never
fired.
"""

import ast
import inspect
import re
from pathlib import Path

from rok_farm import PROJECT_ROOT

WD = (PROJECT_ROOT / "tools" / "dev" / "overnight" / "watchdog2.py").read_text(
    encoding="utf-8")
BOT = (PROJECT_ROOT / "tools" / "remote" / "discord_bot.py").read_text(
    encoding="utf-8")


def const(src, name):
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is gone")


def test_the_failure_limit_is_one_that_can_actually_fire():
    """18 was the longest run ever seen and 14 was reached 5 times in 294.
    Eight was reached ten times -- rare, but it exists."""
    limit = const(WD, "CONSEC_FAIL_LIMIT")
    assert limit <= 10, f"{limit} sits in the tail again and will not fire"
    assert limit >= 5, f"{limit} will fire on ordinary fog and wrong-place runs"


def test_the_watchdog_has_a_way_to_speak():
    assert "def alert(" in WD, "the watchdog can only write to its own file again"
    tree = ast.parse(WD)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "alert")
    body = ast.dump(fn)
    assert "FARM_LOG" in body, (
        "alert() does not write where the bot is reading, so it still reaches "
        "nobody")


def test_what_it_says_gets_past_the_bot_filter():
    """Both halves have to agree or the alert is written and dropped."""
    m = re.search(r"FEED = re\.compile\((.*?)\n\)", BOT, re.S)
    assert m, "the bot's feed filter moved"
    assert "WATCHDOG:" in m.group(1), (
        "the bot drops WATCHDOG lines, so alert() writes into a void")

    # and the line alert() writes must not look like a logger line, which the
    # bot skips before it ever reaches the filter
    logpfx = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ \[\w+\s*\] [\w.]+: ")
    sample = "  [WARN] WATCHDOG: 8 consecutive mine failures"
    assert not logpfx.match(sample), "alert()'s line would be skipped as log noise"
    feed = re.compile(m.group(1).replace('r"', '"').replace('"', ''), re.X)
    assert feed.search(sample), sample


def test_the_judgements_actually_use_it():
    """An alert path nothing calls is the same as no alert path."""
    tree = ast.parse(WD)
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "alert" in called, "alert() is defined and never called"
    assert WD.count("alert(") >= 3, (
        "only the definition and one call; the failures and the stuck clock "
        "should both speak")
