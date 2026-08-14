"""GemFarmRunner -- setup, the main farm loop, teardown and the report.

The runner owns the state; every behaviour lives in a mixin (see rok_farm's
package docstring). It stays a single object so `self._click`/`self._grab`/
`self._find` work from anywhere in the flow and so `PlayerActions` can keep
using the runner as its action context.
"""

from __future__ import annotations

import random
import threading
import time

import numpy as np

from anti_detection.mouse_humanizer import MouseHumanizer
from anti_detection.notification_watcher import NotificationWatcher
from anti_detection.player_actions import PlayerActions
from anti_detection.profile_loader import DEFAULT_PROFILE, ProfileLoader
from anti_detection.session_manager import SessionManager
from anti_detection.timing_engine import TimingEngine
from capture.screen_capture import ScreenCapture
from vision.gem_classifier import GemPatchClassifier
from vision.state_detector import StateDetector
from vision.template_cache import TemplateCache
from vision.template_matcher import Match, TemplateMatcher

from rok_farm.button_registry import ButtonRegistry
from rok_farm.capture_svc import CaptureMixin
from rok_farm.config import (AUTO_LAUNCH_GAME, COUNTDOWN_SECONDS,
                             DELAY_AFTER_CLICK, DELAY_BETWEEN_MINES,
                             FRAME_STALL_TIMEOUT, MAX_MARCH_MINUTES,
                             OCCUPIED_TEMPLATES, RESTART_AFTER_FAILS,
                             RESTART_BREAK_MINUTES, RESTART_ON_RECOVERY,
                             SCREENSHOT_DIR, TEMPLATE_DIR, WINDOW_LOST_TIMEOUT)
from rok_farm.detect import DetectMixin
from rok_farm.dismiss import DismissMixin
from rok_farm.flow_steps import GemFlowMixin
from rok_farm.game_process import GameLifecycleMixin, GameProcess
from rok_farm.input_hid import HidInputMixin
from rok_farm.logging_setup import FAIL, INFO, PASS, WARN, logger
from rok_farm.persona import PersonaMixin
from rok_farm.phases import PhasesMixin
from rok_farm.queue_ocr import QueueMixin, _OCR_BACKEND
from rok_farm.recovery import RecoveryMixin
from rok_farm.screenshots import save_screenshot
from rok_farm.state_probe import StateProbeMixin
from rok_farm.vision_llm import VisionOracle, build_oracle


