"""Burst rhythm: farm hard, then behave like a player between bursts.

Phase 1 is the march burst itself (see GemFlowMixin). Phase 2 drops back to the
city for light tasks, phase 3 alt-tabs out and waits for the Windows "troops
returned" toast -- which only fires while the game runs in the BACKGROUND, which
is why the wait is an alt-tab and not a game exit.
"""

from __future__ import annotations

import random
import statistics
import time

from anti_detection.player_actions import mail_badge_count
from rok_farm.config import (MAIL_SURPRISE, MAX_MARCH_MINUTES,
                             MODAL_RATIO_MIN, QUIT_GAP_TARGET_S,
                             RELAUNCH_OVERHEAD_S, WAIT_EARLY_MARGIN,
                             WAIT_QUIT_FACTOR, WAIT_QUIT_FLOOR_S)
from rok_farm import wake
from rok_farm.logging_setup import INFO, PASS, WARN, logger

# What one alt-tab out-and-back costs before any waiting happens: _tab_back()
# sleeps uniform(1.5, 3.0) plus a warmup capped at 8s. Staying out for less
# than this is pure overhead, so it is the floor on a planned wait.
TAB_CYCLE_COST = 20.0



class PhasesMixin:
    """Between-burst behaviour. Mixed into GemFarmRunner."""

    # Baseline for the mail rule. Class attributes so a fresh runner
    # starts with no baseline and takes its first look, rather than
    # needing every construction path to remember to set them.
    _mail_last_count: int | None = None
    _mail_last_gathers: int = 0

    def _tab_out(self):
        """Alt-tab out of the game and stop the HID idle-jitter. No fixed wait --
        caller decides how long to stay out (e.g. wait for a return toast)."""
        self.cmd.send("IDLE", "1")
        hold = random.randint(50, 120)
        self.cmd.send("COMBO", "ALT", "TAB", hold)

    # While the client sits in the background, how often the pointer is
    # touched at all, and what that looks like.
    #
    # The operator's point, 2026-09-22: the cursor freezing absolutely, for
    # exactly as long as the client is backgrounded, every single time, is a
    # clean correlation for anything sampling the global cursor. Nobody has
    # shown that ROK does sample it -- this is precaution against an
    # unconfirmed channel, not a fix for a measured one, which is worth
    # saying out loud because everything else changed today was the latter.
    #
    # It is cheap because the window is small: measured over every saved log,
    # alt-tab absences run 5 to 97 seconds, median 32. Long waits close the
    # client instead, and nothing observes anything then. So this is a handful
    # of moves in half a minute, not the 137,000 nudges that were taken out
    # this morning -- those ran every 1.75s for hours WITH THE GAME IN FRONT.
    TAB_IDLE_CHANCE = 0.55      # the rest of the time, a person who walked off
    TAB_IDLE_GAP_S = (6.0, 22.0)

    def _tab_idle_move(self):
        """One aimless pointer move, the way a hand using another window does.

        Moves only. No clicks, ever: another application owns the screen now,
        and a stray click there lands in someone's editor or browser. Moving
        is harmless, clicking is not.
        """
        win = getattr(self, "win", None)
        if not win:
            return
        x = win["left"] + int(win["width"] * random.uniform(0.12, 0.88))
        y = win["top"] + int(win["height"] * random.uniform(0.12, 0.88))
        try:
            self._moveto(x, y)
        except Exception:
            logger.debug("tab idle move failed", exc_info=True)

    def _tab_away(self):
        raw = random.lognormvariate(3.8, 0.7)
        away = max(5.0, min(600.0, raw))
        logger.info("tab away %.0fs", away)
        print(f"  [{INFO}] Alt-tab away {away:.0f}s")
        self._tab_out()

        # Sometimes nothing at all. A rule with no exception is a fingerprint
        # of its own, and a player who steps away really does leave the mouse
        # where it lies.
        if random.random() >= self.TAB_IDLE_CHANCE:
            logger.debug("tab idle: leaving the pointer where it is")
            time.sleep(away)
            return

        end = time.time() + away
        moves = 0
        while True:
            nap = random.uniform(*self.TAB_IDLE_GAP_S)
            left = end - time.time()
            if left <= nap:
                if left > 0:
                    time.sleep(left)
                break
            time.sleep(nap)
            self._tab_idle_move()
            moves += 1
        logger.debug("tab idle: %d move(s) across %.0fs", moves, away)

    def _tab_back(self):
        hold = random.randint(50, 120)
        self.cmd.send("COMBO", "ALT", "TAB", hold)
        # Stay quiet. This used to send IDLE 0, which let the board resume
        # nudging the pointer for the whole time the client was in front.
        #
        # It was put there on the idea that a pointer which never moves looks
        # fake -- a guess, arriving in a bulk commit on 2026-05-19 with no
        # measurement behind it. Measured now, it is the guess that looks
        # fake: across 13 days of logs the board sent about 137,000 micro
        # moves against 9,559 real clicks, fourteen phantom moves per click,
        # and while the client was in front the pointer never rested longer
        # than three seconds. Paired with a click rhythm that never dipped
        # below one second, that is two walls with nothing outside them.
        #
        # A human's mouse does rest. The farm's own alt-tab waits already
        # prove the game does not mind: the board is suppressed there and the
        # client sits without a single input for up to ten minutes, which has
        # always worked.
        self.cmd.send("IDLE", "1")
        time.sleep(random.uniform(1.5, 3.0))
        # ALT+TAB is a guess about window order, not a guarantee. Verify it
        # actually landed on the game: WGC capture would keep showing a healthy
        # game frame either way, so an unnoticed miss means every click for the
        # rest of the burst goes to whatever window is really in front.
        self._ensure_game_focused("after alt-tab back")
        self._client_just_returned = True
        self._refresh_window()
        if self._check_reconnect_popup():
            logger.info("tab_back: dismissed reconnect popup")
            time.sleep(random.uniform(2.0, 4.0))
        warmup = random.lognormvariate(0.5, 0.6)
        time.sleep(max(0.5, min(8.0, warmup)))
        if random.random() < 0.5:
            cx, cy = self._center_screen()
            dx, dy = random.randint(-60, 60), random.randint(-40, 40)
            self._human_drag(cx + dx, cy + dy, cx - dx, cy - dy)
            time.sleep(random.uniform(0.3, 1.2))

    _BTN_POS = {
        "bag":      (0.755, 0.953),
        "alliance": (0.803, 0.953),
        "mail":     (0.898, 0.953),
    }

    _X_CLOSE_POS = {
        "bag":      (0.865, 0.187),
        "alliance": (0.765, 0.233),
        "mail":     (0.817, 0.086),
    }

    _PANEL_ITEMS = {
        "bag": [
            (0.12, 0.187), (0.24, 0.187), (0.36, 0.187),
            (0.48, 0.187), (0.60, 0.187), (0.72, 0.187),
        ],
        "alliance": [
            (0.38, 0.52), (0.48, 0.52), (0.58, 0.52), (0.68, 0.52), (0.78, 0.52),
            (0.38, 0.72), (0.48, 0.72), (0.58, 0.72), (0.68, 0.72), (0.78, 0.72),
        ],
        "mail": [
            (0.08, 0.086), (0.18, 0.086), (0.27, 0.086),
            (0.37, 0.086), (0.46, 0.086), (0.57, 0.086),
        ],
    }

    def _close_panel(self, panel: str):
        if panel in self._X_CLOSE_POS:
            self._click_pct(*self._X_CLOSE_POS[panel], jitter_px=3)
            time.sleep(random.uniform(0.4, 0.8))

    def _phase_full_cycle(self):
        """All march slots are full. Behave like a real player between bursts:
        drop back to the city for a light idle, then wait out the gather --
        alt-tab for a short one, quit the client for a long one."""
        self._phase_city_idle()
        # Last look at the queue while the client is still in front of us -- the
        # moment the next line runs we are tabbed away and blind to it.
        self._reconcile_queue()
        self._phase_wait_return()
        self._queue_wait_start = time.time()

    def _phase_city_idle(self):
        """Phase 2: back in city while troops are out marching.

        Mail and alliance gifts used to be opened here for realism. Both open a
        panel, and a panel that fails to close strands the bot in a screen no
        step knows how to leave -- observed hanging on the alliance panel. The
        idle actions kept below never open anything, so they cannot strand it.
        """
        print(f"\n  [{INFO}] Phase: back to city, light tasks while troops march")
        self._step_return_city("city_idle")
        self._wait(random.uniform(1.0, 2.5))

        if random.random() < 0.3:
            self._actions.do(random.choice(["stare", "micro_afk", "idle_drag"]))

        # Both of these need the city, and only the city: the arc under the
        # portrait and the troop buildings are not on the world map.
        self._maybe_train_troops()
        # The arc is only READ here. Acting on it here would never work: this
        # phase is reached when the march queue is full, and the barbarian
        # auto needs a free slot to send an army to. The operator caught that
        # -- "hang cho day sao xa ap duoc". So the reading is remembered and
        # spent at the top of the next mine, where a slot has just come free.
        self._note_ap_bar()

    def _maybe_train_troops(self) -> int:
        """Collect any finished batch and start the next one. Returns how many.

        Four clicks per building, each verified before the next: collect,
        select, open the panel, press HUAN LUYEN. Nothing here trusts the
        ordering of anything -- the gem button sits one click from the free
        one, so the target is re-checked for orange immediately before it is
        pressed.
        """
        from rok_farm import training
        from rok_farm.screenshots import save_screenshot
        from rok_farm.state_probe import dim_ratio

        frame = self._grab()
        # The city, and only the city. _phase_city_idle returns there first,
        # but a return that quietly failed used to leave this step reading the
        # world map -- and on 2026-09-22 it did: two "banners" at x 0.967 and
        # 0.969, which are the HUD buttons down the right edge, followed by a
        # click on one of them and another on open ground. Four clicks nobody
        # asked for, twice, and "training: the panel did not open" to show for
        # it. Checking the view costs one template match.
        if self._on_world_map(frame):
            logger.debug("training: still on the world map -- not looking for "
                         "banners")
            return 0
        banners = training.find_banners(frame)
        if not banners:
            return 0
        if not self._window_check(120.0):
            return 0
        if not self._ensure_game_focused("troop training"):
            return 0

        print("")
        print(f"  [{INFO}] {len(banners)} troop building(s) finished -- "
              f"collecting and starting the next batch")
        logger.info("training: %d banner(s) ready", len(banners))
        done = 0
        tried: list[tuple[int, int]] = []
        for _ in range(len(banners)):
            frame = self._grab()
            banners = training.find_banners(frame)
            if not banners:
                break
            banner = training.not_yet_tried(banners, tried)
            if banner is None:
                logger.info("training: the %d banner(s) still up have all had "
                            "their turn this visit", len(banners))
                break
            tried.append((banner[0], banner[1]))
            h, w = frame.shape[:2]
            tx, ty = training.building_point(banner)

            self._click_pct(tx / w, ty / h, jitter_px=3)     # collect
            self._wait(random.uniform(1.2, 2.0))
            self._click_pct(tx / w, ty / h, jitter_px=3)     # select
            self._wait(random.uniform(1.4, 2.2))

            frame = self._grab()
            hexes = training.menu_hexes(frame)
            if not hexes:
                # 2 of the first 3 live runs ended here and none of them left
                # a picture, so there is still nothing to say WHY the two
                # clicks did not open the building menu.
                logger.info("training: no menu after selecting -- collected "
                            "only")
                if frame is not None:
                    save_screenshot(frame, "TRAIN_NO_MENU")
                continue
            hx, hy = hexes[-1][0], hexes[-1][1]
            self._click_pct(hx / w, hy / h, jitter_px=4)     # open the panel
            self._wait(random.uniform(1.6, 2.4))

            frame = self._grab()
            if frame is None or dim_ratio(frame) < training.TRAIN_PANEL_DIM_MIN:
                logger.warning("training: the panel did not open")
                if frame is not None:
                    save_screenshot(frame, "TRAIN_NO_PANEL")
                self._dismiss_modal()
                continue

            point = training.train_point(frame)
            if point is None:
                # Either the panel is not what was expected or the free button
                # is not where it should be. Both mean: do not click.
                print(f"  [{WARN}] training: cannot place HUAN LUYEN safely "
                      f"-- leaving this one")
                logger.warning("training: no safe HUAN LUYEN point")
                save_screenshot(frame, "TRAIN_NO_SAFE_POINT")
                self._dismiss_modal()
                continue
            self._click_pct(point[0] / w, point[1] / h, jitter_px=4)
            self._wait(random.uniform(1.8, 2.6))

            frame = self._grab()
            if frame is not None and dim_ratio(frame) >= training.TRAIN_PANEL_DIM_MIN:
                logger.warning("training: the panel is still up after HUAN "
                               "LUYEN")
                save_screenshot(frame, "TRAIN_STILL_OPEN")
                self._dismiss_modal()
                continue
            done += 1
            logger.info("training: batch %d started", done)
            self._wait(random.uniform(0.8, 1.6))

        if done:
            print(f"  [{INFO}] training: {done} batch(es) started")
        return done

    def _note_ap_bar(self) -> float:
        """Read the action-point arc and remember whether it is worth spending.

        Reading and acting are separate because they happen in different
        places: the arc is legible only in the city, and the auto can only run
        when a march slot is free -- which is never true in the city phase.
        """
        from rok_farm import ap_burn

        fill = ap_burn.arc_fill(self._grab())
        if fill < 0:
            return fill
        self._ap_pending = ap_burn.due(fill)
        self._ap_fill = fill
        if self._ap_pending:
            if ap_burn.spent_nothing(fill):
                logger.warning("AP arc still %.0f%% full -- the last run "
                               "spent nothing; the auto may have had no free "
                               "march slot", fill * 100)
            logger.info("AP arc %.0f%% full -- will spend it when a march "
                        "slot frees", fill * 100)
        else:
            logger.debug("AP arc %.0f%% full -- nothing to do", fill * 100)
        return fill

    def _maybe_burn_ap(self) -> bool:
        """Send the game's own auto after barbarians when the bar is near full.

        Not for the points: the operator said plainly that spending them hardly
        matters. It is that an account which gathers all day and does nothing
        else is a strange shape, and none of the anti-cheat letters has been
        explained by anything smaller.

        Every screen here was measured with the operator watching it, and the
        detail that shapes the ending is theirs: closing the client stops an
        auto run and sends the troops home. That is not an obstacle to work
        around, it is the brake -- the farm lets it run a short random while
        and then quits, which caps what gets spent without any arithmetic.
        """
        from rok_farm import ap_burn
        from rok_farm.screenshots import save_screenshot

        if not getattr(self, "_ap_pending", False):
            return False
        fill = 1.0

        # The window has to hold the whole thing: the dwell with the client
        # open, and the stretch out while the recalled troops walk home.
        planned = ap_burn.AP_DWELL_S[1] + ap_burn.AP_AWAY_S[1]
        if not self._window_check(planned):
            return False

        proc = None
        try:
            from rok_farm.session_control import game_proc
            proc = game_proc()
        except Exception:
            pass
        if proc is not None:
            up = time.time() - proc.create_time()
            if up < ap_burn.AP_WARMUP_S:
                logger.info("AP arc %.0f%% full but the client is only %.0fs "
                            "old; the auto errors before %.0fs -- leaving it",
                            fill * 100, up, ap_burn.AP_WARMUP_S)
                return False

        print("")
        print(f"  [{INFO}] AP bar is {fill * 100:.0f}% full -- sending the "
              f"game's auto after barbarians")
        logger.info("AP burn: arc %.0f%% full, starting", fill * 100)
        if not self._ensure_game_focused("AP burn"):
            return False

        if not self._on_world_map():
            self._toggle_view("ap_burn")
            self._wait(random.uniform(1.5, 2.5))

        self._click_pct(*ap_burn.SEARCH_BTN_PCT, jitter_px=6)
        self._wait(random.uniform(1.8, 2.6))
        frame = self._grab()
        if not ap_burn.auto_button_visible(frame):
            print(f"  [{WARN}] AP burn: the search panel did not open -- giving up")
            logger.warning("AP burn: search panel never appeared")
            save_screenshot(frame, "AP_NO_SEARCH_PANEL")
            return False

        sat = ap_burn.tab_saturation(frame)
        if sat < ap_burn.TAB_ACTIVE_SAT:
            logger.info("AP burn: panel is on the other tab (sat %.0f) -- "
                        "switching to the barbarian one", sat)
            self._click_pct(*ap_burn.BARB_TAB_PCT, jitter_px=5)
            self._wait(random.uniform(1.0, 1.8))
            frame = self._grab()

        self._click_pct(*ap_burn.AUTO_BTN_PCT, jitter_px=5)
        self._wait(random.uniform(2.0, 3.0))
        frame = self._grab()
        from rok_farm.state_probe import dim_ratio
        if frame is None or dim_ratio(frame) <= MODAL_RATIO_MIN:
            print(f"  [{WARN}] AP burn: the auto panel did not open -- giving up")
            logger.warning("AP burn: auto panel never appeared")
            if frame is not None:
                save_screenshot(frame, "AP_NO_AUTO_PANEL")
            self._dismiss_modal()
            return False

        self._click_pct(*ap_burn.START_BTN_PCT, jitter_px=6)
        self._wait(random.uniform(2.5, 3.5))
        frame = self._grab()
        if frame is not None and dim_ratio(frame) > MODAL_RATIO_MIN:
            print(f"  [{WARN}] AP burn: the panel is still up after START")
            logger.warning("AP burn: panel still open after pressing start")
            save_screenshot(frame, "AP_START_DID_NOTHING")
            self._dismiss_modal()
            return False

        ap_burn.note_burn(getattr(self, "_ap_fill", 0.0))
        self._ap_pending = False
        dwell = random.uniform(*ap_burn.AP_DWELL_S)
        away = random.uniform(*ap_burn.AP_AWAY_S)
        print(f"  [{INFO}] AP burn running -- staying in for {dwell / 60:.1f}min, "
              f"then out for {away / 60:.1f}min while the troops walk back")
        logger.info("AP burn started: dwell %.0fs then quit for %.0fs",
                    dwell, away)
        self._ap_dwell(dwell)

        # Quitting is what ENDS the run -- their warning, and the reason this
        # needs no sums about how many points to spend.
        #
        # No harvest or mail check on the way out. Those belong to the ordinary
        # planned quit, and a test holds them to exactly one call site so that
        # "only before quitting" stays a fact rather than a habit. The bubbles
        # keep until the next ordinary exit, minutes later.
        self._note_quit()
        self._restart_game("ending the AP run and bringing the troops home",
                           extra_wait=away)
        self._view_is_world = False
        return True

    def _ap_dwell(self, dwell: float) -> list:
        """Sit out the auto run, watching what it does to the march queue.

        This used to be one blind sleep. The operator said why that is not
        safe to guess at: the auto does not take one march slot, it takes
        however many are free -- "kha dung bao nhieu march da setup truoc do
        se dung bay nhieu", depending on the queue and on how many troops
        there are. So the one measurement taken off the 14:42 run, where
        exactly one slot happened to be free, is not a rate and cannot be
        multiplied out to a longer dwell.

        Their own log says what a longer dwell would meet: the queue fell 5->4
        at 14:37:05 and again at 14:41:56, a gathering march home every four
        or five minutes. Twenty minutes of blind dwell therefore hands the
        auto roughly four more slots as they free, and the quit recalls all of
        them with four to six minutes set aside for the walk home.

        Nothing is clamped here. How much of the queue the barbarians may hold
        is the operator's call about their own account, and it needs numbers
        under it rather than another single sample. What this does is look:
        read the queue through the run and write down what actually happens.

        The interval is randomised on purpose. A fixed beat is what drew the
        detection warning before, and this is only a screen read -- no input
        reaches the game from here.
        """
        started = time.time()
        end = started + dwell
        seen = []
        while True:
            left = end - time.time()
            if left <= 0:
                break
            if not self._sleep_until_woken(
                    min(left, random.uniform(70.0, 140.0)), "AP burn dwell"):
                break
            queue = self._detect_march_queue(retries=2)
            if not queue:
                continue
            used, total = queue
            at = time.time() - started
            seen.append((at, used, total))
            logger.info("AP dwell %.0fs in: queue %d/%d", at, used, total)
        if seen:
            from rok_farm import ap_burn
            held = max(0, max(u for _, u, _ in seen) - seen[0][1])
            logger.info("AP dwell over after %.0fs: queue %s -- the auto took "
                        "%d more slot(s) (its own limit is %d marches, and "
                        "troops at home cap it below that)",
                        time.time() - started,
                        " -> ".join(f"{u}/{t}" for _, u, t in seen),
                        held, ap_burn.AP_AUTO_MARCHES)
        else:
            logger.info("AP dwell over after %.0fs: the queue never read",
                        time.time() - started)
        return seen

    def _maintenance_hold(self) -> bool:
        """Sit out a server maintenance. Returns True if it held.

        2026-09-22: the game went into maintenance at about 13:13 and the farm
        did not notice. It panned and scanned a notice board for gem deposits
        for over an hour -- three mines logged NO_CANDIDATES -- and every
        saved frame from 14:20 on shows the notice with its countdown ticking
        down behind the farm's own drag marks. The operator's warning is the
        point of this: swiping around while that screen is up is a good way to
        collect a warning letter.

        The notice answers the question itself -- "May chu dang bao tri. Thoi
        gian con lai: 00:38:27" -- and the clock reads exactly: 2307 seconds
        off the kept frame.

        What to DO about it is the operator's rule, and it is simply how a
        person behaves. You do not poke a server that has just told you how
        long it needs. You wait for the clock to run out, press LAM MOI once,
        and then one of two things happens: you are in, or the notice returns
        with more time on it because the publisher hit a problem. So this
        waits without touching anything, presses refresh once when the clock
        is nearly out, and looks again.

        The earlier version closed the client and relaunched after the
        countdown, which reaches the same place but spends two minutes of
        client startup to press a button that is already on screen.
        """
        from rok_farm import maintenance as mt
        from rok_farm.queue_ocr import ocr_texts
        from rok_farm.screenshots import save_screenshot

        frame = self._grab()
        lines = mt.read_lines(frame, ocr_texts)
        if not mt.is_maintenance(lines):
            return False

        print("")
        print(f"  [{WARN}] The server is in maintenance -- waiting it out, "
              f"and pressing LAM MOI only when its clock runs out")
        if frame is not None:
            save_screenshot(frame, "MAINTENANCE")

        started = time.time()
        presses = 0
        while time.time() - started < mt.MAX_HOLD_S:
            left = mt.seconds_left(lines)
            if left is None:
                logger.warning("maintenance: notice up, no readable clock -- "
                               "looking again in %.0fmin",
                               mt.BLIND_WAIT_S / 60)
                self._sleep_until_woken(mt.BLIND_WAIT_S, "server maintenance")
            elif left > mt.PRESS_WITHIN_S:
                nap = min(left - mt.PRESS_WITHIN_S,
                          random.uniform(*mt.POLL_S))
                logger.info("maintenance: %.0fmin left on its clock, "
                            "waiting %.0fs", left / 60, nap)
                self._sleep_until_woken(nap, "server maintenance")
            else:
                # The clock is out. One press, then look.
                presses += 1
                logger.info("maintenance: the clock is out -- pressing LAM MOI "
                            "(press %d)", presses)
                print(f"  [{INFO}] Maintenance clock is out -- pressing LAM MOI")
                self._click_pct(*mt.REFRESH_AT, jitter_px=6)
                self._wait(random.uniform(4.0, 8.0))

            if not self.game.is_game_running():
                logger.info("maintenance: the client closed itself while we "
                            "waited -- letting the loop bring it back")
                self._view_is_world = False
                return True

            frame = self._grab()
            lines = mt.read_lines(frame, ocr_texts)
            if not mt.is_maintenance(lines):
                held = (time.time() - started) / 60.0
                print(f"  [{PASS}] Maintenance over after {held:.0f}min "
                      f"({presses} refresh press(es)) -- back to work")
                logger.info("maintenance: over after %.0fmin, %d press(es)",
                            held, presses)
                self._view_is_world = False
                return True

        logger.warning("maintenance: still up after %.0fmin -- giving the loop "
                       "back its turn", mt.MAX_HOLD_S / 60)
        self._view_is_world = False
        return True

    def _harvest_city_before_quit(self):
        """Tap the resource bubbles in the city, on the way out of the client.

        The operator's call, 2026-09-14: collect the city's production -- the
        four common resources and the KvK-only crystal -- and do it only
        before quitting, when the flow is already back in the city.

        Detection and its measurements live in rok_farm/city_harvest.py.

        ONE TAP, THEN LOOK AGAIN. The first version tapped every bubble found
        on a single frame, one after another. Live 2026-09-14, three exits,
        the same 20 spots each time, and after two of them something was
        covering the game when the mail check looked: at 01:02 the view button
        template scored 0.000 (0.841 at the next exit), and the 01:52 frame
        shows the road plot's info panel over the city. Taps were landing
        where a bubble had been, because ONE TAP TAKES EVERY BUBBLE OF ITS
        KIND. Measured on the first six exits with per-tap logging (2026-09-14
        02:53-06:04): 116 bubbles in 29 taps -- 20 in 5 five times, 16 in 4
        once. Three times a collect animation hid a neighbour for one look and
        shifted a count between two taps without changing the total. The old
        sweep spent fifteen of its twenty taps on bare ground every exit.

        So every tap is followed by a fresh frame, and:
          * anything covering the game stops the harvest on the spot. Dim
            ratio over the saved frames: 23 city views, 18 of them with 18-20
            bubbles showing, 1.04-1.24; the mail panel 2.40; the road panel
            5.18; MODAL_RATIO_MIN is 1.8. The panel goes to _dismiss_modal,
            one try, and the ALT+F4 that follows closes it if that fails;
          * no spot is tapped twice. A bubble still there after its tap and a
            second look is logged and left for the next exit -- one a tap did
            not take is more likely a wrong detection than bad luck.

        The next target is one of the few nearest the last tap (pick_next).
        """
        from collections import Counter

        from rok_farm.city_harvest import (HARVEST_BURST_GAP,
                                           HARVEST_MAX_CLICKS,
                                           HARVEST_MAX_SURVIVOR_RUN,
                                           load_harvest_templates, pick_next,
                                           still_there, untapped)
        from rok_farm.screenshots import save_screenshot

        templates = getattr(self, "_harvest_templates", None)
        if templates is None:
            templates = load_harvest_templates()
            self._harvest_templates = templates
        if not templates:
            logger.warning("harvest: no templates in templates/city -- skipped")
            return

        if self._on_world_map():
            # Live 2026-09-14 13:25: a return-to-city toggle had taken the
            # view OUT of the city, and this looked for bubbles on the world
            # map. It found none; nothing promised it never would.
            print(f"  [{WARN}] Harvest: on the world map, not in the city -- skipped")
            logger.warning("harvest: on the world map, not in the city -- skipped")
            return

        # The mine flow has refused to click at a game that is not in front
        # since 2026-08-19; this burst of taps was the last one still doing it.
        # 2026-09-16 14:26: twenty taps, nothing collected, the count drifting
        # 19-20 the whole time because bubbles kept appearing -- the game had
        # gone behind the operator's editor and every tap landed in THAT.
        if not self._ensure_game_focused("city harvest"):
            print(f"  [{WARN}] Harvest: the game is not in front -- skipped "
                  f"rather than tapping into whatever is")
            logger.warning("harvest: the game never took the foreground -- skipped")
            return

        frame, ratio, bubbles = self._harvest_look(templates)
        if frame is None:
            return
        if bubbles is None:
            logger.info("harvest: something already covers the city "
                        "(dim %.2f) -- skipped", ratio)
            return
        if not bubbles:
            print(f"  [{INFO}] Harvest: nothing to collect")
            logger.info("harvest: no bubbles on screen")
            return

        kinds = dict(Counter(b.kind for b in bubbles))
        print(f"  [{INFO}] Harvest: {len(bubbles)} bubble(s) {kinds}")
        logger.info("harvest: %d bubble(s) %s", len(bubbles), kinds)

        fh, fw = frame.shape[:2]
        tapped = []
        survivors = []
        in_a_row = 0

        # One tap per kind, in a burst, before looking again. Every click this
        # bot has ever sent waited for a fresh frame first, which is why not
        # one of 4,156 measured gaps was under a second while a person
        # collecting a city empties it in a few. Taking one kind does not move
        # another's bubbles, so these positions are all still good when their
        # turn comes -- unlike the old sweep, which tapped all twenty spots and
        # found fifteen of them bare.
        first = {}
        for b in bubbles:
            first.setdefault(b.kind, b)
        burst = list(first.values())
        random.shuffle(burst)
        for b in burst:
            self._click_pct(b.x / fw, b.y / fh, jitter_px=4)
            tapped.append(b)
            time.sleep(random.uniform(*HARVEST_BURST_GAP))
            # A tap that finds bare ground opens the plot's panel, and the
            # rest of a blind burst would then be clicking buttons on it.
            # This costs a frame grab and two means, not a template pass.
            frame, ratio, covered = self._harvest_cover()
            if covered:
                logger.info("harvest: the burst stopped after %d tap(s) -- "
                            "something covers the city (dim %.2f)",
                            len(tapped), ratio)
                self._harvest_covered(frame, ratio, tapped)
                return
        logger.info("harvest: burst of %d tap(s), one per kind: %s",
                    len(burst), ", ".join(b.kind for b in burst))

        time.sleep(random.uniform(0.6, 1.2))
        frame, ratio, now = self._harvest_look(templates)
        if frame is None:
            logger.info("harvest: no frame after the burst -- stopping")
            return
        if now is None:
            self._harvest_covered(frame, ratio, tapped)
            return
        logger.info("harvest: after the burst %d bubble(s) left of %d",
                    len(now), len(bubbles))
        if all(still_there(now, t) is not None for t in tapped):
            # Five taps, one per kind, and every single one still sitting
            # there. That is not bad luck; the clicks are not reaching the
            # game or the bubbles were never there.
            print(f"  [{WARN}] Harvest: the burst took nothing -- stopping")
            logger.warning("harvest: the burst of %d took nothing -- stopping",
                           len(tapped))
            save_screenshot(frame, "HARVEST_TAKES_NOTHING")
            return
        bubbles = now

        # Anything the burst missed goes back through the careful path.
        while len(tapped) < HARVEST_MAX_CLICKS:
            fresh = untapped(bubbles, tapped)
            if not fresh:
                break
            target = pick_next(fresh, tapped[-1] if tapped else None, random)
            self._click_pct(target.x / fw, target.y / fh, jitter_px=4)
            tapped.append(target)
            time.sleep(random.uniform(0.6, 1.2))

            frame, ratio, now = self._harvest_look(templates)
            if now is not None and still_there(now, target) is not None:
                # A bubble takes a moment to go. Look once more before
                # calling this one a survivor.
                time.sleep(random.uniform(0.5, 0.9))
                frame, ratio, now = self._harvest_look(templates)
            if frame is None:
                logger.info("harvest: no frame after tap %d -- stopping",
                            len(tapped))
                return
            if now is None:
                self._harvest_covered(frame, ratio, tapped)
                return

            here = still_there(now, target)
            if here is not None:
                survivors.append(here)
                in_a_row += 1
            else:
                in_a_row = 0
            logger.info("harvest: tap %d %s at (%d,%d): %d -> %d on screen%s",
                        len(tapped), target.kind, target.x, target.y,
                        len(bubbles), len(now),
                        ", and it is still there" if here is not None else "")
            bubbles = now

            # Taps that take nothing, over and over, are not bad luck. Either
            # the clicks are not reaching the game or the bubbles are not
            # really there -- and both are reasons to stop, not to keep
            # drumming on the same city.
            if in_a_row >= HARVEST_MAX_SURVIVOR_RUN:
                print(f"  [{WARN}] Harvest: {in_a_row} taps in a row took "
                      f"nothing -- stopping")
                logger.warning("harvest: %d taps in a row took nothing after "
                               "%d taps -- stopping", in_a_row, len(tapped))
                save_screenshot(frame, "HARVEST_TAKES_NOTHING")
                return

        logger.info("harvest: tapped %d, %d still on screen", len(tapped),
                    len(bubbles))
        if survivors and not getattr(self, "_harvest_leftover_saved", False):
            self._harvest_leftover_saved = True
            save_screenshot(frame, "HARVEST_LEFTOVER")

    def _harvest_cover(self):
        """Is something covering the city? (frame, ratio, covered).

        The burst needs this between taps and cannot afford the template pass
        that _harvest_look does -- the whole point is clicks under a second
        apart. A dim ratio is two means over a frame the capture thread
        already has: microseconds, and it is the signal that separates a city
        view (1.04-1.24 over 23 frames) from the mail panel (2.40) or the road
        plot's panel (5.18).
        """
        from rok_farm.state_probe import dim_ratio

        frame = self._grab()
        if frame is None:
            return None, 0.0, True
        ratio = dim_ratio(frame)
        return frame, ratio, ratio >= MODAL_RATIO_MIN

    def _harvest_look(self, templates):
        """A fresh frame as (frame, dim ratio, bubbles).

        bubbles is None when there is no frame or something covers the game --
        a covered city is not an empty one, and nothing on it may be tapped.
        """
        from rok_farm.city_harvest import find_harvest_bubbles
        from rok_farm.state_probe import dim_ratio

        frame = self._grab()
        if frame is None:
            return None, 0.0, None
        ratio = dim_ratio(frame)
        if ratio >= MODAL_RATIO_MIN:
            return frame, ratio, None
        return frame, ratio, find_harvest_bubbles(frame, templates)

    def _harvest_covered(self, frame, ratio, tapped):
        """A tap opened something. Stop, keep the evidence, try to close it."""
        from rok_farm.screenshots import save_screenshot

        last = tapped[-1]
        print(f"  [{WARN}] Harvest: tap {len(tapped)} opened a panel -- stopping")
        logger.warning("harvest: tap %d (%s at %d,%d) left the game covered, "
                       "dim %.2f -- stopping", len(tapped), last.kind, last.x,
                       last.y, ratio)
        if not getattr(self, "_harvest_panel_saved", False):
            self._harvest_panel_saved = True
            save_screenshot(frame, "HARVEST_PANEL_OPEN")
        closed = self._dismiss_modal()
        logger.info("harvest: panel %s", "closed" if closed
                    else "still open, ALT+F4 will take it")

    def _check_panels_before_quit(self):
        """City harvest, then mail -- and only on the way OUT of the client.

        Harvest goes FIRST because it needs the plain city view and mail opens
        a panel over it.

        This used to run during the city idle and was taken out because it
        opens a panel, and a panel that fails to close strands the bot in a
        screen no step knows how to leave. That reasoning is sound everywhere
        except here: the next thing this code does is ALT+F4, which closes the
        window whatever panel is open, and the client comes back with none. It
        is also when a player would do it -- you read your mail before you log
        off, not in the middle of a march.

        Alliance gifts were here for about an hour on 2026-09-13 and the
        action was deleted the same day, on its own record: 80 calls, 25 of
        them opening the panel, and zero gifts collected across the entire
        log. Nothing on the benefit side of the scale, so there was nothing to
        weigh the exposure against.

        act_mail skips when the mail button has no red badge, so this opens
        nothing unless something is there. Whether mail itself survives is an
        open question -- see the note in act_mail, which has never once got
        past the panel to a letter.
        """
        try:
            self._harvest_city_before_quit()
        except Exception:
            # Never let a nicety stop the quit.
            logger.warning("harvest before quit failed", exc_info=True)

        look, why = self._mail_worth_opening()
        logger.info("mail check: %s -> %s", why, "OPEN" if look else "skip")
        print(f"  [{INFO}] Mail: {why} -- {'opening' if look else 'leaving it'}")
        if not look:
            return

        for job in ["mail"]:
            try:
                self._actions.do(job)
            except Exception:
                # Never let a nicety stop the quit. The wait that follows is
                # the real work and the client is about to be closed anyway.
                logger.warning("%s check before quit failed", job,
                               exc_info=True)
        self._mail_rebaseline_after_read()

    def _mail_rebaseline_after_read(self):
        """Take the baseline from the badge AFTER the farm has read the mail.

        The check counts the badge before deciding to open, so the baseline it
        leaves behind is the pre-read number. Live 2026-09-14: 48 before the
        farm read two tabs at 02:53, 39 at the next exit -- which the check
        called "badge fell, somebody has read it" and skipped without doing
        the arithmetic at all. Any mail that arrived in between was invisible
        for that exit. The operator's rule counts from a read mailbox, so the
        count starts from one.

        If the number does not read now, or the panel is still covering the
        game, the pre-read baseline stays -- and the next fall is at least put
        down to the right reader.
        """
        self._mail_read_by_farm = True
        time.sleep(random.uniform(0.6, 1.0))
        frame = self._grab()
        if getattr(frame, "shape", None) is not None:
            from rok_farm.state_probe import dim_ratio
            if dim_ratio(frame) >= MODAL_RATIO_MIN:
                logger.info("mail: still covered after reading; baseline "
                            "stays %s", self._mail_last_count)
                return
        count = mail_badge_count(frame) if frame is not None else None
        if count is None:
            logger.info("mail: badge after reading did not read; baseline "
                        "stays %s", self._mail_last_count)
            return
        logger.info("mail: badge %s -> %s after reading, re-baselining",
                    self._mail_last_count, count)
        self._mail_last_count = count
        self._mail_last_gathers = getattr(self, "_gathers_started", 0)

    def _mail_badge_visible(self, frame) -> bool:
        """Is there any badge-red blob on the mail button at all?

        The boolean half of the mail button reading, for when the number does
        not read. Errors count as visible, so a broken check falls back to the
        old open-if-red behaviour instead of silently never reading mail.
        """
        try:
            from anti_detection.player_actions import _btn_has_badge
            return bool(_btn_has_badge(frame, "mail"))
        except Exception:
            return True

    def _mail_worth_opening(self) -> tuple[bool, str]:
        """Is there MORE mail than the farm's own marches can account for?

        The badge is a count, and most of what lands in it is the farm's own
        doing: every gather sends back one "Bao cao thu gom". So "is there
        mail" is the wrong question -- there always is -- and asking it is why
        the old rule opened the mailbox on all 125 calls it was given.

        The operator's rule, 2026-09-13: compare how much the badge GREW
        against how many gathers finished in the same stretch, and open when
        the difference is bigger than routine. Their worked example -- badge 63
        against about 40 returns, 23 unexplained -- was plainly worth a look.

        Reading the number is new and measured: mail_badge_count got it right
        on every frame that has a visible badge, including a night frame where
        the old red mask missed the badge entirely.
        """
        frame = self._grab()
        if getattr(frame, "shape", None) is not None:
            from rok_farm.state_probe import dim_ratio
            cover = dim_ratio(frame)
            if cover >= MODAL_RATIO_MIN:
                # Live 2026-09-14 01:52: a harvest tap had opened the road
                # plot's panel and this said "no badge on the mail button".
                # The badge was underneath, not gone. Baseline untouched.
                return False, (f"something covers the game (dim {cover:.2f}), "
                               "the badge cannot be seen")
        count = mail_badge_count(frame) if frame is not None else None
        # Marches SENT, not gathers finished -- and between two checks those
        # are the same number. The check only runs on the way out, and the
        # farm only leaves with the queue full: every one of the 13 checks in
        # the log up to 2026-09-14 07:21 came right after a 5/5 reading.
        # Returned = sent + occupancy before - occupancy after = sent + 5 - 5.
        # A quit with a part-empty queue would break that; none has happened.
        done = getattr(self, "_gathers_started", 0)

        prev, prev_done = self._mail_last_count, self._mail_last_gathers
        read_by_farm = getattr(self, "_mail_read_by_farm", False)
        if count is not None:
            self._mail_last_count = count
            self._mail_last_gathers = done
            self._mail_read_by_farm = False

        if count is None:
            # None has meant two different things, and the log said the wrong
            # one. Live 2026-09-14 01:02: "badge unreadable, falling back" --
            # then act_mail's own check found red_px=0, no badge it could see.
            # Nothing was unreadable, and MAIL_SURPRISE is meant to be tuned
            # from exactly these lines. (That exit was first put down to an
            # empty mailbox. The view-button template scored 0.000 there
            # against 0.841 at the next exit, and the exit after that saved a
            # frame with a panel over the city, so covered is likelier. A
            # panel that dims the game is now caught above.)
            if not self._mail_badge_visible(frame):
                # Empty mailbox, or something covering the button without
                # dimming the game. Save the first such frame so the two can
                # be told apart. Baseline untouched: guessing "0" while the
                # button is covered would fake a jump later.
                if not getattr(self, "_mail_nobadge_frame_saved", False):
                    self._mail_nobadge_frame_saved = True
                    if getattr(frame, "shape", None) is not None:
                        try:
                            from rok_farm.screenshots import save_screenshot
                            save_screenshot(frame, "MAIL_BUTTON_NO_BADGE")
                        except Exception:
                            logger.debug("could not save the no-badge frame",
                                         exc_info=True)
                return False, ("no badge on the mail button (empty mailbox, "
                               "or the button is covered)")
            # Cannot count is not the same as nothing there. Fall back to the
            # old question so a number that does not read never silently stops
            # the mail being read at all.
            return True, ("badge present but its number did not read, "
                          "falling back to open-if-red")
        if prev is None:
            return True, f"first look this session (badge {count})"
        if count < prev:
            who = "the farm read it" if read_by_farm else "somebody has read it"
            return False, f"badge fell {prev}->{count}; {who}, re-baselining"

        grew = count - prev
        explained = max(0, done - prev_done)
        surprise = grew - explained
        detail = (f"badge {prev}->{count} (+{grew}), {explained} gather(s) "
                  f"finished, {surprise} unexplained vs {MAIL_SURPRISE}")
        return (surprise >= MAIL_SURPRISE), detail

    def _sleep_until_woken(self, seconds: float, reason: str) -> bool:
        """Sleep, but stop early if the remote control asks.

        The alt-tab wait was a single time.sleep, which nothing could reach
        into. The player watches the same account on their phone and often
        knows troops are home before the estimate does; the only way to act on
        that was to stop the farm and start it again, losing the march
        bookkeeping and paying for a client restart.

        Returns True if the full time elapsed, False if it was cut short.
        """
        deadline = time.time() + max(0.0, seconds)
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return True
            time.sleep(min(5.0, remaining))
            note = wake.consume()
            if note:
                waited = seconds - max(0.0, deadline - time.time())
                print(f"  [{INFO}] Woken {waited / 60:.1f}min into "
                      f"{seconds / 60:.1f}min ({reason}) -- {note}")
                logger.info("Wake request during %s after %.0fs of %.0fs",
                            reason, waited, seconds)
                return False

    def _quit_threshold_s(self) -> float:
        """How long a wait must be before closing the client pays for itself.

        Not a fixed number of minutes: the waits move with the game (a KvK
        deposit holds 30 gems and gathers for ~27min, an ordinary-map one holds
        10-20), while the cost of coming back does not. So the cost IS the
        threshold -- measured, not assumed: 78s at the median over 83 planned
        relaunches in the log, and re-measured as this run goes on.
        """
        seen = getattr(self, "_relaunch_overheads", None)
        overhead = (statistics.median(seen) if seen and len(seen) >= 3
                    else RELAUNCH_OVERHEAD_S)
        return max(WAIT_QUIT_FLOOR_S, overhead * WAIT_QUIT_FACTOR)

    def _note_relaunch_overhead(self, seconds: float):
        """File what the last quit+relaunch cost beyond the wait it covered.

        Outliers are dropped rather than averaged in: a wake request cuts a
        wait short (negative) and a launcher that hung is not the cost of a
        normal relaunch (the log's worst is 490s against a 78s median).
        """
        if seconds <= 0 or seconds > 300:
            return
        seen = getattr(self, "_relaunch_overheads", None)
        if seen is None:
            seen = self._relaunch_overheads = []
        seen.append(seconds)
        del seen[:-10]
        logger.info("relaunch cost %.0fs (median of %d: %.0fs) -> quit when a "
                    "wait beats %.0fs", seconds, len(seen),
                    statistics.median(seen), self._quit_threshold_s())

    def _may_quit_again(self) -> bool:
        """Has enough time passed since the last restart -- probably?

        The threshold beside this is pure arithmetic and cannot see that
        restarts have a shape of their own. It never changed, yet the gap
        between them drifted from 31 minutes to 8 over ten days, because the
        marches started coming home sooner and every wait cleared the bar.

        The first fix was a cap of three an hour. The operator asked whether a
        fixed number is itself recognisable, and it is: every busy hour would
        show exactly three restarts and never four, which is a flatter, more
        artificial line than the rhythm it replaced. So this is a chance, not
        a limit. It rises with the time since the last quit and reaches
        certainty at a target drawn fresh for each session, so short gaps
        happen occasionally and long ones usually -- with no edge anywhere for
        anyone to notice.
        """
        seen = getattr(self, "_quit_times", None)
        if not seen:
            return True
        target = getattr(self, "_quit_gap_target", None)
        if target is None:
            target = self._quit_gap_target = random.uniform(*QUIT_GAP_TARGET_S)
            logger.info("this session will aim for about %.0f min between "
                        "client restarts", target / 60)
        gap = time.time() - seen[-1]
        # Cubed, not linear. A linear chance fires far too early: with a
        # target of 20 minutes and a wait asking every 4, simulating a day
        # gave 61-82 restarts at a median gap of 8-12 minutes -- worse than
        # the fixed cap it replaced. The cube keeps early gaps unlikely
        # without ever forbidding them.
        chance = min(1.0, (gap / target) ** 3)
        if random.random() < chance:
            return True
        print(f"  [{INFO}] last restart was {gap / 60:.0f}min ago -- staying "
              f"in and alt-tabbing this wait instead")
        logger.info("quit spacing: %.0fmin since the last, %.0f%% chance "
                    "taken -- alt-tab instead", gap / 60, chance * 100)
        return False

    def _note_quit(self):
        seen = getattr(self, "_quit_times", None)
        if seen is None:
            seen = self._quit_times = []
        seen.append(time.time())

    def _window_check(self, planned_s: float = 0.0) -> bool:
        """May the account be online -- and stay online for planned_s more?

        Outside the window, or when the wait about to start would run past its
        end, the client is closed and the farm stops. rok_farm/run_window.py
        holds the 3,006-gem reclaim this exists to prevent; closing the client
        is the point, since a farm that merely stops leaves the account logged
        in.
        """
        from rok_farm import run_window

        left = run_window.seconds_left()
        if left > 0 and planned_s <= left:
            return True
        why = ("the run window is closed" if left <= 0 else
               f"the next wait ({planned_s / 60:.0f}min) runs past its end")
        print(f"\n  [{WARN}] Run window {run_window.window_label()}: {why} "
              f"-- closing the client and stopping")
        logger.warning("Run window %s: %s -- quitting the client and stopping",
                       run_window.window_label(), why)
        try:
            self.game.quit_game(self)
        except Exception:
            logger.warning("could not close the client at the window edge",
                           exc_info=True)
        return False

    def _phase_wait_return(self):
        """Phase 3: alt-tab out and wait for the 'troops returned' toast.

        The toast only fires while ROK is in the background, so we genuinely tab
        away and read it from the OS (no screen capture). Cap at MAX_MARCH_MINUTES;
        if nothing arrives we tab back and let the OCR queue check sort it out."""
        # No wait of any kind starts outside the window -- including the toast
        # vigil at the bottom, which has no estimate to check against and keeps
        # the client open while it listens.
        if not self._window_check():
            return

        # Decide HOW to wait from how long the wait is. The estimate comes from
        # the deploy panel, so this is a plan rather than a vigil.
        wait_s = self.seconds_until_first_return()
        if wait_s is not None:
            # Coming back 90s early only makes sense when the wait is longer
            # than 90s. Subtracting the margin from a 24-second gather gave
            # plan = 0, and with the "stay in the game" branch gone that became
            # "alt-tab out for 0.0min" -- tab out, tab straight back, reconcile,
            # compute an even shorter wait, repeat. Seen flickering three times
            # in twenty seconds at 16:50, which wastes the cycle and is a far
            # worse behavioural tell than sitting still would have been.
            # The floor is not a tuning knob: _tab_back() alone sleeps
            # uniform(1.5, 3.0) plus a warmup capped at 8s, so a tab cycle costs
            # up to ~11 seconds. Planning to stay out for less than that is all
            # overhead and no waiting. Capping at wait_s keeps a genuinely short
            # gather from being rounded UP past its own return.
            plan = (wait_s if wait_s <= WAIT_EARLY_MARGIN
                    else min(wait_s,
                             max(TAB_CYCLE_COST, wait_s - WAIT_EARLY_MARGIN)))
            before = self._detect_march_queue()

            # A wait is the farm's longest stretch of doing nothing, and the
            # alt-tab kind keeps the client OPEN throughout. Starting one that
            # outlives the window would hold the account online past the edge,
            # so stop here instead and let the day end clean.
            if not self._window_check(plan):
                return

            # Shorter than the tab cycle itself? Then tabbing is pure overhead:
            # it takes LONGER than the wait it is supposed to cover, and leaves
            # a burst of alt-tabs that no player produces. The floor above was
            # written for exactly this and does not reach it -- a wait under
            # WAIT_EARLY_MARGIN takes the first branch, where plan = wait_s with
            # no floor at all, which is how "alt-tab out for 0.0min" survived.
            # Nine of 112 waits in the log are under six seconds.
            if wait_s < TAB_CYCLE_COST:
                print(f"  [{INFO}] Troops home in ~{wait_s:.0f}s -- shorter "
                      f"than an alt-tab cycle, waiting where we are")
                logger.info("Wait %.0fs below tab cost %.0fs -- staying put",
                            wait_s, TAB_CYCLE_COST)
                self._sleep_until_woken(wait_s, "short wait in place")
                self._score_wait_prediction(before, wait_s, "in-place")
                return

            if plan > self._quit_threshold_s() and self._may_quit_again():
                print(f"  [{INFO}] Troops home in ~{wait_s / 60:.1f}min -- "
                      f"longer than the {self._quit_threshold_s() / 60:.1f}min "
                      f"a relaunch costs, quitting the client")
                logger.info("Computed wait %.0fs -> quit+relaunch "
                            "(threshold %.0fs)", plan, self._quit_threshold_s())
                # Only here. _restart_game is also the RECOVERY path, where the
                # client may be the thing that is broken, and poking a panel
                # into it would be the worst possible moment.
                self._check_panels_before_quit()
                self._note_quit()
                away = time.time()
                if self._restart_game(f"waiting {plan / 60:.0f}min for troops",
                                      extra_wait=plan):
                    self._note_relaunch_overhead(time.time() - away - plan)
                    self._view_is_world = False
                    self._score_wait_prediction(before, wait_s, "quit")
                    return
                print(f"  [{WARN}] Could not quit; falling back to alt-tab")
            else:
                print(f"  [{INFO}] Troops home in ~{wait_s / 60:.1f}min -- "
                      f"alt-tab out for {plan / 60:.1f}min")
                self._capture_paused = True
                self._tab_out()
                self._sleep_until_woken(plan, "alt-tab wait")
                self._capture_paused = False
                self._tab_back()
                self._view_is_world = False
                self._score_wait_prediction(before, wait_s, "alt-tab")
                return

        # No estimate available (panel unreadable, or a march predates this
        # feature): fall back to the toast vigil, which still works.
        print(f"  [{INFO}] Phase: alt-tab away, waiting for troops to return "
              f"(cap {MAX_MARCH_MINUTES}min)")
        self._notif.snapshot_baseline()
        # Stop grabbing the screen while we're tabbed out -- we only read OS
        # notifications during the wait. Resume before tabbing back so the frame
        # buffer is fresh for the queue check.
        self._capture_paused = True
        self._tab_out()

        start = time.time()
        cap = MAX_MARCH_MINUTES * 60
        returned = 0
        try:
            while time.time() - start < cap:
                time.sleep(random.uniform(4.0, 8.0))
                note = wake.consume()
                if note:
                    elapsed = (time.time() - start) / 60.0
                    print(f"  [{INFO}] Woken after {elapsed:.1f}min of waiting "
                          f"-- {note}")
                    logger.info("Wake request during toast vigil after %.1fmin",
                                elapsed)
                    break
                if self._notif.available:
                    n = self._notif.check_returned()
                    if n > 0:
                        returned += n
                        elapsed = (time.time() - start) / 60.0
                        print(f"  [{INFO}] Toast: {returned} troop(s) returned after {elapsed:.1f}min")
                        self.note_troops_returned(n)
                        # human reaction: notice the toast, then tab back
                        time.sleep(random.uniform(3.0, 20.0))
                        break
        finally:
            self._capture_paused = False

        if returned == 0:
            mins = (time.time() - start) / 60.0
            print(f"  [{WARN}] No return toast in {mins:.0f}min "
                  f"(notif {'on' if self._notif.available else 'OFF'}), "
                  f"tabbing back to check queue")

        self._tab_back()
        # View is uncertain after alt-tabbing back -> force a fresh detect next mine.
        self._view_is_world = False

        # Reconcile free slots so the next burst can start. OCR is authoritative;
        # without it, estimate from the toast count (>=1) so we never deadlock on
        # the full-queue branch.
        queue = self._detect_march_queue() if self.loop else None
        if queue:
            used, total = queue
            self.mines_completed = used
            print(f"  [{INFO}] After return: queue {used}/{total}")
        else:
            freed = returned if returned > 0 else 1
            self.mines_completed = max(0, self.mines_completed - freed)
            print(f"  [{INFO}] After return: no OCR read, assuming {freed} slot(s) "
                  f"freed -> counter {self.mines_completed}")

    def _score_wait_prediction(self, before, predicted_s, how: str):
        """Did the computed return time actually hold?

        This is the validation the strict "exactly one march outstanding" rule
        could never deliver -- with five slots that condition almost never
        occurs, so the prediction would have gone unchecked forever. Here the
        question is simpler and available EVERY cycle: we waited until troops
        were supposed to be home, so did the queue actually drop?

        Not purely observational any more: the badge reading taken here also
        retires marches that are already home (see below). The queue reading
        stays the authority either way.
        """
        # Give the client time to finish drawing. Scoring right after a
        # relaunch read an empty ROI and recorded "unreadable" for a wait that
        # had in fact worked perfectly -- 5/5 went to 1/5 eight seconds later.
        # A verification that runs before the thing it verifies is visible does
        # not measure the prediction, it measures the repaint.
        after = None
        for attempt in range(4):
            after = self._detect_march_queue()
            if after:
                break
            self._wait((2.5, 0.6))
        if not before or not after:
            logger.info("Wait check (%s): predicted %.0fmin, queue unreadable",
                        how, predicted_s / 60)
            return

        # Retire the marches this reading proves are home, before scoring.
        #
        # A march that came back EARLY is invisible to the clock -- its
        # estimate still sits in the future -- so the slot count is the only
        # thing that can retire it. Waking for march 1 and finding march 2 home
        # too has to skip the wait straight to march 3, or the next wait is
        # computed from a march that is already in the city.
        #
        # This reading cost four retries and a repaint wait; it is the freshest
        # badge the bot sees all cycle. Spending it on a log verdict alone left
        # reconciliation to the NEXT read, and badge OCR fails 42% of the time
        # (822 of 1932 reads in the log) -- so the stale record could survive
        # for several cycles.
        self.sync_open_marches(after[0])

        dropped = before[0] - after[0]
        # HOW MANY came home is the honest measure, not merely whether any did.
        # "ON TIME" cannot tell a tight estimate from a wildly long one: if the
        # prediction overshoots, troops are home early and the bot sleeps on,
        # and the log still says ON TIME. One slot freed means the wait ended
        # about when the first gather finished; several means we slept through
        # that many more, i.e. farm time thrown away.
        if dropped <= 0:
            verdict = "TOO EARLY"
        elif dropped == 1:
            verdict = "ON TIME"
        else:
            verdict = f"OVERSHOT by ~{dropped - 1}"
        print(f"  [{INFO}] Wait check: predicted {predicted_s / 60:.0f}min, "
              f"queue {before[0]}/{before[1]} -> {after[0]}/{after[1]} [{verdict}]")
        logger.info("Wait prediction %s: %.0fs, queue %d->%d, %s",
                    how, predicted_s, before[0], after[0], verdict)
