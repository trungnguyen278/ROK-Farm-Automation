"""!days: the farm day by day, one chart a metric, days along the bottom.

Asked for 2026-09-29: "one column the day, one the value to compare" --
how many gems yesterday, and the same numbers for the days before.
"""

import io
import time

import pytest
from PIL import Image

from rok_farm import charts, reports

# Two run days with a gap between them. Console lines ("Mine 1 DONE") carry
# no timestamp of their own.
LOG = """\
2026-09-26 09:00:00,000 [INFO   ] gem_farm_test: Gem counter starts at 1000
2026-09-26 09:05:00,000 [INFO   ] gem_farm_test: Marched to deposit 580:620
  Mine 1 DONE (total: 1)
2026-09-26 09:20:00,000 [INFO   ] gem_farm_test: Gems now 1020 (+20 since start)
2026-09-26 09:30:00,000 [INFO   ] gem_farm_test: Marched to deposit 590:600
  Mine 2 DONE (total: 2)
2026-09-26 09:40:00,000 [INFO   ] gem_farm_test: Gems now 1035 (+35 since start)
2026-09-26 09:45:00,000 [WARNING] gem_farm_test: Game restart: waiting 8min for troops
2026-09-26 23:59:00,000 [INFO   ] gem_farm_test: AP burn started: dwell 900s then quit for 300s
  Mine 3 FAILED
2026-09-28 10:00:00,000 [INFO   ] gem_farm_test: Gem counter starts at 2000
2026-09-28 10:10:00,000 [INFO   ] gem_farm_test: Marched to deposit 570:610
  Mine 1 DONE (total: 1)
2026-09-28 10:30:00,000 [INFO   ] gem_farm_test: Gems now 2018 (+18 since start)
"""

NOW = time.mktime(time.strptime("2026-09-29 11:00", "%Y-%m-%d %H:%M"))


@pytest.fixture
def log(tmp_path):
    p = tmp_path / "farm_run.log"
    p.write_text(LOG, encoding="utf-8")
    return p


def rows_of(log, days=4):
    return {r.day: r for r in reports.daily_stats(days, now=NOW, log=log)}


def test_a_row_for_every_day_even_without_a_run(log):
    rows = reports.daily_stats(4, now=NOW, log=log)
    assert [r.day for r in rows] == ["2026-09-26", "2026-09-27",
                                     "2026-09-28", "2026-09-29"]
    assert [r.ran for r in rows] == [True, False, True, False]


def test_counts_per_day(log):
    d = rows_of(log)["2026-09-26"]
    assert (d.marches, d.done, d.failed, d.ap, d.restarts) == (2, 2, 1, 1, 1)
    assert d.gems == 35 and d.hours == pytest.approx(40 / 60)
    assert rows_of(log)["2026-09-28"].gems == 18


def test_a_console_line_takes_the_day_of_the_line_above_it(log):
    """"Mine 3 FAILED" follows a 23:59 line: it is the 26th's, not the 27th's."""
    assert rows_of(log)["2026-09-26"].failed == 1
    assert rows_of(log)["2026-09-27"].failed == 0


@pytest.mark.parametrize("args,want", [
    ([], (None, 14)),
    (["gems"], ("gems", 14)),
    (["30"], (None, 30)),
    (["gems", "30d"], ("gems", 30)),
    (["7", "marches"], ("marches", 7)),
    (["quits"], ("restarts", 14)),
    (["999"], (None, reports.DAYS_MAX)),
    (["1"], (None, 2)),
    (["bogus"], (None, 14)),
])
def test_what_the_operator_types(args, want):
    assert reports.parse_days(args) == want


def png_size(png):
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return Image.open(io.BytesIO(png)).size


def test_the_overview_is_one_embed_a_metric_then_the_table(log):
    out = reports.days_report(None, 4, now=NOW, log=log)
    assert len(out) == len(reports.DAYS_OVERVIEW) + 1
    images = [spec["image"] for spec, _png in out[:-1]]
    assert len(set(images)) == len(images), "two pictures with one name"
    for spec, png in out[:-1]:
        assert png_size(png)[0] == 1000
    table, png = out[-1]
    assert png is None and "28/09" in table["description"]
    assert table["footer"], "the last embed carries the footnote"


def test_one_metric_lists_every_day_newest_first(log):
    (spec, png), = reports.days_report("gems", 4, now=NOW, log=log)
    text = spec["description"]
    text = text[text.index("```"):]                 # the table, not the headline
    order = [text.index(d) for d in ("29/09", "28/09", "27/09", "26/09")]
    assert order == sorted(order), "newest first"
    assert png_size(png) == (1000, 440)


def test_the_headline_compares_the_last_finished_day(log):
    head = reports._headline(reports.daily_stats(4, now=NOW, log=log), "gems",
                             open_today=True)
    assert head.startswith("**18** on Mon 28/09")
    assert "-17 vs 26/09" in head


def test_mines_compare_what_worked_not_attempts(log):
    head = reports._headline(reports.daily_stats(4, now=NOW, log=log), "mines",
                             open_today=True)
    assert "1 done / 0 failed (100%)" in head and "-1 done vs 26/09" in head


def test_sixty_days_still_fit_a_message(log):
    """Discord: 6,000 characters across a message's embeds."""
    out = reports.days_report(None, reports.DAYS_MAX, now=NOW, log=log)
    chars = sum(len(s["title"]) + len(s["description"]) + len(s.get("footer") or "")
                for s, _png in out)
    assert chars < 6000


def test_the_march_cap_is_the_practice():
    """80 a day since 2026-09-28 (docs/PLAN.md); the chart draws it."""
    assert reports.DAILY_MARCH_CAP == 80


# --- the chart kit ----------------------------------------------------------

@pytest.mark.parametrize("top,want", [
    (87, [0, 25, 50, 75, 100]),
    (2633, [0, 1000, 2000, 3000]),
    (0, [0, 1]),
    (7.2, [0, 2, 4, 6, 8]),
])
def test_ticks_are_round_numbers(top, want):
    assert charts.nice_ticks(top) == want


@pytest.mark.parametrize("v,want", [(0, "0"), (2500, "2,500"),
                                    (12500, "12.5K"), (20000, "20K"),
                                    (2.5, "2.5")])
def test_tick_labels(v, want):
    assert charts.fmt_tick(v) == want


def test_a_chart_with_no_values_still_draws():
    png = charts.column_chart(["a", "b"], [[None, None]], title="empty")
    assert png_size(png) == (1000, 440)


def test_a_stacked_chart_with_a_cap_line_draws():
    png = charts.column_chart(["a", "b", "c"], [[5, None, 3], [1, None, 0]],
                              names=("done", "failed"), partial={2},
                              label_at={0}, ref=(4, "cap 4", charts.WARNING))
    assert png_size(png) == (1000, 440)
