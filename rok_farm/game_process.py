"""Game client lifecycle: find, launch, quit and restart Rise of Kingdoms.

The client is NOT cycled between farm bursts -- see `phases.py`; the ~15 minute
march wait stays an alt-tab because the "troops returned" toast only fires while
the client runs in the background. This module exists for the two cases where a
real player would actually close the game:

  * startup   -- the bot is launched and the game simply is not open yet
  * long stop -- a >= RESTART_BREAK_MINUTES break, or a client that has broken
                 (window gone, capture stalled, repeated flow failures)

Launcher notes (Lilith launcher):
  * `launcher.exe` needs administrator rights. Started from an ELEVATED python
    it inherits the token and no UAC dialog appears; otherwise we ShellExecute
    "runas" and wait for the user to accept -- the UAC dialog lives on the
    secure desktop, which no capture backend can see, so the bot never clicks
    it blind.
  * The launcher window survives the game exiting, so a restart is only
    "press Play again" -- no elevation, no UAC.
  * Both the launcher window and the game window contain "Rise of Kingdoms" in
    their title, so every window lookup here matches on the owning executable.
"""

from __future__ import annotations

import ctypes
import json
import os
import random
import subprocess
import time
from pathlib import Path

import win32con
import win32gui

from capture.screen_capture import ScreenCapture
from capture.screen_info import exe_for_hwnd

from rok_farm.config import (CITY_READY_TIMEOUT, GAME_LAUNCH_TIMEOUT,
                             GAME_PROCESS_NAME, GAME_WINDOW_TITLE,
                             LAUNCHER_PROCESS_NAME, LAUNCHER_UAC_TIMEOUT,
                             LAUNCHER_WINDOW_TIMEOUT, MAX_RESTARTS_PER_HOUR,
                             MODAL_RATIO_MIN, PATHS_FILE, QUIT_TIMEOUT,
                             RESTART_COOLDOWN, WORLD_MAP_BTN_THRESHOLD)
from rok_farm.logging_setup import FAIL, INFO, PASS, WARN, logger
from rok_farm.state_probe import ScreenState, dim_ratio

PLAY_TEMPLATE = "launcher/play_btn"
PLAY_BTN_THRESHOLD = 0.70
EXIT_CONFIRM_TEMPLATE = "ui/btn_confirm_exit"

_CAPTURE_TOOL_HINT = (".venv\\Scripts\\python tools\\capture_launcher_btn.py")


# ---------------------------------------------------------------------------
# Window / process helpers
# ---------------------------------------------------------------------------

