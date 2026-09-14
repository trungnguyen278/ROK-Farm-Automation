"""Burst rhythm: farm hard, then behave like a player between bursts.

Phase 1 is the march burst itself (see GemFlowMixin). Phase 2 drops back to the
city for light tasks, phase 3 alt-tabs out and waits for the Windows "troops
returned" toast -- which only fires while the game runs in the BACKGROUND, which
is why the wait is an alt-tab and not a game exit.
"""

from __future__ import annotations

import random
import time

from anti_detection.player_actions import mail_badge_count
from rok_farm.config import (MAIL_SURPRISE, MAX_MARCH_MINUTES,
                             MODAL_RATIO_MIN, WAIT_EARLY_MARGIN,
                             WAIT_QUIT_MINUTES)
from rok_farm import wake
from rok_farm.logging_setup import INFO, WARN, logger

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

        from rok_farm.city_harvest import (HARVEST_MAX_CLICKS,
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
            logger.info("harvest: tap %d %s at (%d,%d): %d -> %d on screen%s",
                        len(tapped), target.kind, target.x, target.y,
                        len(bubbles), len(now),
                        ", and it is still there" if here is not None else "")
            bubbles = now

        logger.info("harvest: tapped %d, %d still on screen", len(tapped),
                    len(bubbles))
        if survivors and not getattr(self, "_harvest_leftover_saved", False):
            self._harvest_leftover_saved = True
            save_screenshot(frame, "HARVEST_LEFTOVER")

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

            if plan > WAIT_QUIT_MINUTES * 60:
                print(f"  [{INFO}] Troops home in ~{wait_s / 60:.0f}min -- "
                      f"too long to sit here, quitting the client")
                logger.info("Computed wait %.0fs -> quit+relaunch", plan)
                # Only here. _restart_game is also the RECOVERY path, where the
                # client may be the thing that is broken, and poking a panel
                # into it would be the worst possible moment.
                self._check_panels_before_quit()
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
