"""The mail panel's own buttons sit inside the HUD's no-click zones.

Every tab and "Doc va nhan tat" click the mail check ever attempted -- 22 of
them, up to 2026-09-14 04:40 -- was dropped by the click layer as "in no-click
zone" and logged at DEBUG, right under an INFO line saying the mail had been
read. These tests pin the geometry that caused it and the gate that fixes it.

The first gate trusted the read-all button alone and was measured unsafe the
same hour: 627 of 812 saved frames with no panel passed it. The frames below
are the ones that fooled it worst.
"""

import ast
import logging
from contextlib import contextmanager

import cv2
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


KEEP = PROJECT_ROOT / "screenshots" / "keep"
PANEL_FRAMES = [
    KEEP / "feature_refs" / "MAIL_NO_TAB_BADGES_130505.png",
    KEEP / "feature_refs" / "MAIL_NO_TAB_BADGES_180640.png",
    KEEP / "mail_read" / "MAIL_AFTER_READ_044022.png",
    KEEP / "mail_read" / "MAIL_AFTER_READ_053337.png",
]
NOT_PANEL = [
    # the read-all template's highest scores on frames WITHOUT the panel
    KEEP / "gate_negatives" / "m4_scan_14_014903.png",        # 0.709
    KEEP / "gate_negatives" / "m1_after_gather_032436.png",   # 0.700
    KEEP / "gate_negatives" / "m2_scan_00_022544.png",        # 0.698
    # dimmed behind a different panel
    KEEP / "harvest_panel" / "road_panel_after_harvest_015217.png",
    # the plain city, chat box and all
    KEEP / "operator_samples" / "day" / "city_idle_return_city_190516.png",
]


def load(path):
    if not path.is_file():
        pytest.skip(f"{path.name} is not kept any more")
    frame = cv2.imread(str(path))
    if frame is None:
        pytest.skip(f"{path.name} did not decode")
    return frame


@pytest.mark.parametrize("path", PANEL_FRAMES, ids=lambda p: p.stem)
def test_the_mail_panel_is_recognised(path):
    assert pa._mail_panel_open(load(path))


@pytest.mark.parametrize("path", NOT_PANEL, ids=lambda p: p.stem)
def test_nothing_else_is_taken_for_the_mail_panel(path):
    assert not pa._mail_panel_open(load(path))


def test_a_click_in_the_open_panel_goes_through_with_the_zones_down(monkeypatch):
    monkeypatch.setattr(pa, "_mail_panel_open", lambda frame: True)
    ctx = Ctx()
    assert pa._click_in_mail_panel(ctx, "frame", *READ_ALL)
    assert ctx.clicks == [(READ_ALL[0], READ_ALL[1], True)]
    assert ctx.zones_down is False


def test_no_click_without_proof_that_the_panel_is_open(monkeypatch, caplog):
    """If the panel did not open, the read-all spot is the chat box."""
    monkeypatch.setattr(pa, "_mail_panel_open", lambda frame: False)
    ctx = Ctx()
    with caplog.at_level(logging.INFO, logger=pa.logger.name):
        assert not pa._click_in_mail_panel(ctx, "frame", *READ_ALL)
    assert ctx.clicks == []
    assert "not confirmed open" in caplog.text


def test_a_click_that_is_still_blocked_says_so(monkeypatch, caplog):
    monkeypatch.setattr(pa, "_mail_panel_open", lambda frame: True)
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
    # tab switch and read-all. The system tab's own click lives in
    # _open_system_tab, checked below, because it is a rare glance rather than
    # part of every mail visit.
    assert code.count("_click_in_mail_panel(") == 2


