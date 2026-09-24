"""The AP burn has an off switch.

2026-09-24, the operator: "them lua chon tat xa ap di" -- their second account
has no monthly pass, so the game's barbarian auto, the only way the farm
spends action points, is not there to press. The switch is a saved file
(!ap on|off, menu item 8, the app's checkbox) that a running farm reads at
every decision, plus --no-ap-burn for a run started by hand.
"""

import sys

from rok_farm import ap_burn, config
from rok_farm import session_control as sc
from rok_farm.phases import PhasesMixin


class Bar(PhasesMixin):
    """A runner that can only look at the screen and click."""

    def __init__(self):
        self.grabs = 0
        self.clicks = []

    def _grab(self):
        self.grabs += 1
        return None

    def _click_pct(self, *args, **kwargs):
        self.clicks.append(args)


def test_on_when_nothing_was_ever_saved():
    """What the main account has always done."""
    assert not ap_burn.AP_SWITCH.exists()
    assert ap_burn.enabled()


def test_off_and_back_on():
    ap_burn.set_enabled(False, "test")
    assert not ap_burn.enabled()
    on, at, by = ap_burn.switch_state()
    assert (on, by) == (False, "test") and at > 0
    ap_burn.set_enabled(True, "test")
    assert ap_burn.enabled()


def test_an_unreadable_switch_keeps_it_off():
    ap_burn.AP_SWITCH.parent.mkdir(parents=True, exist_ok=True)
    ap_burn.AP_SWITCH.write_text("{half a fi", encoding="utf-8")
    assert not ap_burn.enabled()


def test_the_command_line_flag_wins_over_the_saved_switch(monkeypatch):
    ap_burn.set_enabled(True, "test")
    monkeypatch.setattr(config, "AP_BURN_ENABLED", False)
    assert not ap_burn.enabled()


def test_no_ap_burn_reaches_the_config(monkeypatch):
    import run_farm

    class Runner:
        def __init__(self, **kwargs):
            pass

        def run(self):
            pass

    monkeypatch.setattr(config, "AP_BURN_ENABLED", True)
    monkeypatch.setattr(run_farm, "GemFarmRunner", Runner)
    monkeypatch.setattr(sys, "argv", ["run_farm.py", "--no-ap-burn"])
    run_farm.main()
    assert config.AP_BURN_ENABLED is False


def test_switched_on_the_bar_is_read():
    r = Bar()
    r._note_ap_bar()
    assert r.grabs == 1


def test_switched_off_the_bar_is_not_even_read():
    ap_burn.set_enabled(False, "test")
    r = Bar()
    r._ap_pending = True
    assert r._note_ap_bar() < 0
    assert r.grabs == 0 and r._ap_pending is False


def test_switched_off_after_the_reading_nothing_is_pressed():
    """The city read a full bar while it was on; !ap off came before a slot freed."""
    r = Bar()
    r._ap_pending = True
    ap_burn.set_enabled(False, "test")
    assert r._maybe_burn_ap() is False
    assert r.clicks == [] and r._ap_pending is False


def test_the_switch_from_the_phone(monkeypatch):
    monkeypatch.setattr(sc, "blog", lambda *a, **k: None)
    assert "OFF" in sc.do_ap_burn(False, "Discord (op)")
    assert not ap_burn.enabled()
    text = sc.ap_burn_text()
    assert "OFF" in text and "Discord (op)" in text
    sc.do_ap_burn(True, "Discord (op)")
    assert ap_burn.enabled() and "ON" in sc.ap_burn_text()


def test_every_surface_has_it():
    import tools.remote.discord_bot as bot
    from app import gui, menu

    assert "ap" in bot.KNOWN_CMDS
    assert "!ap on|off" in sc.HELP
    assert any(fn is menu.do_ap_burn for _, fn, _ in menu.ITEMS)
    assert hasattr(gui.App, "do_ap_toggle")
