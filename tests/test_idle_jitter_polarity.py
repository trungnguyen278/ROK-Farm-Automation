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


def test_the_board_starts_quiet_and_stays_quiet_through_a_reset():
    """The case the operator actually hit: farm not running at all, only the
    ESP32 plugged in, and the screen would not sleep after locking.

    Nothing was sending commands then, so no amount of Python could have
    stopped it -- suppressing at the farm's bring-up only covers a board the
    farm has spoken to. Only the firmware's own default reaches a board that
    was merely plugged in.
    """
    if not FIRMWARE.exists():
        pytest.skip("firmware source is not in this checkout")
    src = FIRMWARE.read_text(encoding="utf-8", errors="replace")
    assert re.search(r"static\s+bool\s+idle_suppressed\s*=\s*true\s*;", src), (
        "the board boots nudging again; a plugged-in ESP32 with nothing "
        "running will hold the screen awake")
    reset = src[src.index("void handle_reset("):]
    reset = reset.split("send_ack")[0]
    assert "idle_suppressed = true" in reset, (
        "RESET hands the board back to idle_noise(): " + reset)


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


def test_tabbing_back_in_stays_quiet_too():
    """This used to send 0 and let the board nudge for the whole time the
    client was in front, on the idea that a still pointer looks fake.

    Measured across 13 days of logs: about 137,000 micro moves against 9,559
    real clicks, fourteen phantom moves per real click, and the pointer never
    resting longer than three seconds while the client was up. Together with a
    click rhythm that never dipped under a second, that is two walls with
    nothing outside them, which is the shape being avoided.
    """
    assert idle_args(phases.PhasesMixin._tab_back) == ["1"]


def test_nothing_anywhere_releases_the_jitter():
    """No call site may send IDLE 0. The board's own boot default already
    starts it nudging; nothing in the farm should ask for more."""
    import rok_farm.runner
    seen = {}
    for mod in (phases, session_control, rok_farm.runner):
        src = Path(inspect.getfile(mod)).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "send":
                continue
            args = [a.value for a in node.args if isinstance(a, ast.Constant)]
            if len(args) >= 2 and args[0] == "IDLE":
                seen.setdefault(args[1], []).append(mod.__name__)
    assert "0" not in seen, "IDLE 0 released the jitter in %s" % seen.get("0")
    assert "1" in seen


def test_the_farm_quiets_the_board_as_soon_as_it_opens_the_port():
    """The firmware defaults to nudging, so a replug must not be able to leave
    it running. Suppressing at bring-up covers that without a reflash."""
    import rok_farm.runner
    src = Path(inspect.getfile(rok_farm.runner)).read_text(encoding="utf-8")
    tree = ast.parse(src)
    order = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "start":
                order.append(("start", node.lineno))
            args = [a.value for a in node.args if isinstance(a, ast.Constant)]
            if node.func.attr == "send" and args and args[0] == "IDLE":
                order.append(("idle", node.lineno))
    idles = [ln for kind, ln in order if kind == "idle"]
    starts = [ln for kind, ln in order if kind == "start"]
    assert idles, "runner never tells the board to be quiet"
    assert starts, "runner no longer starts a command buffer"
    assert min(idles) - min(starts) < 10, (
        "the quiet command is no longer right after the port opens: "
        "starts=%s idles=%s" % (starts, idles))
