"""!stop should say what the run produced, not just that it stopped.

Read back out of the farm log rather than from memory: the process that knew
is the one being killed, and a controller can be started at any time and still
summarise a run it did not launch.
"""

import pytest

import rok_farm.session_control as sc


@pytest.fixture
def logdir(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "LOGDIR", tmp_path)
    return tmp_path


def write(logdir, body):
    (logdir / "farm_run.log").write_text(body, encoding="utf-8")


RUN = """=== farm start 2026-09-11 10:12:36
2026-09-11 10:12:40,000 [INFO   ] gem_farm_test: Gem counter starts at 62710
2026-09-11 10:12:40,001 [INFO   ] gem_farm_test: Gems now 62710 (+0 since start)
  Mine 1 DONE
2026-09-11 10:40:00,000 [INFO   ] gem_farm_test: Gems now 62839 (+129 since start)
  Mine 2 DONE
  Mine 3 FAILED
2026-09-11 11:12:36,000 [INFO   ] gem_farm_test: Queue reconcile: 5/5 full
"""


def test_it_reports_gems_duration_and_rate(logdir):
    write(logdir, RUN)
    out = " | ".join(sc.session_summary())
    # 10:12:40 -> 11:12:36 is four seconds short of the hour, and the duration
    # floors rather than rounds. Better a minute understated than overstated.
    assert "0h59m" in out
    assert "62,710 -> 62,839" in out and "+129" in out
    assert "/h" in out
    assert "2 done / 1 failed" in out


def test_only_the_current_run_is_counted(logdir):
    """The log is append-mode across restarts on purpose."""
    write(logdir, "=== farm start 2026-09-10 01:00:00\n"
                  "2026-09-10 01:00:00,000 [INFO   ] x: Gems now 1 (+0 since start)\n"
                  "  Mine 1 DONE\n  Mine 2 DONE\n  Mine 3 DONE\n" + RUN)
    out = " | ".join(sc.session_summary())
    assert "2 done" in out, "counted mines from an earlier run"
    assert "62,710" in out


def test_a_run_with_one_gem_reading_says_so(logdir):
    write(logdir, "=== farm start 2026-09-11 10:00:00\n"
                  "2026-09-11 10:00:00,000 [INFO   ] x: Gems now 500 (+0 since start)\n"
                  "2026-09-11 10:30:00,000 [INFO   ] x: nothing else\n")
    out = " | ".join(sc.session_summary())
    assert "only one reading" in out, out
    assert "/h" not in out, "a rate from one reading would be invented"


def test_a_run_too_short_to_have_a_rate(logdir):
    write(logdir, "=== farm start 2026-09-11 10:00:00\n"
                  "2026-09-11 10:00:00,000 [INFO   ] x: Gems now 500 (+0 since start)\n"
                  "2026-09-11 10:00:30,000 [INFO   ] x: Gems now 530 (+30 since start)\n")
    out = " | ".join(sc.session_summary())
    assert "+30" in out
    assert "/h" not in out, "30 seconds is not enough to quote an hourly rate"


def test_an_empty_or_missing_log_says_nothing(logdir):
    assert sc.session_summary() == []
    write(logdir, "")
    assert sc.session_summary() == []


def test_rejected_readings_cannot_skew_the_total(logdir):
    """Refused reads never appear as "Gems now", which is what makes this safe."""
    write(logdir, "=== farm start 2026-09-11 10:00:00\n"
                  "2026-09-11 10:00:00,000 [INFO   ] x: Gems now 62710 (+0 since start)\n"
                  "2026-09-11 10:10:00,000 [WARNING] x: Ignoring gem reading 550 "
                  "(last was 62710) -- too big a jump to be real\n"
                  "2026-09-11 11:00:00,000 [INFO   ] x: Gems now 62900 (+190 since start)\n")
    out = " | ".join(sc.session_summary())
    assert "62,710 -> 62,900" in out and "+190" in out, out
    assert "550" not in out
