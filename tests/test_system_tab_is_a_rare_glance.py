"""The system mail tab is checked about twice a day, not thirty times.

The first cut of this opened HE THONG once per SESSION -- and the farm starts
a new session every quarter of an hour, so that was thirty visits a day to a
mailbox nobody opens thirty times a day. The operator caught it straight away:
"lan nao cung mo de bi ban a". It was added while the account was already
under an anti-cheat warning, which makes it the worst possible moment to have
invented a new fixed rhythm.

A new letter still arrives with a red badge and the badge loop opens it. This
is only the safety net for a letter the operator has already read, which
leaves no badge at all.
"""

import json
import time

import pytest

pa = pytest.importorskip("anti_detection.player_actions")


@pytest.fixture
def state(tmp_path, monkeypatch):
    path = tmp_path / "mail_system_tab.json"
    monkeypatch.setattr(pa, "_system_tab_state_path", lambda: path)
    return path


def test_it_is_not_due_again_right_after_a_visit(state, monkeypatch):
    monkeypatch.setattr(pa.random, "random", lambda: 0.0)   # always willing
    pa._note_system_tab_opened()
    assert not pa._system_tab_due(), "a second look minutes later"


def test_after_the_gap_it_becomes_possible_again(state, monkeypatch):
    long_ago = time.time() - (pa.SYSTEM_TAB_MIN_GAP_H + 1) * 3600
    state.write_text(json.dumps({"last": long_ago}), encoding="utf-8")
    monkeypatch.setattr(pa.random, "random", lambda: 0.0)
    assert pa._system_tab_due()


def test_even_then_it_does_not_always_go(state, monkeypatch):
    """A gap alone would still be a clock -- the same hour every day."""
    state.write_text(json.dumps({"last": time.time() - 48 * 3600}),
                     encoding="utf-8")
    monkeypatch.setattr(pa.random, "random", lambda: 0.99)
    assert not pa._system_tab_due()


def test_no_state_file_means_it_may_look(state, monkeypatch):
    monkeypatch.setattr(pa.random, "random", lambda: 0.0)
    assert pa._system_tab_due()


def test_the_gap_is_long_enough_to_be_a_daily_habit():
    assert pa.SYSTEM_TAB_MIN_GAP_H >= 6, (
        "the farm opens the mailbox every session; a short gap here is the "
        "every-session behaviour again under another name"
    )
    assert pa.SYSTEM_TAB_CHANCE < 1.0, "always going makes the gap a schedule"


def test_a_new_letter_does_not_depend_on_this_path():
    """It arrives with a badge, and the badge loop clicks every badged tab."""
    import ast
    import inspect

    src = inspect.getsource(pa.act_mail)
    tree = ast.parse(src.lstrip())
    text = ast.unparse(tree)
    assert "badge_tabs" in text, "the badge-driven loop is gone"
