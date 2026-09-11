"""A near-miss command should point at the right one -- and never run it.

These get typed from a phone. "!statud" cost a round trip for nothing, and a
bare "unknown command" does not help when the keyboard is the problem.

The suggestion must stay a suggestion: "!stpo" is one letter from "!stop", and
acting on a guess would stop a farm the operator meant to leave running.
"""

import difflib

import pytest

bot = pytest.importorskip("tools.remote.discord_bot",
                          reason="discord.py not installed")


def suggest(cmd):
    near = difflib.get_close_matches(cmd, bot.SUGGESTABLE, n=1, cutoff=0.6)
    return near[0] if near else None


def test_the_typo_that_prompted_this():
    assert suggest("statud") == "status"


@pytest.mark.parametrize("typo,want", [
    ("repot", "report"),
    ("sthot", "shot"),
    ("chek", "check"),
    ("statud", "status"),
])
def test_common_slips_resolve(typo, want):
    assert suggest(typo) == want


@pytest.mark.parametrize("typo", ["shto", "sotp", "stpo", "strat", "sart"])
def test_a_slip_is_never_pointed_at_start_or_stop(typo):
    """The whole reason SUGGESTABLE exists.

    "shto" scores 0.75 against both "shot" and "stop"; the tie breaks on list
    order. An operator who follows a wrong hint stops the farm and closes the
    game when they wanted a screenshot, so these have to be typed in full.
    """
    assert suggest(typo) not in ("start", "stop")


def test_nonsense_suggests_nothing():
    """Better to fall back to !help than to point somewhere random."""
    assert suggest("xyzzy") is None
    assert suggest("") is None


def test_every_real_command_is_listed():
    """KNOWN_CMDS is a second copy of the handler's verbs; keep it honest."""
    import re
    from pathlib import Path
    src = Path(bot.__file__).read_text(encoding="utf-8")
    body = src[src.index("if cmd in (\"help\""):src.index("unknown command")]
    handled = set()
    for m in re.finditer(r'cmd (?:==|in) \(?([^):\n]+)\)?:', body):
        handled |= {w.strip().strip('"\'') for w in m.group(1).split(",")
                    if w.strip().strip('"\'')}
    missing = handled - set(bot.KNOWN_CMDS)
    assert not missing, f"handled but not known: {sorted(missing)}"
    assert set(bot.SUGGESTABLE) <= set(bot.KNOWN_CMDS)
    assert "stop" not in bot.SUGGESTABLE and "start" not in bot.SUGGESTABLE