def test_the_system_tab_click_also_goes_through_the_gate():
    """It is a click inside the panel like any other, just a rarer one."""
    src = (PROJECT_ROOT / "anti_detection" / "player_actions.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next((n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name == "_open_system_tab"), None)
    assert fn is not None, "the system tab is never opened any more"
    code = ast.unparse(fn)
    assert "_click_in_mail_panel(" in code
    assert "_click_pct(" not in code, "a panel click bypasses the gate"


# --- Closing the panel -----------------------------------------------------
#
# The X search accepted anything template-shaped scoring over 0.60 anywhere in
# the top 15% of the frame. Live 2026-09-21 16:01:06 it clicked pct(0.352,
# 0.115) -- the gift icon on the first message row, which the template matches
# at 0.866 once shrunk to scale 0.4. The no-click zone then dropped that click
# at DEBUG level, the panel stayed open, and only the client quit that followed
# cleared it.

class CloseCtx:
    """Just enough context for _close_mail."""

    def __init__(self, frame="a frame"):
        self.win = dict(WIN)
        self.frame = frame
        self.clicks = []
        self.waited = 0

    def _grab(self):
        return self.frame

    @contextmanager
    def _pointer_scope(self, rect):
        yield

    def _click_pct(self, px, py, jitter_px=0):
        self.clicks.append((px, py))
        return True

    def _wait(self, *a, **k):
        self.waited += 1


@pytest.fixture
def close_ctx(monkeypatch):
    monkeypatch.setattr(pa, "_mail_panel_open", lambda frame: True)
    dismissed = []
    monkeypatch.setattr(pa, "_dismiss_panel", lambda ctx: dismissed.append(ctx))
    return CloseCtx(), dismissed


def test_the_x_is_clicked_where_the_button_is(close_ctx, monkeypatch):
    ctx, dismissed = close_ctx
    at = pa.MAIL_X_AT
    monkeypatch.setattr(pa, "_match_on_frame",
                        lambda *a, **k: (at[0], at[1], 0.91, 56, 51))
    pa._close_mail(ctx)
    assert ctx.clicks == [at]
    assert not dismissed


def test_an_x_shaped_thing_elsewhere_is_not_clicked(close_ctx, monkeypatch):
    """The gift icon on the first message row, at scale 0.4, score 0.866."""
    ctx, dismissed = close_ctx
    monkeypatch.setattr(pa, "_match_on_frame",
                        lambda *a, **k: (0.352, 0.115, 0.866, 22, 20))
    pa._close_mail(ctx)
    assert ctx.clicks == [], "clicked a decoy inside the message list"
    assert dismissed, "no fallback when the X was not found"


def test_the_close_click_goes_through_the_panel_path(close_ctx, monkeypatch):
    """Not ctx._click_pct directly -- the zones have to be dropped, and a
    click that is blocked anyway has to say so."""
    ctx, dismissed = close_ctx
    at = pa.MAIL_X_AT
    monkeypatch.setattr(pa, "_match_on_frame",
                        lambda *a, **k: (at[0], at[1], 0.91, 56, 51))
    monkeypatch.setattr(pa, "_mail_panel_open", lambda frame: False)
    pa._close_mail(ctx)
    assert ctx.clicks == [], "clicked without the panel confirmed open"
    assert dismissed


def test_the_x_sits_where_the_saved_panels_put_it():
    """Every saved mail-panel frame agrees to four decimal places."""
    frames = sorted((PROJECT_ROOT / "screenshots").glob("**/MAIL_AFTER_READ_*.png"))
    frames += sorted((PROJECT_ROOT / "screenshots").glob("**/MAIL_NO_TAB_BADGES_*.png"))
    seen = []
    for f in frames:
        im = cv2.imread(str(f))
        if im is None:
            continue
        m = pa._match_on_frame(im, "ui/btn_x_close_mail", threshold=0.60,
                               roi=(0.0, 0.15),
                               scales=[0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
        if m:
            seen.append((m[0], m[1]))
    if not seen:
        pytest.skip("no mail panel frames are kept any more")
    for x, y in seen:
        assert abs(x - pa.MAIL_X_AT[0]) <= pa.MAIL_X_TOL, (x, y)
        assert abs(y - pa.MAIL_X_AT[1]) <= pa.MAIL_X_TOL, (x, y)
