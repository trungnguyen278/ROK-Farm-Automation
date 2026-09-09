"""Burst rhythm: farm hard, then behave like a player between bursts.

Phase 1 is the march burst itself (see GemFlowMixin). Phase 2 drops back to the
city for light tasks, phase 3 alt-tabs out and waits for the Windows "troops
returned" toast -- which only fires while the game runs in the BACKGROUND, which
is why the wait is an alt-tab and not a game exit.
"""

from __future__ import annotations

import random
import time

from rok_farm.config import (MAX_MARCH_MINUTES, WAIT_EARLY_MARGIN,
                             WAIT_QUIT_MINUTES)
from rok_farm.logging_setup import INFO, WARN, logger

# What one alt-tab out-and-back costs before any waiting happens: _tab_back()
# sleeps uniform(1.5, 3.0) plus a warmup capped at 8s. Staying out for less
# than this is pure overhead, so it is the floor on a planned wait.
TAB_CYCLE_COST = 20.0



class PhasesMixin:
    """Between-burst behaviour. Mixed into GemFarmRunner."""

    def _tab_out(self):
        """Alt-tab out of the game and stop the HID idle-jitter. No fixed wait --
        caller decides how long to stay out (e.g. wait for a return toast)."""
        self.cmd.send("IDLE", "1")
        hold = random.randint(50, 120)
        self.cmd.send("COMBO", "ALT", "TAB", hold)

    def _tab_away(self):
        raw = random.lognormvariate(3.8, 0.7)
        away = max(5.0, min(600.0, raw))
        logger.info("tab away %.0fs", away)
        print(f"  [{INFO}] Alt-tab away {away:.0f}s")
        self._tab_out()
        time.sleep(away)

    def _tab_back(self):
        hold = random.randint(50, 120)
        self.cmd.send("COMBO", "ALT", "TAB", hold)
        self.cmd.send("IDLE", "0")
        time.sleep(random.uniform(1.5, 3.0))
        # ALT+TAB is a guess about window order, not a guarantee. Verify it
        # actually landed on the game: WGC capture would keep showing a healthy
        # game frame either way, so an unnoticed miss means every click for the
        # rest of the burst goes to whatever window is really in front.
        self._ensure_game_focused("after alt-tab back")
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

    def _check_session(self) -> str | None:
        # No active-window gate: the operator runs this when they choose, and a
        # bot that refuses to start before 09:00 is a scheduling nuisance, not a
        # safety feature. The realism that mattered here was CLOSING the client
        # between sessions, and that lives in the long-break roll instead (see
        # SessionManager.get_break_duration).
        if self.session.should_take_break():
            return "break"
        return None

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

    def _phase_wait_return(self):
        """Phase 3: alt-tab out and wait for the 'troops returned' toast.

        The toast only fires while ROK is in the background, so we genuinely tab
        away and read it from the OS (no screen capture). Cap at MAX_MARCH_MINUTES;
        if nothing arrives we tab back and let the OCR queue check sort it out."""
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
            if plan > WAIT_QUIT_MINUTES * 60:
                print(f"  [{INFO}] Troops home in ~{wait_s / 60:.0f}min -- "
                      f"too long to sit here, quitting the client")
                logger.info("Computed wait %.0fs -> quit+relaunch", plan)
                if self._restart_game(f"waiting {plan / 60:.0f}min for troops",
                                      extra_wait=plan):
                    self._view_is_world = False
                    self._score_wait_prediction(before, wait_s, "quit")
                    return
                print(f"  [{WARN}] Could not quit; falling back to alt-tab")
            else:
                print(f"  [{INFO}] Troops home in ~{wait_s / 60:.1f}min -- "
                      f"alt-tab out for {plan / 60:.1f}min")
                self._capture_paused = True
                self._tab_out()
                time.sleep(plan)
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
