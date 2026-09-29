"""What the Discord bot's answers look like: the state first, help in
groups, several embeds in one message, !days among the commands.

2026-09-29, the operator: the commands' look is not professional yet.
"""

import asyncio
import difflib

import pytest

bot = pytest.importorskip("tools.remote.discord_bot",
                          reason="discord.py not installed")

from rok_farm import session_control as sc  # noqa: E402


def test_days_is_a_command_and_a_typo_finds_it():
    assert "days" in bot.KNOWN_CMDS and "days" in bot.SUGGESTABLE
    assert difflib.get_close_matches("dyas", bot.SUGGESTABLE, n=1,
                                     cutoff=0.6) == ["days"]


def test_help_names_every_command():
    listed = " ".join(cmd for _g, items in sc.HELP_GROUPS for cmd, _w in items)
    aliases = {"help", "h", "s", "pic", "live", "wake"}
    for cmd in set(bot.KNOWN_CMDS) - aliases:
        assert f"!{cmd}" in listed, f"!{cmd} is not in !help"
    assert "!ap on|off" in sc.HELP, "the plain-text copy is built from the groups"


def test_help_is_an_embed_in_groups():
    emb = bot.help_embed()
    assert [f.name for f in emb.fields] == [g for g, _i in sc.HELP_GROUPS]
    assert all(len(f.value) <= 1024 for f in emb.fields)


LINES = [
    "2026-09-29 10:00:00,000 [INFO   ] gem_farm_test: Queue: 5/5",
    "  [INFO] Troops home in ~12.0min -- alt-tab out for 12.5min",
]


def test_a_planned_wait_is_the_state():
    how, left = bot.current_wait(LINES)
    assert how == "alt-tabbed out" and left == 0.0      # 10:00 is long gone


def test_a_mine_after_the_wait_ends_it():
    assert bot.current_wait(LINES + ["--- [m5] Step 1: Ensure world map ---"]) is None


def test_a_quit_uses_its_own_countdown():
    lines = ["2026-09-29 10:00:00,000 [INFO   ] gem_farm_test: x",
             "  [INFO] Troops home in ~20.0min -- quitting the client, back in ~21min",
             "  [INFO] Still out, 7 min to go"]
    assert bot.current_wait(lines) == ("client closed on purpose", 7.0)


def test_every_embed_is_stamped_unless_told_not_to():
    spec = {"title": "t", "description": "d", "fields": [], "image": None,
            "footer": None}
    assert bot.to_embed(spec).timestamp is not None
    assert bot.to_embed(spec).footer.text == "ROK Farm"
    assert bot.to_embed(spec, stamp=False).timestamp is None


class Channel:
    def __init__(self):
        self.sent = []

    async def send(self, *a, **k):
        self.sent.append(k)


class Message:
    def __init__(self):
        self.channel = Channel()


def spec(n, desc_len=10):
    return ({"title": f"t{n}", "description": "x" * desc_len, "fields": [],
             "image": f"i{n}.png", "footer": None}, b"\x89PNG fake")


def test_several_embeds_go_in_one_message():
    m = Message()
    asyncio.run(bot.send_specs(m, [spec(k) for k in range(7)]))
    assert len(m.channel.sent) == 1
    sent = m.channel.sent[0]
    assert len(sent["embeds"]) == 7 and len(sent["files"]) == 7
    stamped = [e.timestamp is not None for e in sent["embeds"]]
    assert stamped == [False] * 6 + [True], "only the last embed is stamped"


class Msg:
    _next = 100

    def __init__(self, channel, embed):
        Msg._next += 1
        self.id, self.channel, self.embed = Msg._next, channel, embed
        self.edits, self.deleted = 0, False

    async def edit(self, embed=None):
        self.embed = embed
        self.edits += 1

    async def delete(self):
        self.deleted = True