def is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def windows_for_exe(exe_name: str, min_size: int = 200) -> list[dict]:
    """Visible top-level windows owned by `exe_name`, as client-area rects."""
    found: list[dict] = []
    target = exe_name.lower()

    def _cb(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            if exe_for_hwnd(hwnd).lower() != target:
                return
            cl = win32gui.GetClientRect(hwnd)
            w, h = cl[2] - cl[0], cl[3] - cl[1]
            if w < min_size or h < min_size:
                return  # splash/tool windows
            pt = win32gui.ClientToScreen(hwnd, (0, 0))
            found.append({
                "hwnd": hwnd, "left": pt[0], "top": pt[1],
                "width": w, "height": h,
                "title": win32gui.GetWindowText(hwnd),
            })
        except Exception:
            pass

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        logger.debug("EnumWindows failed while looking for %s", exe_name)
    return found


def focus_window(hwnd, retries: int = 2) -> bool:
    """Bring a window to the foreground and CONFIRM it got there.

    Windows can refuse a foreground switch (focus-stealing lock), and the return
    value matters: a keystroke meant for the game would otherwise land on
    whatever is actually in front -- including the terminal running the bot.
    """
    for attempt in range(retries):
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
        except Exception as e:
            logger.debug("SetForegroundWindow failed: %s", e)
        time.sleep(0.4 + 0.3 * attempt)
        if win32gui.GetForegroundWindow() == hwnd:
            return True
    logger.warning("Window %s did not come to the foreground", hwnd)
    return False


def grab_rect(rect: dict):
    """Screenshot an arbitrary screen rect (used for the launcher window, which
    the game-bound ScreenCapture backend does not cover)."""
    try:
        import mss
        with mss.mss() as sct:
            shot = sct.grab({"left": rect["left"], "top": rect["top"],
                             "width": rect["width"], "height": rect["height"]})
            import numpy as np
            return np.array(shot, dtype=np.uint8)[:, :, :3]
    except Exception as e:
        logger.debug("grab_rect failed: %s", e)
        return None


def taskkill(image_name: str) -> bool:
    try:
        subprocess.run(["taskkill", "/IM", image_name, "/F"],
                       capture_output=True, timeout=15,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception as e:
        logger.warning("taskkill %s failed: %s", image_name, e)
        return False


# ---------------------------------------------------------------------------
# GameProcess
# ---------------------------------------------------------------------------

class GameProcess:
    """Locates and drives the game client + its launcher."""

    def __init__(self, launcher_path: str | None = None):
        self._paths = self._load_paths()
        self._launcher = self._resolve_launcher(launcher_path)
        self.play_btn_pct = self._paths.get("play_btn_pct")

    # --- persisted paths ---

    @staticmethod
    def _load_paths() -> dict:
        try:
            if PATHS_FILE.exists():
                # utf-8-sig so a hand-edited file with a BOM still loads.
                return json.loads(PATHS_FILE.read_text(encoding="utf-8-sig"))
        except Exception as e:
            logger.warning("Cannot read %s: %s", PATHS_FILE, e)
        return {}

    def _save_paths(self):
        try:
            PATHS_FILE.parent.mkdir(parents=True, exist_ok=True)
            PATHS_FILE.write_text(json.dumps(self._paths, indent=2),
                                  encoding="utf-8")
        except Exception as e:
            logger.warning("Cannot write %s: %s", PATHS_FILE, e)

    @property
    def launcher_path(self) -> Path | None:
        return self._launcher

    def _resolve_launcher(self, override: str | None) -> Path | None:
        """CLI > env > cached paths.json > Start Menu shortcut > registry."""
        candidates = [
            ("--launcher-path", override),
            ("ROK_LAUNCHER_PATH", os.environ.get("ROK_LAUNCHER_PATH")),
            ("profiles/paths.json", self._paths.get("launcher")),
        ]
        for source, value in candidates:
            if value and Path(value).exists():
                logger.info("Launcher from %s: %s", source, value)
                return Path(value)
            if value:
                logger.warning("Launcher path from %s does not exist: %s",
                               source, value)

        for finder in (self._from_shortcut, self._from_registry):
            path = finder()
            if path:
                self._paths["launcher"] = str(path)
                self._save_paths()
                logger.info("Launcher discovered via %s: %s",
                            finder.__name__, path)
                return path
        return None

    @staticmethod
    def _from_shortcut() -> Path | None:
        roots = [os.environ.get("ProgramData", ""), os.environ.get("APPDATA", "")]
        for root in filter(None, roots):
            start_menu = Path(root) / "Microsoft/Windows/Start Menu/Programs"
            if not start_menu.exists():
                continue
            for lnk in start_menu.rglob("*.lnk"):
                if "rise of kingdoms" not in lnk.stem.lower():
                    continue
                try:
                    import win32com.client
                    shell = win32com.client.Dispatch("WScript.Shell")
                    target = Path(shell.CreateShortCut(str(lnk)).TargetPath)
                    if target.exists():
                        return target
                except Exception as e:
                    logger.debug("Cannot resolve shortcut %s: %s", lnk, e)
        return None

    @staticmethod
    def _from_registry() -> Path | None:
        import winreg
        subkey = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    root = winreg.OpenKey(hive, subkey, 0,
                                          winreg.KEY_READ | view)
                except OSError:
                    continue
                with root:
                    for i in range(winreg.QueryInfoKey(root)[0]):
                        try:
                            name = winreg.EnumKey(root, i)
                            with winreg.OpenKey(root, name) as key:
                                display = winreg.QueryValueEx(key, "DisplayName")[0]
                                if "rise of kingdoms" not in str(display).lower():
                                    continue
                                loc = winreg.QueryValueEx(key, "InstallLocation")[0]
                                exe = Path(loc) / LAUNCHER_PROCESS_NAME
                                if exe.exists():
                                    return exe
                        except OSError:
                            continue
        return None

    # --- state ---

    def game_window(self) -> dict | None:
        wins = [w for w in windows_for_exe(GAME_PROCESS_NAME)
                if GAME_WINDOW_TITLE.lower() in w["title"].lower()]
        return wins[0] if wins else None

    def launcher_window(self) -> dict | None:
        wins = windows_for_exe(LAUNCHER_PROCESS_NAME)
        return wins[0] if wins else None

    def is_game_running(self) -> bool:
        return self.game_window() is not None

    def is_launcher_running(self) -> bool:
        return self.launcher_window() is not None

    # --- actions ---

    def start_launcher(self) -> bool:
        """Start launcher.exe and wait for its window. Elevated python starts it
        silently; otherwise the user has to accept a UAC prompt we cannot see."""
        if self.is_launcher_running():
            return True
        if not self._launcher:
            print(f"  [{FAIL}] Launcher not found. Set ROK_LAUNCHER_PATH or pass "
                  f"--launcher-path")
            return False

        workdir = str(self._launcher.parent)
        if is_elevated():
            print(f"  [{INFO}] Starting launcher (elevated): {self._launcher}")
            try:
                subprocess.Popen([str(self._launcher)], cwd=workdir,
                                 close_fds=True)
            except Exception as e:
                print(f"  [{FAIL}] Cannot start launcher: {e}")
                return False
            timeout = LAUNCHER_WINDOW_TIMEOUT
        else:
            print(f"  [{WARN}] Not running as administrator -- Windows will ask "
                  f"for permission to start the launcher.")
            print(f"  [{INFO}] Accept the UAC prompt; the bot waits and never "
                  f"clicks it (the prompt is on a desktop no capture can see).")
            print(f"  [{INFO}] Tip: run the bot from an admin terminal to skip "
                  f"this prompt entirely.")
            rc = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", str(self._launcher), None, workdir, 1)
            if rc <= 32:
                print(f"  [{FAIL}] Launcher elevation refused or failed "
                      f"(ShellExecute={rc})")
                return False
            timeout = LAUNCHER_WINDOW_TIMEOUT + LAUNCHER_UAC_TIMEOUT

        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_launcher_running():
                print(f"  [{PASS}] Launcher window is up")
                time.sleep(random.uniform(1.5, 3.0))  # let it finish painting
                return True
            time.sleep(1.0)
        print(f"  [{FAIL}] Launcher window did not appear within {timeout:.0f}s")
        return False

    def press_play(self, ctx) -> bool:
        """Click Play in the launcher window. Position comes from a captured
        template (or the stored percentage) -- it is never guessed."""
        win = self.launcher_window()
        if not win:
            print(f"  [{FAIL}] Launcher window not found")
            return False

        if not focus_window(win["hwnd"]):
            print(f"  [{WARN}] Launcher did not come to the front; another "
                  f"window may swallow the click")
        time.sleep(random.uniform(0.6, 1.2))
        win = self.launcher_window() or win

        target = None
        img = grab_rect(win)
        if img is not None and ctx.cache is not None:
            if ctx.cache.get(PLAY_TEMPLATE) is not None:
                m = ctx.matcher.match_single(img, PLAY_TEMPLATE)
                if m and m.confidence >= PLAY_BTN_THRESHOLD:
                    target = (win["left"] + m.center[0], win["top"] + m.center[1])
                    print(f"  [{PASS}] Play button matched (conf={m.confidence:.3f})")
                elif m:
                    logger.info("Play button match too weak: %.3f", m.confidence)

        if target is None and self.play_btn_pct:
            px, py = self.play_btn_pct
            target = (win["left"] + int(win["width"] * px),
                      win["top"] + int(win["height"] * py))
            print(f"  [{INFO}] Play button from stored position {px:.3f},{py:.3f}")

        if target is None:
            print(f"  [{FAIL}] No Play button template or position stored. "
                  f"Capture it once:\n      {_CAPTURE_TOOL_HINT}")
            return False

        # The launcher is not the game window: clamp the pointer to the launcher
        # rect and drop the game's no-click zones for this one click.
        with ctx._pointer_scope(win):
            ctx._click(*target)
        return True

    def quit_game(self, ctx) -> bool:
        """Close the client. Graceful ALT+F4 first (a hard kill reads as a crash
        server-side); taskkill only if the window refuses to go away."""
        win = self.game_window()
        if not win:
            return True

        # ALT+F4 hits whatever is in the foreground, so only send it once the
        # game really IS in front -- otherwise it would close the terminal
        # running the bot. No focus, no keystroke: kill the process instead.
        if not focus_window(win["hwnd"]):
            print(f"  [{WARN}] Could not focus the game -- skipping ALT+F4 "
                  f"(it would hit the wrong window) and killing the process")
            taskkill(GAME_PROCESS_NAME)
            time.sleep(3.0)
            return not self.is_game_running()

        print(f"  [{INFO}] Closing the game (ALT+F4)")
        time.sleep(random.uniform(0.5, 1.2))
        ctx.cmd.send("COMBO", "ALT", "F4", random.randint(50, 120))

        start = time.time()
        next_confirm = start + 3.0
        confirmed = False
        while time.time() - start < QUIT_TIMEOUT:
            time.sleep(1.0)
            if not self.is_game_running():
                print(f"  [{PASS}] Game closed")
                return True
            # Some builds ask "really quit?"; click it if that template exists.
            if not confirmed and time.time() >= next_confirm:
                confirmed = self._click_exit_confirm(ctx)
                next_confirm = time.time() + 4.0

        print(f"  [{WARN}] Game did not close in {QUIT_TIMEOUT:.0f}s -- taskkill")
        taskkill(GAME_PROCESS_NAME)
        time.sleep(3.0)
        return not self.is_game_running()

    def _click_exit_confirm(self, ctx) -> bool:
        """Click the in-game 'really quit?' button if that template exists."""
        win = self.game_window()
        if not win or ctx.cache is None:
            return False
        if ctx.cache.get(EXIT_CONFIRM_TEMPLATE) is None:
            return False
        img = grab_rect(win)
        if img is None:
            return False
        m = ctx.matcher.match_single(img, EXIT_CONFIRM_TEMPLATE)
        if not m or m.confidence < 0.70:
            return False
        print(f"  [{INFO}] Exit confirm dialog (conf={m.confidence:.3f}), clicking")
        with ctx._pointer_scope(win):
            ctx._click(win["left"] + m.center[0], win["top"] + m.center[1])
        return True


# ---------------------------------------------------------------------------
# Runner-side wiring
# ---------------------------------------------------------------------------

class GameLifecycleMixin:
    """Launch / restart the client from inside the farm loop."""

    def _ensure_game_running(self) -> bool:
        """Make the game window exist and the city view be usable. Returns False
        if the client could not be brought up (caller aborts the run)."""
        if self.game.is_game_running():
            return True
        if not self._auto_launch:
            print(f"  [{FAIL}] Game window not found (--no-auto-launch)")
            return False

        print(f"\n  [{INFO}] Game is not running -- launching it")
        if not self.game.start_launcher():
            return False
        if not self.game.press_play(self):
            return False
        if not self._wait_for_game_window():
            return False
        return self._wait_until_in_city()

    def _wait_for_game_window(self, timeout: float = GAME_LAUNCH_TIMEOUT) -> bool:
        print(f"  [{INFO}] Waiting for the game window (cap {timeout:.0f}s)")
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.game.is_game_running():
                # The WGC backend binds to a window handle at construction, so a
                # relaunched client needs a fresh ScreenCapture.
                self._rebind_capture()
                # Resize BEFORE anything is detected: the client opens at
                # whatever size it likes (measured 2147x1208 here), and every
                # template was captured at TARGET_CONTENT_W -- at 2147 the city
                # templates read 0.54 against a 0.72 gate, so the city check
                # below would never pass.
                self._ensure_target_size()
                print(f"  [{PASS}] Game window: "
                      f"{self.win['width']}x{self.win['height']}")
                return True
            time.sleep(2.0)
        print(f"  [{FAIL}] No game window after {timeout:.0f}s")
        return False

    def _rebind_capture(self):
        """Point ScreenCapture at the (new) game window."""
        if self.sc is not None:
            try:
                self.sc.close()
            except Exception:
                pass
        self.sc = ScreenCapture()
        for _ in range(10):
            w = self.sc.find_window()
            if w:
                self.win = w
                return
            time.sleep(1.0)

    # "The client finished loading" = any one of these is on screen. city_btn is
    # included because a session can resume straight onto the world map, not the
    # city. Note this only answers on a view with the HUD visible: an entry
    # popup or an open panel covers all four, which is why a miss is not treated
    # as fatal below.
    _READY_TEMPLATES = (
        ("ui/city_food", 0.72),
        ("ui/city_wood", 0.72),
        ("buttons/world_map_city_btn", WORLD_MAP_BTN_THRESHOLD),
        ("buttons/city_btn", 0.70),
    )

    def _wait_until_in_city(self, timeout: float = CITY_READY_TIMEOUT) -> bool:
        """Poll until the game world answers (city or world map)."""
        print(f"  [{INFO}] Waiting for the game world (cap {timeout:.0f}s)")
        deadline = time.time() + timeout
        cleared = 0
        while time.time() < deadline:
            frame = self.sc.grab_full() if self.sc else None
            if frame is not None:
                for name, thr in self._READY_TEMPLATES:
                    if self._find_on_frame(frame, name, threshold=thr):
                        print(f"  [{PASS}] Game world is up ({name})")
                        self._view_is_world = name == "buttons/city_btn"
                        return True
                # A dimmed background means the client HAS loaded and something
                # is simply sitting on top of it -- an entry popup, an event,
                # the daily gift. Waiting out the full timeout for templates
                # that are covered would be pointless.
                if dim_ratio(frame) >= MODAL_RATIO_MIN:
                    print(f"  [{PASS}] Client is up with a popup over it "
                          f"-- handing to the flow to clear it")
                    self._view_is_world = False
                    return True
                # Nothing matched and nothing is dimmed. That is the genuinely
                # ambiguous case -- still loading, sitting on a login screen, or
                # a view the templates do not cover -- so it is worth asking.
                state = self._resolve_state(frame, reason="post-launch wait")
                if state.view in ("city", "world_map"):
                    print(f"  [{PASS}] Game world is up (oracle: {state.view})")
                    self._view_is_world = state.view == "world_map"
                    return True
                # Entry popups (events, daily gift) sit on top of a loaded city.
                if cleared < 4 and self._check_reconnect_popup():
                    cleared += 1
            time.sleep(random.uniform(3.0, 6.0))

        # Timing out is NOT fatal: an event popup or a panel left open after
        # login covers every template above while the client is perfectly fine.
        # No blind ESC back-out here either -- with the capture paused around a
        # restart the "is a panel open" check reads stale frames, and ESC on a
        # clean view opens the profile panel. Hand back to the flow, which
        # navigates with live frames and runs its own recovery after 3 failures.
        print(f"  [{WARN}] Game world not confirmed in {timeout:.0f}s "
              f"(a popup or an open panel hides the HUD) -- handing back to the flow")
        return self.game.is_game_running()

    def _restart_game(self, reason: str, extra_wait: float = 0.0) -> bool:
        """Quit the client, wait, bring it back. Used for a long break and for a
        client that stopped responding -- never between ordinary bursts."""
        if not self._restart_enabled:
            print(f"  [{INFO}] Restart disabled (--no-restart); reason was: {reason}")
            return False

        now = time.time()
        self._restart_times = [t for t in getattr(self, "_restart_times", [])
                               if now - t < 3600]
        if len(self._restart_times) >= MAX_RESTARTS_PER_HOUR:
            print(f"  [{WARN}] {MAX_RESTARTS_PER_HOUR} restarts in the last hour "
                  f"-- refusing to loop, staying put")
            return False
        self._restart_times.append(now)

        print(f"\n  [{WARN}] Restarting the game: {reason}")
        logger.warning("Game restart: %s", reason)
        self._record("game_restart", True, reason)

        self._capture_paused = True
        time.sleep(0.5)  # let an in-flight grab finish before ScreenCapture swaps
        try:
            self.game.quit_game(self)
            cooldown = random.uniform(*RESTART_COOLDOWN) + max(0.0, extra_wait)
            print(f"  [{INFO}] Staying out for {cooldown / 60:.1f} min")
            time.sleep(cooldown)
            ok = self._ensure_game_running()
        finally:
            self._capture_paused = False

        if not ok:
            print(f"  [{FAIL}] Game did not come back up")
            return False

        self._view_is_world = False
        self._last_frame_ok = time.time()
        self._window_lost_since = None
        queue = self._detect_march_queue() if self.loop else None
        if queue:
            self.mines_completed = queue[0]
            print(f"  [{INFO}] After restart: queue {queue[0]}/{queue[1]}")
        return True

    def _client_looks_broken(self) -> str | None:
        """Cheap health check run once per mine; returns a reason or None."""
        now = time.time()
        if self.game.is_game_running():
            self._window_lost_since = None
        else:
            self._window_lost_since = self._window_lost_since or now
            if now - self._window_lost_since > self._window_lost_timeout:
                return (f"game window missing for "
                        f"{now - self._window_lost_since:.0f}s")

        last_ok = getattr(self, "_last_frame_ok", now)
        if now - last_ok > self._frame_stall_timeout:
            return f"no fresh frame for {now - last_ok:.0f}s"

        # A frozen client still delivers frames -- identical ones. That is
        # invisible to the check above, so ask the probe, which knows to ignore
        # the stillness of an open panel.
        state = self._probe_state()
        if not state.alive:
            return self._confirm_frozen(state)
        return None

    def _looks_loading(self) -> bool:
        """Is the client mid-load rather than dead? Worth one oracle call before
        spending a restart, because a loading screen is also static."""
        state = self._resolve_state(reason="frozen check")
        return state.view in ("loading", "login")

    def _confirm_frozen(self, first: ScreenState) -> str | None:
        """Re-check before condemning the client.

        A single still moment is not a crash -- the camera can simply be idle
        between animations -- so require the stillness to persist across a few
        seconds before spending a restart on it.
        """
        logger.info("Client may be frozen (%s), confirming...", first.note)
        for _ in range(3):
            time.sleep(5.0)
            state = self._probe_state()
            if state.alive:
                logger.info("Client recovered on re-check (%s)", state.note)
                return None
        # Still static. A loading or login screen looks exactly the same, and
        # restarting through one would be both pointless and destructive, so
        # spend one oracle call here if layer 2 is available.
        if self._looks_loading():
            print(f"  [{INFO}] Static screen is a loading/login screen, not a "
                  f"crash -- waiting instead of restarting")
            return None
        return f"client frozen ({first.note})"
