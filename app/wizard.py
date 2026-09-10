"""First-run setup, written for someone who has never flashed a board.

Every step is idempotent and says what it found before it changes anything, so
re-running the wizard after a half-finished attempt is safe and is in fact the
recommended way to fix a step that went wrong.

Nothing here is required to run the farm -- each step maps to something that
can also be done by hand (see docs/SETUP.vi.md). The wizard exists so the
answer to "what do I do now" is never "read the source".
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from rok_farm import PROJECT_ROOT
from app import ui
from app.ui import (Closed, ask, bad, confirm, info, ok, rule, say, step,
                    t, title, warn)

TOTAL = 5


# ------------------------------------------------------------------ 1. deps

def check_dependencies() -> bool:
    step(1, TOTAL, t("Kiểm tra thư viện", "Checking libraries"))
    if getattr(sys, "frozen", False):
        ok(t("Bản đóng gói -- thư viện đã nằm sẵn trong app.",
             "Packaged build -- libraries ship inside the app."))
        return True

    needed = {
        "cv2": "opencv-python", "numpy": "numpy", "mss": "mss",
        "serial": "pyserial", "PIL": "Pillow", "win32gui": "pywin32",
        "esptool": "esptool", "psutil": "psutil", "discord": "discord.py",
    }
    missing = []
    for mod, pkg in needed.items():
        try:
            __import__(mod)
        except Exception:
            missing.append(pkg)
    if missing:
        bad(t(f"Thiếu: {', '.join(missing)}", f"Missing: {', '.join(missing)}"))
        say(t("  Cài bằng:  .venv\\Scripts\\python -m pip install -r requirements.txt",
              "  Install with:  .venv\\Scripts\\python -m pip install -r requirements.txt"))
        return False
    ok(t("Đủ thư viện.", "All libraries present."))
    return True


# ----------------------------------------------------------------- 2. board

def setup_board() -> bool:
    step(2, TOTAL, t("Mạch ESP32-S3 (chuột/bàn phím giả)",
                     "The ESP32-S3 board (the fake mouse/keyboard)"))
    from tools import flash_board as fb

    say(t("Cắm mạch vào cổng USB có chữ UART/COM (không phải cổng còn lại).",
          "Plug the board into the USB socket marked UART/COM (not the other one)."))
    say(t("Phải dùng cáp truyền dữ liệu -- cáp chỉ để sạc trông y hệt nhưng không chạy.",
          "It must be a data cable -- a charge-only cable looks identical and will not work."))
    rule()

    bridges, native = fb.scan()
    if not bridges:
        info(t("Chưa thấy mạch. Đang chờ 60 giây...",
               "No board yet. Waiting 60 seconds..."))
        board = fb.wait_for_board(60.0)
        if board is None:
            bad(t("Không tìm thấy mạch. Bỏ qua bước này -- chạy lại wizard sau khi cắm được.",
                  "No board found. Skipping -- re-run the wizard once it is plugged in."))
            return False
    else:
        board = bridges[0]

    ok(t(f"Thấy mạch ở {board}", f"Found the board at {board}"))

    if fb.firmware_alive(board.device):
        ok(t("Mạch đã có firmware và trả lời PING.",
             "It already has the firmware and answers PING."))
        if fb.hid_present():
            ok(t("Windows đã nhận nó là chuột/bàn phím.",
                 "Windows sees it as a mouse/keyboard."))
        else:
            warn(t("Trả lời PING nhưng Windows chưa nhận HID. Rút ra cắm lại một lần.",
                   "Answers PING but Windows has not attached the HID. Unplug and replug once."))
        if not confirm(t("Nạp lại firmware đè lên?", "Flash the firmware again anyway?"),
                       default=False):
            return True

    if not (fb.FIRMWARE_DIR / "manifest.json").is_file():
        bad(t(f"Chưa có firmware dựng sẵn trong {fb.FIRMWARE_DIR}.",
              f"No prebuilt firmware in {fb.FIRMWARE_DIR}."))
        say(t("  Bản đóng gói luôn kèm sẵn. Nếu chạy từ source: cd esp32-s3 && pio run",
              "  The packaged app ships it. From source: cd esp32-s3 && pio run"))
        return False

    say(t("Đang nạp -- đừng rút cáp.", "Flashing -- do not unplug."))
    # Drive the flasher exactly as the CLI does, with an explicit port so it
    # cannot pick a different board than the one just reported.
    sys_argv = sys.argv
    rc = 1
    try:
        sys.argv = ["flash_board.py", "--port", board.device, "--force"]
        rc = fb.main()
    finally:
        sys.argv = sys_argv
    if rc == 0:
        ok(t("Nạp xong.", "Flashed."))
        return True
    bad(t("Nạp thất bại. Thử lại, hoặc giữ nút BOOT khi cắm cáp.",
          "Flashing failed. Try again, or hold the BOOT button while plugging the cable in."))
    return False


# ------------------------------------------------------------------ 3. game

def check_game() -> bool:
    step(3, TOTAL, t("Rise of Kingdoms", "Rise of Kingdoms"))
    from rok_farm.game_process import GameProcess

    # Constructing it IS the resolution: --launcher-path > ROK_LAUNCHER_PATH >
    # profiles/paths.json > Start Menu shortcut > registry. Cheap and no side
    # effect beyond caching a path it discovered.
    try:
        path = GameProcess().launcher_path
    except Exception as e:
        path = None
        info(f"{type(e).__name__}: {e}")

    if path and Path(path).is_file():
        ok(t(f"Thấy launcher: {path}", f"Found the launcher: {path}"))
    else:
        warn(t("Không tự tìm được launcher.exe.",
               "Could not find launcher.exe automatically."))
        given = ask(t("Dán đường dẫn tới launcher.exe (bỏ trống để bỏ qua)",
                      "Paste the full path to launcher.exe (blank to skip)"))
        if given:
            p = Path(given.strip('"'))
            if not p.is_file():
                bad(t("Không có file đó.", "No such file."))
                return False
            import json
            pf = PROJECT_ROOT / "profiles" / "paths.json"
            data = json.loads(pf.read_text(encoding="utf-8")) if pf.is_file() else {}
            data["launcher"] = str(p)
            pf.parent.mkdir(parents=True, exist_ok=True)
            pf.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            ok(t(f"Đã lưu vào {pf}", f"Saved to {pf}"))
        else:
            return False

    say("")
    say(t("Lưu ý: launcher.exe cần quyền Administrator. Chạy app này bằng "
          "'Run as administrator' thì nó tự kế thừa, nếu không Windows sẽ hiện "
          "hộp thoại UAC mà bot KHÔNG bấm hộ được.",
          "Note: launcher.exe needs administrator rights. Run this app as "
          "administrator and it inherits them silently; otherwise Windows shows "
          "a UAC prompt the bot CANNOT click for you."))
    return True


# --------------------------------------------------------------- 4. discord

ENV_TEMPLATE = """# Remote control over Discord. See docs/SETUP.vi.md.
DISCORD_BOT_TOKEN={token}
DISCORD_OWNER_ID={owner}
DISCORD_CHANNEL_ID={channel}
"""


def setup_discord() -> bool:
    step(4, TOTAL, t("Điều khiển từ xa qua Discord",
                     "Remote control over Discord"))
    env = PROJECT_ROOT / ".env"
    existing = {}
    if env.is_file():
        for raw in env.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()
        if existing.get("DISCORD_BOT_TOKEN") and existing.get("DISCORD_OWNER_ID"):
            ok(t("Đã cấu hình rồi.", "Already configured."))
            if not confirm(t("Nhập lại?", "Enter it again?"), default=False):
                return True

    say(t("Bot Discord cho phép bật/tắt farm và xem ảnh màn hình từ điện thoại.",
          "The Discord bot lets you start/stop the farm and see screenshots from your phone."))
    say(t("Bỏ qua được -- farm vẫn chạy bằng menu tại máy.",
          "Optional -- the farm still runs from the menu on this machine."))
    if not confirm(t("Cấu hình bây giờ?", "Set it up now?"), default=True):
        return True

    rule()
    say(t("1. Vào https://discord.com/developers/applications -> New Application",
          "1. Go to https://discord.com/developers/applications -> New Application"))
    say(t("2. Tab Bot -> Reset Token -> copy (chỉ hiện MỘT lần)",
          "2. Bot tab -> Reset Token -> copy it (shown ONCE)"))
    say(t("3. Cùng tab, bật MESSAGE CONTENT INTENT -> Save Changes",
          "3. Same tab, turn on MESSAGE CONTENT INTENT -> Save Changes"))
    rule()
    token = ask(t("Dán BOT TOKEN", "Paste the BOT TOKEN"),
                existing.get("DISCORD_BOT_TOKEN", ""))
    if not token:
        warn(t("Bỏ trống -- bỏ qua Discord.", "Blank -- skipping Discord."))
        return True

    rule()
    say(t("Discord -> Settings -> Advanced -> bật Developer Mode.",
          "Discord -> Settings -> Advanced -> turn on Developer Mode."))
    say(t("Rồi chuột phải vào TÊN CỦA BẠN -> Copy User ID.",
          "Then right-click YOUR OWN NAME -> Copy User ID."))
    say(t("Bot chỉ nghe lời tài khoản này. Không có nó, bot từ chối chạy.",
          "The bot obeys this account and nobody else. Without it, it refuses to start."))
    owner = ask(t("Dán USER ID của bạn", "Paste your USER ID"),
                existing.get("DISCORD_OWNER_ID", ""))
    if not owner:
        bad(t("Bắt buộc phải có -- không lưu gì cả.",
              "This one is required -- nothing was saved."))
        return False

    channel = ask(t("CHANNEL ID (tuỳ chọn, chuột phải kênh -> Copy Channel ID)",
                    "CHANNEL ID (optional: right-click the channel -> Copy Channel ID)"),
                  existing.get("DISCORD_CHANNEL_ID", ""))

    env.write_text(ENV_TEMPLATE.format(token=token, owner=owner, channel=channel),
                   encoding="utf-8")
    ok(t(f"Đã lưu {env}", f"Saved {env}"))
    warn(t("File này chứa token -- đừng gửi cho ai, đừng commit.",
           "That file holds the token -- do not share it, do not commit it."))
    return True


# ------------------------------------------------------------------ 5. done

def finish(results: dict) -> None:
    step(5, TOTAL, t("Xong", "Done"))
    for name, good in results.items():
        (ok if good else warn)(name)
    rule()
    say(t("Bắt đầu farm: chọn mục 2 ở menu chính.",
          "To start farming: pick item 2 in the main menu."))
    say(t("Trước khi bắt đầu, NÊN đóng Rise of Kingdoms -- bot tự mở lấy. "
          "Bám vào một client đang chạy nền làm hỏng 3 mỏ đầu tiên.",
          "Before starting, PREFER the game closed -- the bot launches it "
          "itself. Attaching to a client already running in the background "
          "costs the first three mines."))


def run() -> int:
    title(t("CÀI ĐẶT LẦN ĐẦU", "FIRST-RUN SETUP"))
    say(t(f"Thư mục: {PROJECT_ROOT}", f"Folder: {PROJECT_ROOT}"))

    results = {}
    results[t("Thư viện", "Libraries")] = check_dependencies()
    try:
        results[t("Mạch ESP32", "ESP32 board")] = setup_board()
    except Closed:
        raise
    except Exception as e:
        bad(f"{type(e).__name__}: {e}")
        results[t("Mạch ESP32", "ESP32 board")] = False
    try:
        results[t("Game", "Game")] = check_game()
    except Closed:
        raise
    except Exception as e:
        bad(f"{type(e).__name__}: {e}")
        results[t("Game", "Game")] = False
    try:
        results[t("Discord", "Discord")] = setup_discord()
    except Closed:
        raise
    except Exception as e:
        bad(f"{type(e).__name__}: {e}")
        results[t("Discord", "Discord")] = False

    finish(results)
    return 0 if all(results.values()) else 1