class LiveChannel:
    def __init__(self):
        self.sent, self.last_message_id = [], None

    async def send(self, *a, **k):
        m = Msg(self, k.get("embed"))
        self.sent.append((m, k))
        self.last_message_id = m.id
        return m


@pytest.fixture
def live(monkeypatch):
    from rok_farm import live_feed
    monkeypatch.setattr(bot, "LIVE", live_feed.LiveState())
    monkeypatch.setattr(bot, "_panel_msg", None)
    monkeypatch.setattr(bot, "_panel_sig", None)
    monkeypatch.setattr(bot, "farm_procs", lambda: [1])
    monkeypatch.setattr(bot, "wd_procs", lambda: [1])
    return bot.LIVE


def test_the_panel_is_one_message_edited_in_place(live):
    ch = LiveChannel()
    asyncio.run(bot.refresh_panel(ch))
    asyncio.run(bot.refresh_panel(ch))              # nothing new: no call at all
    assert len(ch.sent) == 1 and ch.sent[0][0].edits == 0
    live.feed("  *** MINE 4 ***")
    asyncio.run(bot.refresh_panel(ch))
    assert len(ch.sent) == 1 and ch.sent[0][0].edits == 1
    assert "Mine 4" in ch.sent[0][0].embed.title


def test_the_panel_moves_back_under_anything_posted_after_it(live):
    ch = LiveChannel()
    asyncio.run(bot.refresh_panel(ch))
    first = ch.sent[0][0]
    ch.last_message_id = 999                          # a reply landed below it
    live.feed("  *** MINE 5 ***")
    asyncio.run(bot.refresh_panel(ch))
    assert len(ch.sent) == 2 and first.deleted, "the old panel stays behind"


def test_a_failed_mine_is_sent_with_its_frame(live, tmp_path, monkeypatch):
    import os
    import time as _t
    monkeypatch.setattr(bot, "SHOTS", tmp_path)
    f = tmp_path / "m6_NO_CANDIDATES_120000.png"
    f.write_bytes(b"\x89PNG fake")
    os.utime(f, (_t.time(), _t.time()))
    live.feed("  *** MINE 6 ***")
    live.feed("  [WARN] 18 consecutive empty scans -- restarting from city")
    (e,) = live.feed("  Mine 6 FAILED")
    ch = LiveChannel()
    asyncio.run(bot.send_alert(ch, e))
    (_m, kw), = ch.sent
    assert "Mine 6 failed" in kw["embed"].title
    assert kw["embed"].description == "18 empty scans in a row"
    assert kw["file"].filename == "fail.png"


def test_a_restart_clears_the_panels_it_left_behind(monkeypatch):
    """Each bot restart posted a new panel; the old one stayed, frozen."""
    from types import SimpleNamespace
    from rok_farm import live_feed

    def msg(author, footer):
        m = SimpleNamespace(author=author, id=id(author) + len(footer or ""),
                            deleted=False)
        m.embeds = [SimpleNamespace(footer=SimpleNamespace(text=footer))] if footer else []

        async def delete():
            m.deleted = True
        m.delete = delete
        return m

    ours = bot.client.user                          # None in a test: no login
    old_panel = msg(ours, live_feed.PANEL_FOOTER)
    alert = msg(ours, None)
    other = msg("operator", live_feed.PANEL_FOOTER)

    class Hist:
        def history(self, limit):
            async def gen():
                for m in (old_panel, alert, other):
                    yield m
            return gen()

    monkeypatch.setattr(bot, "_panel_msg", None)
    asyncio.run(bot.clear_old_panels(Hist()))
    assert old_panel.deleted and not alert.deleted and not other.deleted


def test_more_than_discord_takes_is_split():
    """Ten embeds, 6,000 characters: past either, a second message."""
    m = Message()
    asyncio.run(bot.send_specs(m, [spec(k, 1500) for k in range(5)]))
    assert len(m.channel.sent) == 2
    assert sum(len(s["embeds"]) for s in m.channel.sent) == 5
