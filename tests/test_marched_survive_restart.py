"""The deposits our armies are on survive a restart of the farm.

The marched list lived only in the session, and 2026-09-23 had eight farm
restarts in two hours: after each one the farm was free to click -- and
march to -- a deposit an army was still on its way to. The site now rides
on the march's own record, which is saved and reloaded.
"""

import json
import time

from rok_farm import queue_ocr
from rok_farm.queue_ocr import GatherModelMixin


class Farm(GatherModelMixin):
    def __init__(self):
        self._marched_sites = []


def _write(tmp_path, monkeypatch, marches):
    p = tmp_path / "open_marches.json"
    p.write_text(json.dumps(marches), encoding="utf-8")
    monkeypatch.setattr(queue_ocr, "OPEN_MARCHES", p)


def test_a_restart_remembers_where_the_armies_went(tmp_path, monkeypatch):
    now = time.time()
    _write(tmp_path, monkeypatch, [
        {"t_sent": now - 300, "est_home": now + 1200, "site": ["4096", 632, 622]},
        {"t_sent": now - 200, "est_home": now + 900},              # no site
        {"t_sent": now - 9000, "est_home": now - 60, "site": ["4096", 1, 2]},
    ])
    f = Farm()
    f.load_open_marches()
    assert [(m, x, y) for m, x, y, _t in f._marched_sites] == [("4096", 632, 622)]


def test_home_armies_free_their_deposits(tmp_path, monkeypatch):
    now = time.time()
    _write(tmp_path, monkeypatch, [
        {"t_sent": now - 9000, "est_home": now - 1, "site": ["4096", 632, 622]}])
    f = Farm()
    f.load_open_marches()
    assert f._marched_sites == []
