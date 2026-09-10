"""The main menu -- what someone sees when they double-click the app.

Deliberately the same verbs the Discord bot exposes, driven by the same code
in rok_farm.session_control: start, stop, status, report, plus setup and the
board flasher. Anything that can be done from a phone can be done here, and
neither surface can drift into behaving differently from the other.
"""

from __future__ import annotations

import sys
import time

from rok_farm import PROJECT_ROOT
from rok_farm import session_control as sc
from app.ui import (BOLD, DIM, RESET, Closed, ask, bad, confirm, info, ok,
                    pause, rule, say, t, title, warn)


def _fmt_procs(label, procs):
    if not procs:
        return f"{label}: -"
    return f"{label}: " + ", ".join(f"pid {p.pid}" for p in procs)


def show_status() -> None:
    title(t("TRẠNG THÁI", "STATUS"))
    farm = sc.farm_procs()
    wd = sc.wd_procs()
    game = sc.game_proc()
    say(_fmt_procs(t("Farm", "Farm"), farm))
    say(_fmt_procs(t("Watchdog", "Watchdog"), wd))
    say(t("Game: ", "Game: ") + (f"pid {game.pid}" if game else "-"))

    try:
        from tools import flash_board as fb
        bridges, native = fb.scan()
        say(t("Mạch  : ", "Board : ")
            + (", ".join(b.device for b in bridges) if bridges
               else t("không thấy", "not found")))
        say(t("HID   : ", "HID   : ")
            + (t("Windows đã nhận", "attached to Windows") if fb.hid_present()
               else t("chưa nhận", "not attached")))
    except Exception as e:
        warn(f"{type(e).__name__}: {e}")

    idle = sc.idle_seconds()
    say(t(f"Không chạm chuột/phím: {idle:.0f}s",
          f"Input idle for: {idle:.0f}s"))
    rule()


def do_start() -> None:
    title(t("BẮT ĐẦU FARM", "START THE FARM"))
    if sc.farm_procs():
        warn(t("Farm đang chạy rồi. Dừng trước đã (mục 3).",
               "A farm is already running. Stop it first (item 3)."))
        return

    idle = sc.idle_seconds()
    if idle < sc.HUMAN_IDLE_GUARD:
        warn(t(f"Vừa có người dùng máy ({idle:.0f}s trước).",
               f"Someone used this machine {idle:.0f}s ago."))
        say(t("Khi farm chạy, mạch ESP32 sẽ giành chuột với bạn.",
              "While the farm runs, the ESP32 fights you for the mouse."))
        if not confirm(t("Vẫn bắt đầu?", "Start anyway?"), default=False):
            return

    say(t("NÊN đóng Rise of Kingdoms trước -- bot tự mở lấy.",
          "PREFER the game closed -- the bot launches it itself."))
    say(t("Bám vào client đang chạy nền làm hỏng 3 mỏ đầu tiên.",
          "Attaching to a backgrounded client costs the first three mines."))
    if not confirm(t("Tiếp tục?", "Continue?"), default=True):
        return

    say(sc.do_start(with_watchdog=True))


def do_stop() -> None:
    title(t("DỪNG FARM", "STOP THE FARM"))
    keep = not confirm(t("Đóng luôn Rise of Kingdoms?", "Close Rise of Kingdoms too?"),
                       default=True)
    say(t("Đang dừng và trả lại chuột...", "Stopping and releasing the mouse..."))
    say(sc.do_stop(close_game=not keep))


def do_flash() -> None:
    title(t("MẠCH ESP32", "ESP32 BOARD"))
    from tools import flash_board as fb
    argv = sys.argv
    try:
        sys.argv = ["flash_board.py", "--check"]
        fb.main()
    finally:
        sys.argv = argv
    rule()
    if confirm(t("Nạp lại firmware?", "Flash the firmware again?"), default=False):
        if sc.farm_procs():
            bad(t("Farm đang chạy và đang giữ cổng COM. Dừng farm trước.",
                  "A farm is running and holding the COM port. Stop it first."))
            return
        try:
            sys.argv = ["flash_board.py", "--force"]
            fb.main()
        finally:
            sys.argv = argv


def do_report() -> None:
    title(t("BÁO CÁO", "REPORT"))
    say(sc.do_report())


def do_bot() -> None:
    title(t("DISCORD BOT", "DISCORD BOT"))
    if sc.find_procs("bot"):
        warn(t("Bot đang chạy rồi.", "The bot is already running."))
        return
    if not (PROJECT_ROOT / ".env").is_file():
        bad(t("Chưa có .env. Chạy mục 1 (cài đặt) trước.",
              "No .env yet. Run item 1 (setup) first."))
        return
    pid = sc.spawn_detached("bot")
    if pid:
        ok(t(f"Bot đã chạy nền (pid {pid}). Nhắn !status trong Discord để thử.",
             f"Bot running in the background (pid {pid}). Send !status in Discord to test."))
    else:
        bad(t("Bot không lên được. Xem logs/overnight/discord_bot.log",
              "The bot did not come up. See logs/overnight/discord_bot.log"))


ITEMS = [
    ("1", lambda: __import__("app.wizard", fromlist=["run"]).run(),
     ("Cài đặt lần đầu (mạch + game + Discord)",
      "First-run setup (board + game + Discord)")),
    ("2", do_start, ("Bắt đầu farm", "Start the farm")),
    ("3", do_stop, ("Dừng farm và trả lại chuột", "Stop the farm, release the mouse")),
    ("4", do_bot, ("Bật Discord bot (điều khiển từ điện thoại)",
                   "Start the Discord bot (control it from your phone)")),
    ("5", show_status, ("Xem trạng thái", "Show status")),
    ("6", do_flash, ("Kiểm tra / nạp lại mạch ESP32",
                     "Check / re-flash the ESP32 board")),
    ("7", do_report, ("Báo cáo phiên vừa chạy", "Report on the last run")),
]


def run() -> int:
    while True:
        title(t("ROK FARM", "ROK FARM"))
        for key, _, (vi, en) in ITEMS:
            say(f"  {BOLD}{key}{RESET}. {t(vi, en)}")
        say(f"  {BOLD}0{RESET}. " + t("Thoát", "Quit"))
        say(DIM + t("   (đóng cửa sổ này KHÔNG dừng farm -- dùng mục 3)",
                    "   (closing this window does NOT stop the farm -- use item 3)") + RESET)
        try:
            choice = ask("\n" + t("Chọn", "Choose"))
        except Closed:
            return 0
        if choice in ("0", "q", "quit", "exit"):
            return 0
        fn = next((f for k, f, _ in ITEMS if k == choice), None)
        if fn is None:
            bad(t("Không có mục đó.", "No such item."))
            continue
        try:
            fn()
        except Closed:
            return 0
        except KeyboardInterrupt:
            warn(t("Đã huỷ.", "Cancelled."))
        except Exception as e:
            bad(f"{type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
        pause()
