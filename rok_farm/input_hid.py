"""HID input: pointer moves, clicks, drags, scrolls -- all via the ESP32.

Every coordinate that reaches the ESP32 goes through here, so the window clamp
and the no-click zones are enforced in one place.
"""

from __future__ import annotations

import random
import time
from contextlib import contextmanager

from capture.screen_info import (get_cursor_pos, get_screen_resolution,
                                 screen_to_hid)
from vision.template_matcher import Match

from rok_farm.config import DELAY_AFTER_CLICK
from rok_farm.logging_setup import WARN, logger


class HidInputMixin:
    """Mouse/keyboard output. Mixed into GemFarmRunner."""

    # --- Anti-detection helpers ---

    def _wait(self, spec, variance: float = 0.0) -> float:
        if isinstance(spec, tuple):
            center, spread = spec[0], spec[1] if len(spec) > 1 else spec[0] * 0.15
        else:
            center = float(spec)
            spread = center * 0.15
        if spread > 0:
            sigma = spread / center if center > 0 else 0.15
        else:
            sigma = 0.12
        raw = random.lognormvariate(0, sigma)
        actual = max(0.05, center * raw)
        time.sleep(actual)
        return actual

    @contextmanager
    def _pointer_scope(self, rect: dict):
        """Aim the pointer at another window for the duration of the block.

        Every click is clamped to `self.win` (the game client) and screened
        against the game's no-click zones. When we have to click something that
        is NOT the game -- the launcher's Play button, an exit confirmation --
        both of those would either clamp the click back inside a stale game rect
        or reject it outright, so swap the rect and drop the zones here.
        """
        prev_win = self.win
        had_zones = "_NO_CLICK_ZONES" in self.__dict__
        prev_zones = self.__dict__.get("_NO_CLICK_ZONES")
        self.win = rect
        self._NO_CLICK_ZONES = []
        try:
            yield
        finally:
            self.win = prev_win
            if had_zones:
                self._NO_CLICK_ZONES = prev_zones
            else:
                del self._NO_CLICK_ZONES

    # Set by _muscle_memory(); None means the normal deliberate pacing.
    _mm_speed: float | None = None

    @contextmanager
    def _muscle_memory(self, speed: float = 3.0):
        """Click like a player who knows exactly where the button is.

        The deploy chain (gather -> new troop -> march) is three buttons at
        FIXED positions that a gem farmer hits from memory. Paying the normal
        "find it, recognise it, then click" cost there is not just slow, it is
        WRONG: measured 3.6 s then 2.3 s between clicks, where a practised
        player takes ~0.5-0.8 s per beat. Being slowest exactly where humans are
        fastest is itself a tell, so this trims the perceive pause and speeds
        the pointer travel, while keeping the position jitter, the hold-time
        variation and the occasional fumble that make the motion human.
        """
        had = "_mm_speed" in self.__dict__
        prev = self.__dict__.get("_mm_speed")
        self._mm_speed = speed
        try:
            yield
        finally:
            if had:
                self._mm_speed = prev
            else:
                del self._mm_speed

    def _probe_moveto(self) -> bool:
        """Send MOVETO and verify cursor arrives near the expected screen position.

        Probes at the center of the game window so the cursor stays in-place
        rather than jumping to an arbitrary screen location.
        """
        if not self.win:
            return False
        res_w, res_h = get_screen_resolution()
        target_sx = self.win["left"] + self.win["width"] // 2
        target_sy = self.win["top"] + self.win["height"] // 2
        target_hid_x = int(target_sx * 32767 / res_w)
        target_hid_y = int(target_sy * 32767 / res_h)
        if not self.cmd.send("MOVETO", target_hid_x, target_hid_y):
            return False
        time.sleep(0.4)
        cx, cy = get_cursor_pos()
        err = max(abs(cx - target_sx), abs(cy - target_sy))
        ok = err < 80
        if not ok:
            logger.warning("MOVETO inaccurate: cursor=(%d,%d) expected=(%d,%d) err=%d",
                           cx, cy, target_sx, target_sy, err)
        return ok

    def _calibrate_mouse_scale(self) -> float:
        """Measure Windows mouse acceleration by sending known MOVE deltas."""
        scales = []
        for test_dx in [80, -80, 120, -120]:
            time.sleep(0.15)
            bx, _ = get_cursor_pos()
            self.cmd.send("MOVE", test_dx, 0, 50)
            time.sleep(0.15)
            ax, _ = get_cursor_pos()
            actual = ax - bx
            if abs(test_dx) > 5 and abs(actual) > 5:
                scales.append(actual / test_dx)
        for test_dy in [80, -80]:
            time.sleep(0.15)
            _, by = get_cursor_pos()
            self.cmd.send("MOVE", 0, test_dy, 50)
            time.sleep(0.15)
            _, ay = get_cursor_pos()
            actual = ay - by
            if abs(test_dy) > 5 and abs(actual) > 5:
                scales.append(actual / test_dy)
        if scales:
            avg = sum(abs(s) for s in scales) / len(scales)
            return max(0.5, min(3.0, avg))
        return 1.0

    def _restore_cursor_to_window(self):
        """Move cursor back to game window center using relative MOVE with correction."""
        tx = self.win["left"] + self.win["width"] // 2
        ty = self.win["top"] + self.win["height"] // 2
        sc = self._mouse_scale
        for _ in range(5):
            cx, cy = get_cursor_pos()
            dx, dy = tx - cx, ty - cy
            if abs(dx) <= 5 and abs(dy) <= 5:
                break
            send_dx = int(dx / sc) if sc != 1.0 else dx
            send_dy = int(dy / sc) if sc != 1.0 else dy
            dur = max(abs(send_dx), abs(send_dy)) * 2
            self.cmd.send("MOVE", send_dx, send_dy, max(dur, 50))
            time.sleep(0.15)

    def _path_to_hid(self, path: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
        """Convert screen-coord path to HID waypoints, clamped to game window."""
        waypoints = []
        for px, py, ms in path:
            cx, cy = self._clamp_to_window(int(px), int(py))
            hx, hy = screen_to_hid(cx, cy)
            waypoints.append((hx, hy, ms))
        return waypoints

    def _send_path(self, waypoints: list[tuple[int, int, int]], drag: bool = False) -> bool:
        """Send path via PATH commands (ESP32 hardware timing) with fallback."""
        ok = self.cmd.send_path(waypoints, drag=drag)
        if ok:
            return True
        # Fallback: send one by one
        logger.debug("PATH command failed, falling back to sequential MOVETO")
        if drag:
            self.cmd.send("MDOWN", "L")
            time.sleep(0.015)
        for hx, hy, ms in waypoints:
            self.cmd.send("MOVETO", hx, hy)
            time.sleep(max(0.004, ms / 1000.0))
        if drag:
            time.sleep(0.015)
            self.cmd.send("MUP", "L")
        return True

    def _moveto(self, sx: int, sy: int) -> bool:
        sx, sy = self._clamp_to_window(sx, sy)
        cur_x, cur_y = get_cursor_pos()
        dx = sx - cur_x
        dy = sy - cur_y
        if abs(dx) < 3 and abs(dy) < 3:
            return True

        # The humanizer already shapes the velocity envelope (accel -> cruise
        # -> decel); don't re-time the path here or it distorts that profile.
        path = self.humanizer.humanize_move(cur_x, cur_y, sx, sy)

        if self._has_moveto:
            waypoints = self._path_to_hid([(cur_x, cur_y, 0), *path])
            self._send_path(waypoints)
            hx, hy = screen_to_hid(sx, sy)
            self.cmd.send("MOVETO", hx, hy)
        else:
            sc = self._mouse_scale
            mm = self._mm_speed
            for px, py, step_ms in path:
                ax, ay = get_cursor_pos()
                mdx = px - ax
                mdy = py - ay
                send_dx = int(mdx / sc) if sc != 1.0 else int(mdx)
                send_dy = int(mdy / sc) if sc != 1.0 else int(mdy)
                if abs(send_dx) > 0 or abs(send_dy) > 0:
                    dur = max(step_ms, max(abs(send_dx), abs(send_dy)))
                    if mm:
                        # A practised flick covers the same curve faster; the
                        # humanizer's shape is kept, only the clock is scaled.
                        dur = max(3, int(dur / mm))
                    self.cmd.send("MOVE", send_dx, send_dy, dur)
            for _ in range(4):
                time.sleep(0.03)
                ax, ay = get_cursor_pos()
                err_x, err_y = sx - ax, sy - ay
                if abs(err_x) <= 3 and abs(err_y) <= 3:
                    break
                send_ex = int(err_x / sc) if sc != 1.0 else err_x
                send_ey = int(err_y / sc) if sc != 1.0 else err_y
                dur = max(abs(send_ex), abs(send_ey)) * 2
                self.cmd.send("MOVE", send_ex, send_ey, max(dur, 30))
        return True

    _NO_CLICK_ZONES = [
        (0.0, 0.0, 0.70, 0.13),
        (0.0, 0.80, 0.45, 1.0),
    ]

    def _in_no_click_zone(self, sx: int, sy: int) -> bool:
        rx = (sx - self.win["left"]) / self.win["width"]
        ry = (sy - self.win["top"]) / self.win["height"]
        in_zone = False
        for x1, y1, x2, y2 in self._NO_CLICK_ZONES:
            if x1 <= rx <= x2 and y1 <= ry <= y2:
                in_zone = True
                break
        if in_zone and random.random() < 0.05:
            return False
        return in_zone

    def _click(self, sx: int, sy: int, hold_ms: int = 0) -> bool:
        ox, oy, h = self.humanizer.humanize_click(sx, sy)
        sx += ox
        sy += oy
        if self._in_no_click_zone(sx, sy):
            logger.debug("Click blocked: (%d,%d) in no-click zone", sx, sy)
            return False
        if not self._moveto(sx, sy):
            return False
        if self._mm_speed:
            # Known button: no visual search, just the reaction floor. Still
            # jittered -- a human is fast here, not metronomic.
            time.sleep(random.uniform(0.04, 0.13))
        else:
            perceive = random.lognormvariate(-0.5, 0.4)
            time.sleep(max(0.15, min(2.0, perceive)))
        if random.random() < 0.015:
            miss_dx = random.randint(-40, 40)
            miss_dy = random.randint(-30, 30)
            self._moveto(sx + miss_dx, sy + miss_dy)
            time.sleep(random.uniform(0.05, 0.15))
            self.cmd.send("CLICK", "L", random.randint(30, 60))
            time.sleep(random.uniform(0.2, 0.6))
            self._moveto(sx, sy)
            time.sleep(random.uniform(0.1, 0.3))
        if hold_ms <= 0:
            hold_ms = h
            if random.random() < 0.08:
                hold_ms = random.randint(200, 400)
        # Log where the click actually lands vs. the target -- the cursor's real
        # position IS the click point, so `err` exposes relative-MOVE drift.
        acx, acy = get_cursor_pos()
        err = max(abs(acx - sx), abs(acy - sy))
        tag = "" if err <= 8 else f"  [{WARN}] OFF by {err}px"
        logger.debug("click target=(%d,%d) cursor=(%d,%d) err=%dpx%s",
                     sx, sy, acx, acy, err, tag)
        ok = self.cmd.send("CLICK", "L", hold_ms)
        self.session.record_action()
        if self._mm_speed:
            self._wait((0.06, 0.03))
        else:
            self._wait(DELAY_AFTER_CLICK)
        return ok

    def _click_match(self, match: Match) -> bool:
        """Click where a template matched -- the one place that does so.

        A fixed button that suddenly matches far from everywhere it has ever
        been is a false positive, not a moved button, so it is refused here
        rather than clicked. See rok_farm/button_registry.py.
        """
        sx, sy = self._screen_xy(*match.center)

        registry = getattr(self, "buttons", None)
        if registry is not None:
            pct = registry.to_window_pct(sx, sy, self.win)
            if pct is not None:
                ok, why = registry.check(match.name, pct)
                if not ok:
                    logger.warning("Refusing click on %s: %s", match.name, why)
                    print(f"  [{WARN}] Refusing click on {match.name} "
                          f"at ({sx},{sy}) -- {why}")
                    return False
                registry.record(match.name, pct)

        jx = int(random.gauss(0, match.w / 8))
        jy = int(random.gauss(0, match.h / 8))
        jx = max(-match.w // 3, min(match.w // 3, jx))
        jy = max(-match.h // 3, min(match.h // 3, jy))
        return self._click(sx + jx, sy + jy)

    def _click_pct(self, pct_x: float, pct_y: float, jitter_px: int = 10):
        ww, wh = self.win["width"], self.win["height"]
        sx = self.win["left"] + int(ww * pct_x) + random.randint(-jitter_px, jitter_px)
        sy = self.win["top"] + int(wh * pct_y) + random.randint(-jitter_px, jitter_px)
        self._click(sx, sy)

    def _human_drag(self, sx: int, sy: int, ex: int, ey: int,
                    button: str = "L", speed_factor: float = 1.0,
                    easing: str = "in_out"):
        # `easing` is accepted for call-site compatibility but ignored: the
        # humanizer now owns the acceleration profile. `speed_factor` still
        # scales the overall duration (e.g. fast camera pans).
        sx, sy = self._clamp_to_window(sx, sy)
        ex, ey = self._clamp_to_window(ex, ey)
        self._moveto(sx, sy)
        time.sleep(random.uniform(0.08, 0.2))

        path = self.humanizer.humanize_move(sx, sy, ex, ey)
        if speed_factor != 1.0:
            path = [(x, y, max(3, int(ms / speed_factor))) for x, y, ms in path]

        if self._has_moveto:
            waypoints = self._path_to_hid([(sx, sy, 0), *path])
            self._send_path(waypoints, drag=True)
        else:
            sc = self._mouse_scale
            self.cmd.send("MDOWN", button)
            time.sleep(random.uniform(0.01, 0.03))
            prev_x, prev_y = float(sx), float(sy)
            for px, py, step_ms in path:
                cx, cy = self._clamp_to_window(int(px), int(py))
                mdx = cx - prev_x
                mdy = cy - prev_y
                send_dx = int(mdx / sc) if sc != 1.0 else int(mdx)
                send_dy = int(mdy / sc) if sc != 1.0 else int(mdy)
                if abs(send_dx) > 0 or abs(send_dy) > 0:
                    self.cmd.send("MOVE", send_dx, send_dy, step_ms)
                prev_x, prev_y = float(cx), float(cy)
            time.sleep(random.uniform(0.01, 0.03))
            self.cmd.send("MUP", button)

    def _scroll_at_center(self, amount: int, count: int = 1):
        cx, cy = self._center_screen()
        cx += random.randint(-int(self.win["width"] * 0.25), int(self.win["width"] * 0.25))
        cy += random.randint(-int(self.win["height"] * 0.15), int(self.win["height"] * 0.15))
        cx, cy = self._clamp_to_play_area(cx, cy)
        self._moveto(cx, cy)
        time.sleep(random.uniform(0.15, 0.4))

        overshoot = random.random() < self._scroll_overshoot_chance
        extra = random.randint(1, 2) if overshoot else 0
        total_notches = abs(amount) * (count + extra)
        direction = 1 if amount > 0 else -1
        for i in range(total_notches):
            self.cmd.send("SCROLL", direction)
            if random.random() < 0.3:
                time.sleep(random.uniform(0.15, 0.5))
            else:
                time.sleep(random.uniform(0.04, 0.12))
            if random.random() < 0.08:
                time.sleep(random.uniform(0.3, 1.5))
        if overshoot and extra > 0:
            time.sleep(random.uniform(0.4, 1.0))
            correction = max(1, int(extra * 0.6))
            for _ in range(correction):
                self.cmd.send("SCROLL", -direction)
                if random.random() < 0.3:
                    time.sleep(random.uniform(0.15, 0.5))
                else:
                    time.sleep(random.uniform(0.04, 0.12))

    def _press_escape(self):
        rx = random.uniform(0.82, 0.92)
        ry = random.uniform(0.35, 0.55)
        sx = self.win["left"] + int(self.win["width"] * rx)
        sy = self.win["top"] + int(self.win["height"] * ry)
        self._moveto(sx, sy)
        time.sleep(random.uniform(0.03, 0.12))
        self.cmd.send("CLICK", "L", random.randint(30, 80))
        logger.debug("dismiss_panel: click empty area (%.2f, %.2f)", rx, ry)