class GemFarmRunner(PersonaMixin, HidInputMixin, CaptureMixin, DetectMixin,
                    StateProbeMixin, DismissMixin, QueueMixin, RecoveryMixin,
                    GameLifecycleMixin, GemFlowMixin, PhasesMixin):
    """Live gem farm runner."""

    def __init__(self, port: str, count: int = 1, auto_learn: bool = False,
                 loop: bool = False, max_marches: int = 5,
                 account_id: str = "default",
                 actions_override: list[str] | None = None,
                 recalibrate: bool = False,
                 skip_mail_alliance: bool = False,
                 initial_alttab: bool = True,
                 auto_launch: bool = AUTO_LAUNCH_GAME,
                 allow_restart: bool = RESTART_ON_RECOVERY,
                 launcher_path: str | None = None,
                 oracle_provider: str | None = None,
                 oracle_models: list[str] | None = None,
                 use_oracle: bool = True):
        self.port = port
        self.count = count
        self.auto_learn = auto_learn
        self.loop = loop
        self.max_marches = max_marches
        self._account_id = account_id
        self._recalibrate = recalibrate
        self._skip_mail_alliance = skip_mail_alliance
        self._initial_alttab = initial_alttab
        # Tracks whether we believe we're on the world map. Set when we reach it
        # / stay after a march; cleared on city return / alt-tab. Avoids the
        # flaky post-march city_btn-vs-globe re-detection (they read ~tied).
        self._view_is_world = False
        self.sc: ScreenCapture | None = None
        self.cache: TemplateCache | None = None
        self.matcher: TemplateMatcher | None = None
        self.detector: StateDetector | None = None
        self.conn = None
        self.cmd = None
        self.win: dict | None = None
        self.results: list[dict] = []
        self.mines_completed = 0
        self.gathered_positions: list[tuple[int, int]] = []
        self._edge_gems: list[Match] = []
        self.classifier = GemPatchClassifier()
        self.classifier.load()
        self._night_logged = False
        self._raw_frame: np.ndarray | None = None
        self._has_moveto = False
        self._mouse_scale = 1.0

        # Frame buffer state. Created here, not in _start_capture_thread, so
        # _grab() is safe during setup -- launching the game runs detection
        # before the capture thread exists.
        self._frame_lock = threading.Lock()
        self._bg_frame = None
        self._bg_back = None
        self._capture_running = False

        # Position history for fixed buttons; gates every click that comes from
        # a template match (see _click_match).
        self.buttons = ButtonRegistry()

        # Layer 2. With no key configured this builds an oracle with no
        # providers, i.e. permanently disabled, and nothing else changes.
        self.oracle = (build_oracle(oracle_provider, oracle_models)
                       if use_oracle else VisionOracle([]))

        # --- Game process lifecycle ---
        self.game = GameProcess(launcher_path)
        self._auto_launch = auto_launch
        self._restart_enabled = allow_restart
        self._restart_times: list[float] = []
        self._window_lost_since: float | None = None
        self._window_lost_timeout = WINDOW_LOST_TIMEOUT
        self._frame_stall_timeout = FRAME_STALL_TIMEOUT
        self._last_frame_ok = time.time()
        self._capture_paused = False

        loader = ProfileLoader()
        self._profile = loader.load_random() if loader.list_profiles() else DEFAULT_PROFILE.copy()

        self._persona = self._load_or_create_persona()
        self._apply_persona()

        self.timing = TimingEngine(self._profile)
        self.session = SessionManager(self._profile)
        self.humanizer = MouseHumanizer(self._profile)
        self._actions = PlayerActions(self, self._persona)
        if actions_override:
            self._actions._preferred = list(actions_override)
        self._notif = NotificationWatcher()

        self._scroll_overshoot_chance = self._jitter(
            self._persona["scroll_overshoot"], 0.08)

    # --- Setup ---

    def _setup(self) -> bool:
        print("--- Setup ---\n")

        # Order matters: templates and the ESP32 come up FIRST, because starting
        # the game (when it isn't open yet) needs both -- the launcher's Play
        # button is template-matched and clicked over HID.
        self.cache = TemplateCache(TEMPLATE_DIR)
        self.matcher = TemplateMatcher(self.cache, threshold=0.50)
        # Faster matcher for the zoom-settle poll. Must still span the full scale
        # range (the gather/mine sit off 1.0), just with fewer samples than the
        # 7-scale default -- a too-narrow set missed the gather button (conf 0.56).
        # The decisive gather checks below still use the full self.matcher.
        self.fast_matcher = TemplateMatcher(self.cache, threshold=0.50,
                                            scales=[0.7, 0.85, 1.0, 1.15, 1.3])
        self.detector = StateDetector(self.matcher, min_confidence=0.80)

        key_templates = [
            "resources/gem_icon", "resources/gem_mine_close",
            "buttons/gather_btn", "buttons/world_map_city_btn",
            "buttons/new_troop_btn", "buttons/march_btn_orange",
            "buttons/march_btn", "buttons/city_btn",
            "ui/btn_mail", "ui/btn_alliance",
            "ui/btn_x_close_mail", "ui/btn_x_close_alliance", "ui/btn_x_close_bag",
            "ui/city_food", "ui/city_wood",
        ]
        for t in key_templates:
            img = self.cache.get(t)
            status = PASS if img is not None else FAIL
            size = f"{img.shape[1]}x{img.shape[0]}" if img is not None else "MISSING"
            print(f"  [{status}] {t}: {size}")

        optional_templates = ["ui/btn_confirm_reconnect", *OCCUPIED_TEMPLATES]
        for t in optional_templates:
            img = self.cache.get(t)
            status = PASS if img is not None else WARN
            size = f"{img.shape[1]}x{img.shape[0]}" if img is not None else "MISSING (optional)"
            print(f"  [{status}] {t}: {size}")

        from serial_comm.connection import SerialConnection
        from serial_comm.command_buffer import CommandBuffer

        self.conn = SerialConnection(port=self.port)
        if not self.conn.connect():
            print(f"  [{FAIL}] ESP32 connect failed")
            return False
        self.cmd = CommandBuffer(self.conn)
        self.cmd.start()
        self._wait(DELAY_AFTER_CLICK)

        # Game window. If it isn't there, start the client (unless the user
        # opted out) and wait until the city view answers.
        self.sc = ScreenCapture()
        self.win = self.sc.find_window()
        if not self.win:
            if not self._ensure_game_running():
                return False
        if not self.win:
            print(f"  [{FAIL}] Game window not found")
            return False
        print(f"  [{PASS}] Window: {self.win['width']}x{self.win['height']}")

        # Resize the game window to the target content width (same as
        # `python -m anti_detection.player_actions`) so template scales match.
        # No-op when a fresh launch already did it.
        self._ensure_target_size()

        # Mouse calibration is the visible "cursor jerks up/down/left/right" at
        # startup. It only depends on the machine (MOVETO support + pointer
        # speed), so measure it once and cache it in the persona -- subsequent
        # runs reuse it and skip the jerk. Use --recalibrate to force a refresh.
        cached = self._persona.get("has_moveto")
        if cached is not None and not self._recalibrate:
            self._has_moveto = cached
            if not cached:
                self._mouse_scale = self._persona.get("mouse_scale", 1.0)
            src = "cached"
        else:
            self._has_moveto = self._probe_moveto()
            if not self._has_moveto:
                self._mouse_scale = self._calibrate_mouse_scale()
            self._persona["has_moveto"] = self._has_moveto
            self._persona["mouse_scale"] = self._mouse_scale
            self._save_persona()
            src = "measured"

        if self._has_moveto:
            print(f"  [{PASS}] ESP32: {self.port} (MOVETO verified, {src})")
        else:
            print(f"  [{WARN}] ESP32: {self.port} (relative MOVE, "
                  f"scale={self._mouse_scale:.2f}x, {src})")

        self._start_capture_thread()
        time.sleep(0.2)

        frame = self._grab()
        if frame is not None:
            save_screenshot(frame, "setup_initial")

        stats = self.classifier.get_stats()
        if stats["is_warm"]:
            print(f"  [{PASS}] Classifier: {stats['total']} samples (gem={stats['gem']}, not_gem={stats['not_gem']})")
        else:
            print(f"  [{INFO}] Classifier: cold start ({stats['total']}/{10} samples)")

        p = self._profile
        print(f"\n  --- Anti-Detection ---")
        print(f"  [{PASS}] Profile: {p.get('name', 'default')}")
        print(f"  [{INFO}] Action delay: {p['timing']['action_delay_mean']}ms "
              f"(+/-{p['timing']['action_delay_std']}ms)")
        print(f"  [{INFO}] Micro-pause: {p['timing']['micro_pause_chance']*100:.0f}% chance, "
              f"{p['timing']['micro_pause_range'][0]}-{p['timing']['micro_pause_range'][1]}ms")
        print(f"  [{INFO}] Session: farm {p['session']['farm_duration_mean']}min "
              f"-> break {p['session']['break_duration_mean']}min")
        print(f"  [{INFO}] Daily limit: {p['session']['daily_hours_max']}h, "
              f"window {p['session']['active_window'][0]}-{p['session']['active_window'][1]}")
        print(f"  [{INFO}] Mouse: overshoot {p['mouse']['overshoot_chance']*100:.0f}%, "
              f"spread +/-{p['mouse']['click_spread']}px, "
              f"hold {p['mouse']['hold_ms'][0]}-{p['mouse']['hold_ms'][1]}ms")

        if self.oracle.enabled:
            print(f"  [{PASS}] Vision oracle: {', '.join(self.oracle.provider_names)}")
        else:
            print(f"  [{INFO}] Vision oracle: off (no API key) -- local detection only")

        if self.loop:
            if _OCR_BACKEND:
                print(f"  [{PASS}] Queue detection: {_OCR_BACKEND}")
            else:
                print(f"  [{INFO}] Queue detection: internal counter (no OCR)")
            print(f"  [{INFO}] Max marches: {self.max_marches}")

            if self._notif.setup():
                print(f"  [{PASS}] Return detection: Windows toast "
                      f"('troops returned', name-independent)")
            else:
                print(f"  [{WARN}] Return detection: toast listener unavailable, "
                      f"falling back to {MAX_MARCH_MINUTES}min timer + queue OCR")

        self._record("setup", True, "OK")
        return True

    # --- Main flow ---

    def _initial_prepare(self):
        """Countdown so the user can get ready, then (optionally) alt-tab to the
        game. Launched from a terminal, the terminal is the foreground window, so
        the first clicks would land on it -- one ALT+TAB brings the game forward."""
        for n in range(COUNTDOWN_SECONDS, 0, -1):
            print(f"  [{INFO}] Starting in {n}...")
            time.sleep(1.0)

        if self._initial_alttab:
            print(f"  [{INFO}] Alt-tab to game window")
            self.cmd.send("COMBO", "ALT", "TAB", random.randint(50, 120))
            time.sleep(random.uniform(1.0, 2.0))
            self._refresh_window()

    def run(self):
        for f in SCREENSHOT_DIR.glob("*.png"):
            f.unlink()

        print("=" * 60)
        print("  GEM FARM FLOW -- E2E Test (Anti-Detection ON)")
        print("=" * 60)
        print(f"  Port: {self.port}")
        if self.loop:
            print(f"  Mode: loop (max {self.max_marches} marches)")
        else:
            print(f"  Target mines: {self.count}")
        print(f"  Profile: {self._profile.get('name', 'default')}")
        print()

        try:
            if not self._setup():
                return

            self._initial_prepare()

            i = 1
            consecutive_fails = 0
            while True:
                if not self.loop and i > self.count:
                    break

                # Client health: a window that vanished or a capture that went
                # silent means the client died, and no amount of flow retrying
                # will bring it back.
                broken = self._client_looks_broken()
                if broken and not self._restart_game(broken):
                    if not self.game.is_game_running():
                        print(f"  [{FAIL}] No game window and no restart "
                              f"available -- stopping")
                        break
                    # Window is there after all: carry on and let the flow's own
                    # failure handling deal with it, without re-tripping here.
                    print(f"  [{WARN}] {broken}, continuing without a restart")
                    self._last_frame_ok = time.time()

                if self.loop:
                    queue = self._detect_march_queue()
                    if queue:
                        used, total = queue
                        if used >= total:
                            print(f"\n  [{INFO}] Queue full ({used}/{total}) -- burst done, city + wait for return")
                            self.mines_completed = used
                            self._phase_full_cycle()
                            continue
                        self.mines_completed = used
                        print(f"  [{INFO}] Queue: {used}/{total}, {total - used} slot(s) free")
                    elif self.mines_completed >= self.max_marches:
                        print(f"\n  [{INFO}] Queue likely full ({self.mines_completed}/{self.max_marches} by counter) -- burst done, city + wait for return")
                        self._phase_full_cycle()
                        continue

                status = self._check_session()
                if status == "break":
                    dur = self.session.get_break_duration()
                    logger.info("Taking break for %.0fs", dur)
                    print(f"\n  [{INFO}] Session break: {dur / 60:.1f} min")
                    # A long break is when a real player actually quits the game
                    # instead of leaving it running behind other windows. Short
                    # breaks stay an alt-tab (cheap, and keeps the client warm).
                    if (dur >= RESTART_BREAK_MINUTES * 60
                            and self._restart_game(
                                f"long break {dur / 60:.0f}min",
                                extra_wait=dur)):
                        continue
                    self._tab_away()
                    time.sleep(dur)
                    self._tab_back()
                    continue

                label = f"{i}" if self.loop else f"{i}/{self.count}"
                print(f"\n{'*' * 60}")
                print(f"  *** MINE {label} ***")
                print(f"  Session: {self.session.elapsed_minutes:.0f} min")
                print(f"{'*' * 60}")

                if not self._mine_flow(i):
                    print(f"\n  Mine {i} FAILED")
                    consecutive_fails += 1
                    if consecutive_fails >= 3:
                        print(f"  [{WARN}] {consecutive_fails} consecutive fails, attempting recovery...")
                        self._attempt_recovery()
                    if consecutive_fails >= RESTART_AFTER_FAILS:
                        # ESC back-out already failed several times, so the flow
                        # is not merely confused -- restart the client, and fall
                        # back to the old long break if restarting is off.
                        reason = f"{consecutive_fails} consecutive mine failures"
                        if not self._restart_game(reason):
                            print(f"  [{WARN}] {reason}, taking long break before retry")
                            self._tab_away()
                            time.sleep(random.uniform(120, 300))
                            self._tab_back()
                        consecutive_fails = 0
                    self._wait(random.uniform(1.0, 3.0))
                    i += 1
                    continue

                consecutive_fails = 0
                self.mines_completed += 1
                self._queue_wait_start = time.time()
                print(f"\n  Mine {i} DONE (total: {self.mines_completed})")

                # Burst: move straight to the next march. The full-queue handler
                # at the top of the loop owns the city + alt-tab-wait pause.
                self._wait(DELAY_BETWEEN_MINES)

                i += 1

        except KeyboardInterrupt:
            print("\n  Interrupted")
        except Exception as e:
            logger.exception("Error")
            self._record("ERROR", False, str(e))
        finally:
            self._teardown()
            self._print_report()

    # --- Helpers ---

    def _record(self, step: str, ok: bool, note: str):
        self.results.append({"step": step, "success": ok, "note": note})

    def _teardown(self):
        print("\n--- Teardown ---")
        self._stop_capture_thread()
        ss = self.session.session_stats()
        print(f"  Session: {ss['session_minutes']:.1f} min active, "
              f"{ss['action_count']} actions, "
              f"fatigue x{self.timing.apply_fatigue(ss['session_minutes']):.2f}")
        self.buttons.save()
        for line in self.buttons.summary():
            print(f"  [reg] {line}")
        if self.auto_learn and self.classifier.sample_count > 0:
            self.classifier.save()
            stats = self.classifier.get_stats()
            print(f"  Classifier saved: {stats['total']} samples (gem={stats['gem']}, not_gem={stats['not_gem']})")
        if self.cmd:
            self.cmd.send("RESET")
            self.cmd.stop()
        if self.conn:
            self.conn.disconnect()
        if self.sc:
            self.sc.close()
        if SCREENSHOT_DIR.exists():
            cutoff = time.time() - 3600
            for f in SCREENSHOT_DIR.glob("*.png"):
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                except Exception:
                    pass

    def _print_report(self):
        print(f"\n{'=' * 60}")
        print("  GEM FARM FLOW REPORT")
        print(f"{'=' * 60}")
        if self.loop:
            print(f"  Mode: loop | Max: {self.max_marches} | Completed: {self.mines_completed}")
        else:
            print(f"  Target: {self.count} | Completed: {self.mines_completed}")

        for r in self.results:
            s = PASS if r["success"] else FAIL
            print(f"  [{s}] {r['step']:25s} -- {r['note']}")

        print()
        if self.mines_completed == self.count:
            print(f"  [{PASS}] *** ALL {self.count} MINES COMPLETE! ***")
        elif self.mines_completed > 0:
            print(f"  [{WARN}] {self.mines_completed}/{self.count} mines done")
        else:
            print(f"  [{FAIL}] No mines completed")
        print(f"\n  Screenshots: {SCREENSHOT_DIR}\n")
