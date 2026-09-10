"""The window a non-technical user actually sees. Four tabs, big buttons.

tkinter, because it ships with Python and survives PyInstaller without a
second runtime to explain to anyone.

Two rules the whole file obeys:

  * Nothing slow runs on the UI thread. Flashing a board takes ~15 s and
    stopping a farm takes ~20 s; either would freeze the window into the
    "not responding" state that makes people force-quit halfway through a
    flash. Work goes to a worker thread and talks back through a queue.
  * Every screen says what is wrong AND what to do about it. "Không thấy
    mạch" on its own is where a non-technical user gives up, so that state
    carries the cable, the socket and the board model with it.
"""

from __future__ import annotations

import queue
import threading
import traceback
from datetime import datetime

import tkinter as tk
from tkinter import messagebox, ttk

from rok_farm import PROJECT_ROOT
from rok_farm import session_control as sc
from app.ui import LANG, t

REFRESH_MS = 2000

BG = "#1e1f22"
CARD = "#2b2d31"
FG = "#e6e6e6"
MUTED = "#9aa0a6"
GOOD = "#4ade80"
WARN = "#fbbf24"
BAD = "#f87171"
ACCENT = "#5865f2"


# --------------------------------------------------------------------------
# worker plumbing

class Worker:
    """Runs one job at a time off the UI thread and streams its output back.

    The jobs here (flash, stop, report) all print their progress, so `write`
    is handed to them as a stand-in for stdout rather than each one growing
    its own callback.
    """

    def __init__(self, app):
        self.app = app
        self.q: queue.Queue = queue.Queue()
        self.thread: threading.Thread | None = None

    @property
    def busy(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, name, fn):
        if self.busy:
            return False
        self.q.put(("busy", name))

        def run():
            try:
                fn(self.write)
            except Exception:
                self.write(traceback.format_exc())
            finally:
                self.q.put(("done", name))

        self.thread = threading.Thread(target=run, daemon=True, name=name)
        self.thread.start()
        return True

    def write(self, text):
        self.q.put(("log", str(text)))


class _Tee:
    """File-like object that forwards print() from a job into the log pane."""

    def __init__(self, write):
        self._write = write
        self._buf = ""

    def write(self, s):
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._write(line)

    def flush(self):
        if self._buf:
            self._write(self._buf)
            self._buf = ""


