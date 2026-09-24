"""Shared test fixtures."""

import sys

import pytest


@pytest.fixture(autouse=True)
def _bot_log_stays_out_of_the_real_one(tmp_path, monkeypatch):
    """Tests must not write the live Discord bot's log.

    Importing tools.remote.discord_bot points session_control's notes at the
    bot's log file, so every later test that calls do_start with fake
    processes wrote "Farm started (pid 1234)" into logs/overnight/
    discord_bot.log -- nine times on 2026-09-24 alone, between real lines.
    """
    bot = sys.modules.get("tools.remote.discord_bot")
    if bot is not None:
        monkeypatch.setattr(bot, "LOGDIR", tmp_path)
        monkeypatch.setattr(bot, "BOT_LOG", tmp_path / "discord_bot.log")


@pytest.fixture(autouse=True)
def _map_books_stay_out_of_the_real_ones(tmp_path, monkeypatch):
    """Tests must not write data/map_knowledge.

    A book a test opened without pointing MEM_DIR elsewhere was saved beside
    the farm's (testmap.json, 2026-09-23 15:33) -- and the book written last
    is the one reports.active_book(), and so the Discord !map, draws.
    """
    import rok_farm.map_memory as mm
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path / "map_knowledge")
