"""A drag ends where it was aimed and never carries the pointer out of the game.

The farm drives the pointer with relative moves (MOVETO misbehaves with the
game on a second monitor), and relative moves go through Windows' pointer
ballistics: a faster step travels further than a slow one of the same count.
One calibrated scale cannot hold at every speed, and the drag used to add up
its steps open-loop. tools/dev/pan_survey.py measured it on 2026-09-23: real
drags came out 0.76-1.77x the aimed length, and 3 of 40 carried the pointer
out of the window -- two scan-speed swipes aimed at ~950px travelled 1,650.

Here the pointer is simulated with that kind of error: every step overshoots
by half again, the way an accelerated fast step does.
"""

import random

import pytest

from rok_farm import input_hid
from rok_farm.capture_svc import CaptureMixin
from rok_farm.input_hid import HidInputMixin

WIN = {"left": 513, "top": 306, "width": 1534, "height": 863}


class Pointer:
    """The OS cursor behind relative HID moves, with ballistics."""

    def __init__(self, x, y, gain=1.5):
        self.x, self.y = x, y
        self.gain = gain
        self.trail = []

    def move(self, dx, dy):
        self.x += int(round(dx * self.gain))
        self.y += int(round(dy * self.gain))
        self.trail.append((self.x, self.y))


class Cmd:
    def __init__(self, ptr, scale):
        self.ptr = ptr
        self.scale = scale
        self.down = False
        self.sent = []

    def send(self, name, *args, **kw):
        self.sent.append(name)
        if name == "MDOWN":
            self.down = True
        elif name == "MUP":
            self.down = False
        elif name == "MOVE":
            # the board moves the pointer by count * the OS's per-count scale
            self.ptr.move(args[0] * self.scale, args[1] * self.scale)
        return True


class Humanizer:
    def humanize_move(self, x1, y1, x2, y2):
        n = 24
        return [(int(x1 + (x2 - x1) * i / n), int(y1 + (y2 - y1) * i / n), 10)
                for i in range(1, n + 1)]


class Rig(HidInputMixin, CaptureMixin):
    def __init__(self, ptr, scale=1.57):
        self.win = dict(WIN)
        self._has_moveto = False
        self._mouse_scale = scale
        self._mm_speed = 0
        self.cmd = Cmd(ptr, scale)
        self.humanizer = Humanizer()

    def _moveto(self, sx, sy):
        self.cmd.ptr.x, self.cmd.ptr.y = sx, sy
        return True


@pytest.fixture
def rig(monkeypatch):
    ptr = Pointer(0, 0)
    monkeypatch.setattr(input_hid, "get_cursor_pos", lambda: (ptr.x, ptr.y))
    monkeypatch.setattr(input_hid.time, "sleep", lambda s: None)
    return Rig(ptr)


def _inside(x, y):
    return (WIN["left"] <= x <= WIN["left"] + WIN["width"]
            and WIN["top"] <= y <= WIN["top"] + WIN["height"])


def test_an_accelerated_drag_still_ends_on_its_aim(rig):
    sx, sy = WIN["left"] + 1150, WIN["top"] + 430
    ex, ey = WIN["left"] + 384, WIN["top"] + 430
    rig._human_drag(sx, sy, ex, ey, speed_factor=5.0)
    p = rig.cmd.ptr
    assert abs(p.x - ex) <= 4 and abs(p.y - ey) <= 4, (p.x, p.y)


def test_the_pointer_never_leaves_the_window(rig):
    rng = random.Random(4)
    for _ in range(30):
        sx = WIN["left"] + rng.randint(200, 1334)
        ex = WIN["left"] + rng.randint(200, 1334)
        y = WIN["top"] + rng.randint(200, 660)
        rig.cmd.ptr.trail.clear()
        rig._human_drag(sx, y, ex, y, speed_factor=rng.uniform(3.6, 7.0))
        for x, yy in rig.cmd.ptr.trail:
            assert _inside(x, yy), (sx, ex, x, yy)


def test_a_hold_keeps_the_button_down_and_the_pointer_still(rig):
    sx, sy = WIN["left"] + 1150, WIN["top"] + 430
    ex, ey = WIN["left"] + 384, WIN["top"] + 430
    rig._human_drag(sx, sy, ex, ey, hold_ms=400)
    assert rig.cmd.sent[0] == "MDOWN" and rig.cmd.sent[-1] == "MUP"
    p = rig.cmd.ptr
    assert abs(p.x - ex) <= 4 and abs(p.y - ey) <= 4


def test_without_the_feedback_it_would_have_overshot(rig, monkeypatch):
    """The rig is honest: blind to the real position, the same drag lands
    far past its aim -- which is what the survey saw."""
    monkeypatch.setattr(input_hid, "get_cursor_pos",
                        lambda: (_ for _ in ()).throw(OSError("blind")))
    sx, sy = WIN["left"] + 1150, WIN["top"] + 430
    ex, ey = WIN["left"] + 700, WIN["top"] + 430
    rig._human_drag(sx, sy, ex, ey)
    assert abs(rig.cmd.ptr.x - ex) > 100