# --------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ROK Farm")
        self.geometry("880x660")
        self.minsize(760, 560)
        self.configure(bg=BG)

        self.worker = Worker(self)
        self._style()
        self._build()
        self.after(200, self._pump)
        self.after(400, self._refresh)

    # ---------------------------------------------------------------- chrome

    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure(".", background=BG, foreground=FG, fieldbackground=CARD)
        s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook.Tab", background=CARD, foreground=MUTED,
                    padding=(18, 10), font=("Segoe UI", 10))
        s.map("TNotebook.Tab", background=[("selected", BG)],
              foreground=[("selected", FG)])
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=CARD)
        s.configure("TLabel", background=BG, foreground=FG,
                    font=("Segoe UI", 10))
        s.configure("Card.TLabel", background=CARD, foreground=FG)
        s.configure("Muted.TLabel", background=BG, foreground=MUTED,
                    font=("Segoe UI", 9))
        s.configure("CardMuted.TLabel", background=CARD, foreground=MUTED,
                    font=("Segoe UI", 9))
        s.configure("H1.TLabel", background=BG, foreground=FG,
                    font=("Segoe UI Semibold", 15))
        s.configure("Big.TLabel", background=CARD, foreground=FG,
                    font=("Segoe UI Semibold", 26))
        s.configure("TButton", font=("Segoe UI", 10), padding=(14, 9))
        s.configure("Go.TButton", font=("Segoe UI Semibold", 11),
                    padding=(18, 12))
        s.configure("TEntry", insertcolor=FG)

    def _build(self):
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(bar, text="ROK Farm", bg=BG, fg=FG,
                 font=("Segoe UI Semibold", 17)).pack(side="left")
        self.dots = tk.Label(bar, text="", bg=BG, fg=MUTED,
                             font=("Segoe UI", 10))
        self.dots.pack(side="right")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self.tab_board = ttk.Frame(nb)
        self.tab_farm = ttk.Frame(nb)
        self.tab_discord = ttk.Frame(nb)
        self.tab_stats = ttk.Frame(nb)
        nb.add(self.tab_board, text=t("1. Mạch ESP32", "1. ESP32 board"))
        nb.add(self.tab_farm, text=t("2. Chạy farm", "2. Run the farm"))
        nb.add(self.tab_discord, text=t("3. Discord", "3. Discord"))
        nb.add(self.tab_stats, text=t("4. Thống kê", "4. Statistics"))

        self._build_board(self.tab_board)
        self._build_farm(self.tab_farm)
        self._build_discord(self.tab_discord)
        self._build_stats(self.tab_stats)

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", padx=16, pady=(0, 14))
        tk.Label(wrap, text=t("Nhật ký", "Log"), bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w")
        self.log = tk.Text(wrap, height=8, bg="#111214", fg="#cfd3d8",
                           insertbackground=FG, relief="flat", wrap="word",
                           font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")

    # ------------------------------------------------------------ tab: board

    def _build_board(self, parent):
        card = ttk.Frame(parent, style="Card.TFrame")
        card.pack(fill="x", padx=14, pady=14, ipady=10)
        self.board_state = tk.Label(card, text="...", bg=CARD, fg=FG,
                                    font=("Segoe UI Semibold", 13),
                                    anchor="w", justify="left")
        self.board_state.pack(fill="x", padx=16, pady=(12, 4))
        self.board_detail = tk.Label(card, text="", bg=CARD, fg=MUTED,
                                     font=("Segoe UI", 9), anchor="w",
                                     justify="left")
        self.board_detail.pack(fill="x", padx=16, pady=(0, 10))

        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=14)
        self.btn_flash = ttk.Button(
            row, text=t("Nạp firmware vào mạch", "Flash the board"),
            style="Go.TButton", command=self.do_flash)
        self.btn_flash.pack(side="left")
        ttk.Button(row, text=t("Kiểm tra lại", "Re-check"),
                   command=self._refresh_board).pack(side="left", padx=8)

        self.help_box = tk.Label(
            parent, text="", bg=BG, fg=MUTED, justify="left", anchor="nw",
            font=("Segoe UI", 9), wraplength=780)
        self.help_box.pack(fill="both", expand=True, padx=16, pady=14)

    HELP_NOT_FOUND = (
        "KHÔNG THẤY MẠCH. Kiểm tra theo đúng thứ tự này:\n\n"
        "1. CÁP  -- đây là nguyên nhân số một. Cáp chỉ-để-sạc và cáp truyền\n"
        "   dữ liệu trông y hệt nhau. Đổi sang cáp khác trước khi làm gì.\n\n"
        "2. CẮM CẢ HAI CỔNG  -- mạch ESP32-S3 có 2 cổng USB-C và khi chạy\n"
        "   farm thì CẢ HAI đều phải cắm vào máy tính:\n"
        "      cổng UART/COM  -> nhận lệnh, và là cổng dùng để nạp\n"
        "      cổng USB/OTG   -> đóng vai chuột + bàn phím thật\n"
        "   Riêng lúc NẠP thì chỉ cần cổng UART/COM.\n\n"
        "3. LOẠI MẠCH  -- cần ESP32-S3 DevKitC-1, bản N16R8 (16MB flash).\n"
        "   ESP32 thường (không phải S3) KHÔNG chạy được: nó không có USB\n"
        "   gốc nên không giả làm chuột được.\n\n"
        "4. Nếu nạp mãi vẫn lỗi: giữ nút BOOT trên mạch trong lúc cắm cáp."
    )
    HELP_NOT_FOUND_EN = (
        "NO BOARD FOUND. Check these in order:\n\n"
        "1. THE CABLE -- the number one cause. A charge-only cable and a data\n"
        "   cable look identical. Swap it before trying anything else.\n\n"
        "2. PLUG IN BOTH SOCKETS -- the ESP32-S3 has two USB-C sockets and\n"
        "   running the farm needs BOTH connected:\n"
        "      UART/COM socket -> carries commands, and is what you flash\n"
        "      USB/OTG socket  -> is the actual mouse and keyboard\n"
        "   Flashing alone only needs the UART/COM socket.\n\n"
        "3. THE BOARD -- it must be an ESP32-S3 DevKitC-1, N16R8 (16MB).\n"
        "   A plain ESP32 will NOT work: no native USB, so it cannot\n"
        "   pretend to be a mouse.\n\n"
        "4. If flashing keeps failing: hold BOOT while plugging the cable in."
    )
    HELP_WRONG_PORT = (
        "Đang cắm vào CỔNG SAI. Máy tính thấy cổng USB gốc của mạch\n"
        "(USB-JTAG), không phải cổng UART.\n\n"
        "Chuyển cáp sang cổng USB-C còn lại -- cổng có chữ UART hoặc COM\n"
        "in cạnh nó. Chỉ cổng đó nạp được.\n\n"
        "Sau khi nạp xong thì cắm cả hai cổng để chạy farm."
    )
    HELP_WRONG_PORT_EN = (
        "Wrong socket. Windows can see the board's native USB (USB-JTAG),\n"
        "not its UART bridge.\n\n"
        "Move the cable to the other USB-C socket -- the one with UART or COM\n"
        "printed beside it. Only that one can be flashed.\n\n"
        "Once flashed, plug in both sockets to run the farm."
    )
    HELP_READY = (
        "Mạch sẵn sàng.\n\n"
        "Nhớ cắm CẢ HAI cổng USB-C khi chạy farm: cổng UART mang lệnh, cổng\n"
        "USB gốc mới là thứ thật sự di chuyển chuột. Thiếu cổng thứ hai thì\n"
        "mạch vẫn trả lời nhưng con trỏ không nhúc nhích."
    )
    HELP_READY_EN = (
        "The board is ready.\n\n"
        "Keep BOTH USB-C sockets plugged in while farming: the UART carries\n"
        "the commands, but the native USB is what actually moves the mouse.\n"
        "With only one plugged, the board answers and the cursor never moves."
    )

    # ------------------------------------------------------------- tab: farm

    def _build_farm(self, parent):
        card = ttk.Frame(parent, style="Card.TFrame")
        card.pack(fill="x", padx=14, pady=14, ipady=10)
        self.farm_state = tk.Label(card, text="...", bg=CARD, fg=FG,
                                   font=("Segoe UI Semibold", 13), anchor="w")
        self.farm_state.pack(fill="x", padx=16, pady=(12, 4))
        self.farm_detail = tk.Label(card, text="", bg=CARD, fg=MUTED,
                                    font=("Segoe UI", 9), anchor="w",
                                    justify="left")
        self.farm_detail.pack(fill="x", padx=16, pady=(0, 10))

        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=14)
        self.btn_start = ttk.Button(row, text=t("Bắt đầu farm", "Start farming"),
                                    style="Go.TButton", command=self.do_start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(row, text=t("Dừng farm", "Stop farming"),
                                   command=self.do_stop)
        self.btn_stop.pack(side="left", padx=8)

        tk.Label(
            parent, bg=BG, fg=MUTED, justify="left", anchor="nw",
            font=("Segoe UI", 9), wraplength=780,
            text=t(
                "NÊN đóng Rise of Kingdoms trước khi bấm Bắt đầu -- bot tự mở "
                "game lấy. Nếu bám vào một game đang chạy sẵn ở chế độ nền, bot "
                "sẽ hỏng 3 mỏ đầu tiên: game ngừng vẽ lại màn hình khi không ở "
                "tiền cảnh nên bot cứ nhìn thấy đúng một khung hình cũ.\n\n"
                "Đóng cửa sổ này KHÔNG dừng farm. Farm chạy tách rời để việc "
                "tắt/mở app không giết một phiên đang chạy. Muốn dừng hẳn thì "
                "bấm Dừng farm, hoặc gõ !stop trong Discord.\n\n"
                "Dừng farm luôn tắt rung chuột của mạch. Nếu chỉ tắt tiến trình "
                "thì mạch vẫn nhích chuột và bạn sẽ không dùng máy được.",
                "PREFER Rise of Kingdoms closed before you press Start -- the "
                "bot launches it itself. Attaching to a client already running "
                "in the background costs the first three mines: the game stops "
                "redrawing when it is not in front, so the bot keeps seeing one "
                "stale frame.\n\n"
                "Closing this window does NOT stop the farm. It runs detached so "
                "restarting the app cannot take a live run down. To really stop "
                "it, press Stop, or send !stop in Discord.\n\n"
                "Stopping always turns the board's idle jitter off. Killing the "
                "process alone leaves it nudging the pointer and you cannot use "
                "the machine.")
        ).pack(fill="both", expand=True, padx=16, pady=14)

    # ---------------------------------------------------------- tab: discord

    DISCORD_STEPS = (
        "Bot Discord cho phép bật/tắt farm và xem ảnh màn hình từ điện thoại.\n"
        "Bỏ qua cũng được -- farm vẫn chạy bằng tab 2.\n\n"
        "1. Vào  discord.com/developers/applications  ->  New Application\n"
        "2. Tab Bot  ->  Reset Token  ->  copy (token chỉ hiện MỘT lần)\n"
        "3. Vẫn tab Bot, kéo xuống Privileged Gateway Intents  ->  bật\n"
        "   MESSAGE CONTENT INTENT  ->  Save Changes\n"
        "   Thiếu bước này thì bot nhận tin nhắn rỗng và mọi lệnh im lặng.\n"
        "4. Discord -> Settings -> Advanced -> bật Developer Mode.\n"
        "   Chuột phải TÊN BẠN -> Copy User ID.  Chuột phải KÊNH -> Copy Channel ID.\n\n"
        "Bot chỉ nghe lời đúng một tài khoản (User ID ở dưới). Thiếu nó thì bot\n"
        "từ chối chạy -- thà không có điều khiển từ xa còn hơn có cái ai cũng bấm được."
    )
    DISCORD_STEPS_EN = (
        "The Discord bot lets you start/stop the farm and see screenshots from\n"
        "your phone. Optional -- the farm still runs from tab 2.\n\n"
        "1. discord.com/developers/applications  ->  New Application\n"
        "2. Bot tab  ->  Reset Token  ->  copy it (shown ONCE)\n"
        "3. Same tab, Privileged Gateway Intents  ->  turn on\n"
        "   MESSAGE CONTENT INTENT  ->  Save Changes\n"
        "   Without it the bot gets empty message text and every command\n"
        "   silently does nothing.\n"
        "4. Discord -> Settings -> Advanced -> Developer Mode on.\n"
        "   Right-click YOUR NAME -> Copy User ID. Right-click the CHANNEL ->\n"
        "   Copy Channel ID.\n\n"
        "The bot obeys exactly one account (the User ID below). Without it the\n"
        "bot refuses to start -- no remote control beats an unlocked one."
    )

    def _build_discord(self, parent):
        tk.Label(parent, text=t(self.DISCORD_STEPS, self.DISCORD_STEPS_EN),
                 bg=BG, fg=MUTED, justify="left", anchor="nw",
                 font=("Segoe UI", 9)).pack(fill="x", padx=16, pady=(14, 8))

        form = ttk.Frame(parent, style="Card.TFrame")
        form.pack(fill="x", padx=14, pady=6, ipady=8)
        self.env_vars = {}
        fields = [
            ("DISCORD_BOT_TOKEN", t("Bot Token", "Bot Token"), True),
            ("DISCORD_OWNER_ID", t("User ID của bạn (bắt buộc)",
                                   "Your User ID (required)"), False),
            ("DISCORD_CHANNEL_ID", t("Channel ID (tuỳ chọn)",
                                     "Channel ID (optional)"), False),
        ]
        for i, (key, label, secret) in enumerate(fields):
            tk.Label(form, text=label, bg=CARD, fg=FG,
                     font=("Segoe UI", 9)).grid(row=i, column=0, sticky="w",
                                                padx=(16, 10), pady=6)
            var = tk.StringVar()
            ent = ttk.Entry(form, textvariable=var, width=58,
                            show="*" if secret else "")
            ent.grid(row=i, column=1, sticky="we", padx=(0, 16), pady=6)
            self.env_vars[key] = var
        form.columnconfigure(1, weight=1)

        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=14, pady=10)
        ttk.Button(row, text=t("Lưu cài đặt", "Save settings"),
                   command=self.save_env).pack(side="left")
        self.btn_bot = ttk.Button(row, text=t("Bật bot", "Start the bot"),
                                  style="Go.TButton", command=self.do_bot)
        self.btn_bot.pack(side="left", padx=8)
        ttk.Button(row, text=t("Tắt bot", "Stop the bot"),
                   command=self.do_bot_stop).pack(side="left")
        self.bot_state = tk.Label(parent, text="", bg=BG, fg=MUTED,
                                  font=("Segoe UI", 9), anchor="w")
        self.bot_state.pack(fill="x", padx=16)
        self.load_env()

    # ------------------------------------------------------------ tab: stats

    def _build_stats(self, parent):
        grid = tk.Frame(parent, bg=BG)
        grid.pack(fill="x", padx=14, pady=14)
        self.tiles = {}
        specs = [
            ("mines", t("Mỏ đã farm", "Mines farmed")),
            ("marches", t("Lượt hành quân", "Marches sent")),
            ("success", t("Tỉ lệ thành công", "Success rate")),
            ("rate", t("Mỏ mỗi giờ", "Mines per hour")),
        ]
        for i, (key, label) in enumerate(specs):
            card = tk.Frame(grid, bg=CARD)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            grid.columnconfigure(i, weight=1)
            val = tk.Label(card, text="-", bg=CARD, fg=FG,
                           font=("Segoe UI Semibold", 24))
            val.pack(pady=(14, 0))
            tk.Label(card, text=label, bg=CARD, fg=MUTED,
                     font=("Segoe UI", 9)).pack(pady=(2, 14))
            self.tiles[key] = val

        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=14)
        ttk.Button(row, text=t("Cập nhật", "Refresh"),
                   command=self.refresh_stats).pack(side="left")
        ttk.Button(row, text=t("Báo cáo đầy đủ", "Full report"),
                   command=self.do_report).pack(side="left", padx=8)
        self.stats_scope = tk.Label(row, text="", bg=BG, fg=MUTED,
                                    font=("Segoe UI", 9))
        self.stats_scope.pack(side="right")

        self.stats_text = tk.Text(parent, bg="#111214", fg="#cfd3d8",
                                  relief="flat", wrap="none",
                                  font=("Consolas", 9))
        self.stats_text.pack(fill="both", expand=True, padx=16, pady=14)
        self.stats_text.configure(state="disabled")
        self.after(600, self.refresh_stats)

    # ---------------------------------------------------------------- actions

    def do_flash(self):
        from tools import flash_board as fb
        import sys

        if sc.farm_procs():
            messagebox.showwarning(
                "ROK Farm",
                t("Farm đang chạy và đang giữ cổng COM. Dừng farm ở tab 2 trước.",
                  "A farm is running and holding the COM port. Stop it on tab 2 first."))
            return
        if not messagebox.askyesno(
                "ROK Farm",
                t("Ghi firmware lên mạch?\n\nĐừng rút cáp trong lúc nạp (~15 giây).",
                  "Write the firmware to the board?\n\n"
                  "Do not unplug it while it writes (~15 seconds).")):
            return

        def job(write):
            old = sys.stdout
            sys.stdout = _Tee(write)
            try:
                sys.argv = ["flash_board.py", "--force"]
                rc = fb.main()
            finally:
                sys.stdout = old
            write(t(f"Kết quả: {'THÀNH CÔNG' if rc == 0 else 'THẤT BẠI'}",
                    f"Result: {'OK' if rc == 0 else 'FAILED'}"))

        self.worker.start("flash", job)

    def do_start(self):
        if sc.farm_procs():
            messagebox.showinfo("ROK Farm",
                                t("Farm đang chạy rồi.", "Already running."))
            return
        idle = sc.idle_seconds()
        if idle < sc.HUMAN_IDLE_GUARD:
            if not messagebox.askyesno(
                    "ROK Farm",
                    t(f"Vừa có người dùng máy ({idle:.0f} giây trước).\n\n"
                      "Khi farm chạy, mạch sẽ giành chuột với bạn.\n\nVẫn bắt đầu?",
                      f"Someone used this machine {idle:.0f}s ago.\n\n"
                      "While farming, the board fights you for the mouse.\n\n"
                      "Start anyway?")):
                return
        self.worker.start("start", lambda w: w(sc.do_start(with_watchdog=True)))

    def do_stop(self):
        if not sc.farm_procs() and not sc.wd_procs():
            messagebox.showinfo("ROK Farm",
                                t("Không có farm nào đang chạy.", "Nothing is running."))
            return
        close = messagebox.askyesno(
            "ROK Farm", t("Đóng luôn Rise of Kingdoms?",
                          "Close Rise of Kingdoms too?"))
        self.worker.start("stop", lambda w: w(sc.do_stop(close_game=close)))

    def do_bot(self):
        if sc.find_procs("bot"):
            messagebox.showinfo("ROK Farm",
                                t("Bot đang chạy rồi.", "The bot is already running."))
            return
        if not self.env_vars["DISCORD_BOT_TOKEN"].get().strip():
            messagebox.showwarning(
                "ROK Farm",
                t("Chưa có Bot Token. Điền vào ô ở trên rồi bấm Lưu cài đặt.",
                  "No Bot Token yet. Fill it in above and press Save settings."))
            return
        if not self.env_vars["DISCORD_OWNER_ID"].get().strip():
            messagebox.showwarning(
                "ROK Farm",
                t("Chưa có User ID. Bot từ chối chạy khi không biết nghe lời ai.",
                  "No User ID. The bot refuses to run without an owner."))
            return
        self.save_env(quiet=True)

        def job(write):
            pid = sc.spawn_detached("bot")
            write(t(f"Bot đã chạy nền (pid {pid}). Nhắn !status trong Discord để thử."
                    if pid else
                    "Bot không lên được. Xem logs/overnight/discord_bot.log",
                    f"Bot running in the background (pid {pid}). Send !status to test."
                    if pid else
                    "The bot did not come up. See logs/overnight/discord_bot.log"))

        self.worker.start("bot", job)

    def do_bot_stop(self):
        procs = sc.find_procs("bot")
        if not procs:
            messagebox.showinfo("ROK Farm",
                                t("Bot không chạy.", "The bot is not running."))
            return

        def job(write):
            for p in procs:
                sc.kill_tree(p)
                write(t(f"Đã tắt bot pid {p.pid}", f"Stopped bot pid {p.pid}"))

        self.worker.start("botstop", job)

    def do_report(self):
        self.worker.start("report", lambda w: w(sc.do_report()))

    # -------------------------------------------------------------------- env

    def load_env(self):
        env = PROJECT_ROOT / ".env"
        if not env.is_file():
            return
        for raw in env.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() in self.env_vars:
                self.env_vars[k.strip()].set(v.strip())

    def save_env(self, quiet=False):
        token = self.env_vars["DISCORD_BOT_TOKEN"].get().strip()
        owner = self.env_vars["DISCORD_OWNER_ID"].get().strip()
        channel = self.env_vars["DISCORD_CHANNEL_ID"].get().strip()
        if token and not owner:
            messagebox.showwarning(
                "ROK Farm",
                t("Phải có User ID. Bot sẽ từ chối chạy nếu không biết nghe lời ai.",
                  "The User ID is required. The bot refuses to start without an owner."))
            return
        (PROJECT_ROOT / ".env").write_text(
            "# Discord remote control. Giữ kín file này -- nó chứa token.\n"
            f"DISCORD_BOT_TOKEN={token}\n"
            f"DISCORD_OWNER_ID={owner}\n"
            f"DISCORD_CHANNEL_ID={channel}\n", encoding="utf-8")
        if not quiet:
            self._log(t(f"Đã lưu {PROJECT_ROOT / '.env'}",
                        f"Saved {PROJECT_ROOT / '.env'}"))
            messagebox.showinfo(
                "ROK Farm",
                t("Đã lưu. File .env chứa token -- đừng gửi cho ai.",
                  "Saved. The .env file holds your token -- do not share it."))

    # ---------------------------------------------------------------- refresh

    def refresh_stats(self):
        try:
            from app import stats
            from tools.dev.overnight.report import DEFAULT_LOG
            runs = stats.parse(DEFAULT_LOG)
        except Exception as e:
            self._log(f"{type(e).__name__}: {e}")
            return
        if not runs:
            self.stats_scope.configure(
                text=t("Chưa có dữ liệu -- chạy farm một lần đã.",
                       "No data yet -- run the farm once."))
            return

        from app import stats as st
        tot = st.totals(runs)
        self.tiles["mines"].configure(text=str(tot.mines))
        self.tiles["marches"].configure(text=str(tot.marches))
        self.tiles["success"].configure(text=f"{tot.success_pct:.0f}%")
        self.tiles["rate"].configure(text=f"{tot.per_hour:.1f}")
        self.stats_scope.configure(
            text=t(f"{len(runs)} lần chạy, {tot.duration_min / 60:.0f} giờ",
                   f"{len(runs)} runs, {tot.duration_min / 60:.0f} hours"))

        lines = [t("10 LẦN CHẠY GẦN NHẤT", "LAST 10 RUNS"), ""]
        head = t(f"{'Bắt đầu':<21}{'Mỏ':>5}{'Hành quân':>11}{'Hỏng':>7}{'Phút':>7}{'Đạt':>7}",
                 f"{'Started':<21}{'Mines':>7}{'Marches':>9}{'Failed':>8}{'Min':>6}{'OK':>6}")
        lines += [head, "-" * len(head)]
        for r in runs[-10:]:
            lines.append(f"{r.started:<21}{r.mines:>5}{r.marches:>11}"
                         f"{r.failed:>7}{r.duration_min:>7.0f}{r.success_pct:>6.0f}%")

        fails = st.top_failures(tot, limit=8, lang=LANG)
        if fails:
            lines += ["", t("VÌ SAO HỎNG (cộng dồn tất cả các lần chạy)",
                            "WHY THINGS FAILED (all runs)"), ""]
            width = max(len(lbl) for lbl, _ in fails)
            for label, n in fails:
                lines.append(f"  {label:<{width}}  {n:>6}")

        self.stats_text.configure(state="normal")
        self.stats_text.delete("1.0", "end")
        self.stats_text.insert("1.0", "\n".join(lines))
        self.stats_text.configure(state="disabled")

    def _refresh_board(self):
        try:
            from tools import flash_board as fb
            bridges, native = fb.scan()
        except Exception as e:
            self.board_state.configure(text=f"{type(e).__name__}: {e}", fg=BAD)
            return bridges if False else None

        if bridges:
            port = bridges[0].device
            hid = fb.hid_present()
            self.board_state.configure(
                text=t(f"Đã thấy mạch ở {port}", f"Board found on {port}"),
                fg=GOOD if hid else WARN)
            self.board_detail.configure(text=t(
                f"HID (chuột/bàn phím giả): {'đã nhận' if hid else 'CHƯA nhận -- cắm nốt cổng USB thứ hai'}",
                f"HID (fake mouse/keyboard): {'attached' if hid else 'NOT attached -- plug in the second USB socket'}"))
            self.help_box.configure(text=t(self.HELP_READY, self.HELP_READY_EN))
            self.btn_flash.state(["!disabled"])
        elif native:
            self.board_state.configure(
                text=t("Sai cổng USB", "Wrong USB socket"), fg=WARN)
            self.board_detail.configure(text=t(
                "Thấy cổng USB gốc, không thấy cổng UART.",
                "Found the native USB, not the UART bridge."))
            self.help_box.configure(
                text=t(self.HELP_WRONG_PORT, self.HELP_WRONG_PORT_EN))
            self.btn_flash.state(["disabled"])
        else:
            self.board_state.configure(
                text=t("Không thấy mạch", "No board found"), fg=BAD)
            self.board_detail.configure(text="")
            self.help_box.configure(
                text=t(self.HELP_NOT_FOUND, self.HELP_NOT_FOUND_EN))
            self.btn_flash.state(["disabled"])

    def _refresh(self):
        try:
            farm = sc.farm_procs()
            wd = sc.wd_procs()
            bot = sc.find_procs("bot")
            game = sc.game_proc()

            if farm:
                self.farm_state.configure(
                    text=t(f"Farm đang chạy (pid {farm[0].pid})",
                           f"Farming (pid {farm[0].pid})"), fg=GOOD)
            else:
                self.farm_state.configure(
                    text=t("Farm không chạy", "Not farming"), fg=MUTED)
            self.farm_detail.configure(text=t(
                f"Watchdog: {'có' if wd else 'không'}    "
                f"Game: {'đang mở' if game else 'đóng'}",
                f"Watchdog: {'yes' if wd else 'no'}    "
                f"Game: {'open' if game else 'closed'}"))

            self.bot_state.configure(text=t(
                f"Bot: đang chạy (pid {bot[0].pid})" if bot else "Bot: không chạy",
                f"Bot: running (pid {bot[0].pid})" if bot else "Bot: not running"))

            self._refresh_board()
            self.dots.configure(text=t(
                f"farm {'ON' if farm else 'off'}   bot {'ON' if bot else 'off'}",
                f"farm {'ON' if farm else 'off'}   bot {'ON' if bot else 'off'}"))
        except Exception as e:
            self._log(f"{type(e).__name__}: {e}")
        self.after(REFRESH_MS, self._refresh)

    # -------------------------------------------------------------------- log

    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", f"{datetime.now():%H:%M:%S}  {msg}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _pump(self):
        try:
            while True:
                kind, payload = self.worker.q.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "busy":
                    self._log(t(f"-- bắt đầu: {payload}", f"-- started: {payload}"))
                    for b in (self.btn_flash, self.btn_start, self.btn_stop,
                              self.btn_bot):
                        b.state(["disabled"])
                elif kind == "done":
                    self._log(t(f"-- xong: {payload}", f"-- done: {payload}"))
                    for b in (self.btn_start, self.btn_stop, self.btn_bot):
                        b.state(["!disabled"])
                    self.refresh_stats()
        except queue.Empty:
            pass
        self.after(200, self._pump)


def run() -> int:
    App().mainloop()
    return 0
