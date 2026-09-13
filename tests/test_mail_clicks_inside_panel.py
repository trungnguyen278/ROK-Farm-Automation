"""The mail panel's own buttons sit inside the HUD's no-click zones.

Every tab and "Doc va nhan tat" click the mail check ever attempted -- 22 of
them, up to 2026-09-14 04:40 -- was dropped by the click layer as "in no-click
zone" and logged at DEBUG, right under an INFO line saying the mail had been
read. These tests pin the geometry that caused it and the gate that fixes it.
"""

import ast
import logging
from contextlib import contextmanager

import pytest

import anti_detection.player_actions as pa
import rok_farm.input_hid as hid
from rok_farm import PROJECT_ROOT
from rok_farm.input_hid import HidInputMixin

WIN = {"left": 952, "top": 190, "width": 1533, "height": 862}
TAB_LIEN_MINH = (0.402, 0.035)     # where act_mail clicks for the badge at 0.412
READ_ALL = (0.218, 0.943)          # where _find_mail_read_all found the button


class Pointer(HidInputMixin):
    def __init__(self):
        self.win = dict(WIN)


def screen(p, pct):
    return (p.win["left"] + int(p.win["width"] * pct[0]),
            p.win["top"] + int(p.win["height"] * pct[1]))


@pytest.fixture
def no_lucky_pass(monkeypatch):
    # _in_no_click_zone lets 5% of zone clicks through at random
    monkeypatch.setattr(hid.random, "random", lambda: 0.5)


@pytest.mark.parametrize("pct", [TAB_LIEN_MINH, READ_ALL], ids=["tab", "read_all"])
def test_the_panel_buttons_are_inside_the_hud_zones(pct, no_lucky_pass):
    p = Pointer()
    assert p._in_no_click_zone(*screen(p, pct)), \
        "no longer inside a zone -- the reason for the mail gate has changed"


@pytest.mark.parametrize("pct", [TAB_LIEN_MINH, READ_ALL], ids=["tab", "read_all"])
def test_the_pointer_scope_lets_them_through_and_restores(pct, no_lucky_pass):
    p = Pointer()
    with p._pointer_scope(p.win):
        assert not p._in_no_click_zone(*screen(p, pct))
    assert p._in_no_click_zone(*screen(p, pct)), "the zones did not come back"


class Ctx:
    """Stands in for the runner and records whether the zones were down."""

    def __init__(self, click_result=None):
        self.win = dict(WIN)
        self.zones_down = False
        self.clicks = []
        self.result = click_result

    @contextmanager
    def _pointer_scope(self, rect):
        self.zones_down = True
        try:
            yield
        finally:
            self.zones_down = False

    def _click_pct(self, px, py, jitter_px=10):
        self.clicks.append((px, py, self.zones_down))
        return self.result


def test_a_click_in_the_open_panel_goes_through_with_the_zones_down(monkeypatch):
    monkeypatch.setattr(pa, "_find_mail_read_all", lambda frame: READ_ALL)
    ctx = Ctx()
    assert pa._click_in_mail_panel(ctx, "frame", *READ_ALL)
    assert ctx.clicks == [(READ_ALL[0], READ_ALL[1], True)]
    assert ctx.zones_down is False


def test_no_click_without_proof_that_the_panel_is_open(monkeypatch, caplog):
    """If the panel did not open, the read-all spot is the chat box."""
    monkeypatch.setattr(pa, "_find_mail_read_all", lambda frame: None)
    ctx = Ctx()
    with caplog.at_level(logging.INFO, logger=pa.logger.name):
        assert not pa._click_in_mail_panel(ctx, "frame", *READ_ALL)
    assert ctx.clicks == []
    assert "not confirmed open" in caplog.text


def test_a_click_that_is_still_blocked_says_so(monkeypatch, caplog):
    monkeypatch.setattr(pa, "_find_mail_read_all", lambda frame: READ_ALL)
    ctx = Ctx(click_result=False)
    with caplog.at_level(logging.INFO, logger=pa.logger.name):
        assert not pa._click_in_mail_panel(ctx, "frame", *TAB_LIEN_MINH)
    assert "was blocked" in caplog.text


def test_click_pct_reports_whether_the_click_happened():
    p = Pointer()
    p._click = lambda sx, sy, hold_ms=0: False
    assert p._click_pct(0.5, 0.5) is False
    p._click = lambda sx, sy, hold_ms=0: True
    assert p._click_pct(0.5, 0.5) is True


def test_act_mail_clicks_nothing_in_the_panel_past_the_gate():
    """Only the button that opens the panel and the ones that close it may go
    straight to _click_pct; everything inside goes through the gate."""
    src = (PROJECT_ROOT / "anti_detection" / "player_actions.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "act_mail")
    code = ast.unparse(fn)
    assert code.count("_click_pct(") == 1, "a panel click bypasses the gate"
    assert "_click_pct(*BTN_POS['mail'])" in code
    assert code.count("_click_in_mail_panel(") == 2
