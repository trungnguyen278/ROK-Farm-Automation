"""IDLE 1 means quiet. IDLE 0 means keep nudging.

The operator found this from outside the code on 2026-09-22: with the ESP32
plugged in the screen never turns off after locking, and unplugged it does.
Windows' idle clock never rose above 0.7s across two minutes of an untouched
machine, so the display timeout could never run down.

The firmware is the authority on what the argument means:

    handle_idle:  idle_suppressed = (atoi(params[0]) == 1);
    idle_noise:   if (executing || idle_suppressed) return;

so 1 suppresses and 0 releases, and released means Mouse.move(+-1) every
500-3000ms for as long as the board has power. session_control's shutdown was
sending 0 while printing "HID: idle jitter OFF", which is the opposite of both
its own message and the docstring at the top of that file.

These tests read the source rather than the board, because the board is not
present in CI -- and they read it with the AST, not with character windows
around a match, so a comment mentioning IDLE cannot pass or fail them.
"""

import ast
import inspect
import re
from pathlib import Path

import pytest

from rok_farm import PROJECT_ROOT, phases, session_control

FIRMWARE = PROJECT_ROOT / "esp32-s3" / "src" / "main.cpp"


def idle_args(func):
    """Every literal argument passed to a .send("IDLE", ...) in this function."""
    tree = ast.parse(inspect.getsource(func).lstrip())
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "send":
            continue
        args = [a.value for a in node.args if isinstance(a, ast.Constant)]
        if args and args[0] == "IDLE":
            out.extend(args[1:])
    return out


def test_the_firmware_still_reads_one_as_suppressed():
    """If this ever flips, every call site below is wrong at once."""
    if not FIRMWARE.exists():
        pytest.skip("firmware source is not in this checkout")
    src = FIRMWARE.read_text(encoding="utf-8", errors="replace")
    assert re.search(r"idle_suppressed\s*=\s*\(\s*atoi\(cmd\.params\[0\]\)\s*==\s*1\s*\)",
                     src), "handle_idle no longer maps 1 to suppressed"
    assert re.search(r"if\s*\(\s*executing\s*\|\|\s*idle_suppressed\s*\)\s*return",
                     src), "idle_noise no longer honours idle_suppressed"


def test_the_board_nudges_the_pointer_while_it_is_not_suppressed():
    """What is at stake: this is a real mouse report, not a no-op."""
    if not FIRMWARE.exists():
        pytest.skip("firmware source is not in this checkout")
    src = FIRMWARE.read_text(encoding="utf-8", errors="replace")
    body = src[src.index("void idle_noise()"):]
    body = body[:body.index("\n}")]
    assert "Mouse.move" in body
    assert "random(500, 3000)" in body, body


def test_stopping_the_farm_leaves_the_board_quiet():
    """The whole point of releasing the board. It was sending "0"."""
    assert idle_args(session_control.shutdown_board) == ["1"], (
        "stopping the farm must SUPPRESS the jitter; sending 0 releases it "
        "and the pointer twitches until the board is unplugged")


def test_tabbing_out_of_the_game_goes_quiet():
    assert idle_args(phases.PhasesMixin._tab_out) == ["1"]


def test_tabbing_back_in_lets_it_nudge_again():
    """Deliberate: while the farm is playing, a pointer that never moves at
    all is its own tell."""
    assert idle_args(phases.PhasesMixin._tab_back) == ["0"]
