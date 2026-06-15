from __future__ import annotations

import bisect
import json
import math
import random
from pathlib import Path

_TWOPI = 2 * math.pi
_SQRT3 = math.sqrt(3)
_SQRT5 = math.sqrt(5)


def _gauss(mu: float, sigma: float) -> float:
    return random.gauss(mu, sigma)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _hypot(dx: float, dy: float) -> float:
    return math.hypot(dx, dy)


# ---------------------------------------------------------------------------
# Perlin-like 1D smooth noise (correlated, not independent like Gaussian)
# ---------------------------------------------------------------------------

class _SmoothNoise:
    """1D value noise with cosine interpolation.

    Produces smooth, correlated random values -- unlike Gaussian which is
    independent each sample.  Used as acceleration noise before integration.
    """

    def __init__(self, wavelength: float = 8.0, amplitude: float = 1.0,
                 octaves: int = 2, persistence: float = 0.5):
        self._wl = max(1.0, wavelength)
        self._amp = amplitude
        self._octaves = octaves
        self._persist = persistence
        self._seeds = [random.random() * 10000 for _ in range(octaves)]
        self._cache: dict[tuple[int, int], float] = {}

    def _lattice(self, octave: int, ix: int) -> float:
        key = (octave, ix)
        if key not in self._cache:
            s = self._seeds[octave]
            h = (ix * 127 + int(s * 311)) ^ int(s * 7919)
            self._cache[key] = ((h * 6364136223846793005 + 1442695040888963407)
                                & 0xFFFFFFFF) / 0xFFFFFFFF * 2.0 - 1.0
        return self._cache[key]

    def sample(self, t: float) -> float:
        total = 0.0
        amp = self._amp
        wl = self._wl
        for o in range(self._octaves):
            ix = int(math.floor(t / wl))
            frac = (t / wl) - ix
            smooth = (1 - math.cos(frac * math.pi)) * 0.5
            a = self._lattice(o, ix)
            b = self._lattice(o, ix + 1)
            total += (a + (b - a) * smooth) * amp
            amp *= self._persist
            wl *= 0.5
        return total


# ---------------------------------------------------------------------------
# Trajectory bank helpers
# ---------------------------------------------------------------------------

def _load_trajectory_bank(path: str | Path | None) -> dict | None:
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        return None
    with open(p) as f:
        bank = json.load(f)
    counts = {k: len(v) for k, v in bank.items()}
    if sum(counts.values()) == 0:
        return None
    return bank


def _bucket_for_distance(dist: float) -> str:
    if dist < 80:
        return "short"
    elif dist < 200:
        return "medium"
    elif dist < 400:
        return "long"
    return "xlong"


# ---------------------------------------------------------------------------
# Bezier helpers
# ---------------------------------------------------------------------------

def _bezier_point(t: float, points: list[tuple[float, float]]) -> tuple[float, float]:
    n = len(points) - 1
    x = y = 0.0
    for i, (px, py) in enumerate(points):
        coeff = _bernstein(n, i, t)
        x += coeff * px
        y += coeff * py
    return (x, y)


def _bernstein(n: int, k: int, t: float) -> float:
    return _comb(n, k) * (t ** k) * ((1 - t) ** (n - k))


def _comb(n: int, k: int) -> int:
    if k < 0 or k > n:
        return 0
    if k == 0 or k == n:
        return 1
    k = min(k, n - k)
    result = 1
    for i in range(k):
        result = result * (n - i) // (i + 1)
    return result


# ---------------------------------------------------------------------------
# MouseHumanizer
# ---------------------------------------------------------------------------

class MouseHumanizer:
    def __init__(self, profile: dict):
        m = profile.get("mouse", {})

        # --- Bezier params (kept for bezier generator) ---
        self._control_points = m.get("bezier_control_points", 3)
        self._curve_spread = m.get("curve_spread", 0.35)

        # --- WindMouse params ---
        wm = m.get("windmouse", {})
        self._wm_gravity = wm.get("gravity", 18.0)
        self._wm_wind = wm.get("wind", 1.2)
        self._wm_max_vel = wm.get("max_velocity", 15.0)
        self._wm_target_dist = wm.get("target_distance", 12.0)

        # --- Generator selection weights ---
        gen = m.get("generator_weights", {})
        self._w_windmouse = gen.get("windmouse", 0.45)
        self._w_bezier = gen.get("bezier", 0.15)
        self._w_replay = gen.get("replay", 0.40)

        # --- Shared movement params ---
        self._overshoot_chance = m.get("overshoot_chance", 0.18)
        self._overshoot_dist = m.get("overshoot_distance", [10, 55])
        self._misclick_chance = m.get("misclick_chance", 0.003)
        self._click_spread = m.get("click_spread", 2)
        self._hold_ms = m.get("hold_ms", [35, 90])
        self._jitter_px = m.get("jitter_px", 1)
        self._micro_corr_chance = m.get("micro_correction_chance", 0.47)
        self._micro_corr_steps = m.get("micro_correction_steps", [2, 4])
        self._micro_corr_dist = m.get("micro_correction_dist", [3, 12])

        # --- Fitts' law ---
        fitts = m.get("fitts_law", {})
        self._fitts_slope = fitts.get("slope", 1.11)
        self._fitts_intercept = fitts.get("intercept", 86.0)
        self._fitts_noise = fitts.get("noise_pct", 0.18)

        # --- Kinematic re-timer ---
        # Geometry generators produce a dense curve SHAPE; the re-timer then
        # places waypoints along it following a smooth velocity profile so the
        # cursor accelerates -> cruises -> decelerates instead of teleporting
        # between sparse points.  The ESP32 firmware interpolates sub-steps
        # between consecutive waypoints, treating delay_ms as travel time.
        kin = m.get("kinematic", {})
        self._seg_ms = kin.get("seg_ms", 22)
        self._min_waypoints = kin.get("min_waypoints", 6)
        self._max_waypoints = kin.get("max_waypoints", 48)
        self._accel_skew = kin.get("min_jerk_skew", 0.9)
        # Force model: the control signal is acceleration (muscle force),
        # integrated twice into the trajectory.
        self._force_curve = kin.get("force_curve", 0.6)       # lateral curvature
        self._force_motor_noise = kin.get("motor_noise", 0.06)
        self._accel_noise_only = kin.get("accel_noise_only", True)

        # --- Per-session physiological traits ---
        self._handedness_bias = random.choice([-1, 1])
        self._speed_percentile = random.uniform(0.35, 0.65)

        # --- Mid-movement pause ---
        pause = m.get("mid_pause", {})
        self._pause_chance = pause.get("chance", 0.12)
        self._pause_min_dist = pause.get("min_distance", 250)
        self._pause_ms = pause.get("duration_ms", [30, 120])

        # --- Trajectory bank ---
        self._mirror_chance = m.get("mirror_chance", 0.12)
        self._blend_chance = m.get("blend_chance", 0.10)
        self._speed_sigma = m.get("speed_sigma", 0.08)
        self._time_warp_range = m.get("time_warp_range", [0.93, 1.07])

        bank_path = m.get("trajectory_bank")
        self._bank = _load_trajectory_bank(bank_path)
        self._replay_chance = m.get("replay_chance", 0.85)

    # -----------------------------------------------------------------------
    # Fitts' law speed
    # -----------------------------------------------------------------------

    def _speed_for_distance(self, dist: float) -> float:
        base = self._fitts_slope * dist + self._fitts_intercept
        noise = _gauss(0, base * self._fitts_noise)
        return max(40, base + noise)

    def _curve_for_distance(self, dist: float) -> float:
        if dist < 80:
            return self._curve_spread * 1.6
        elif dist < 200:
            return self._curve_spread
        elif dist < 400:
            return self._curve_spread * 0.6
        return self._curve_spread * 0.35

    # -----------------------------------------------------------------------
    # Kinematic re-timer (acceleration model)
    # -----------------------------------------------------------------------

    def _pos_fraction(self, tau: float, skew: float) -> float:
        """Minimum-jerk position curve p(tau) in [0,1].

        p(tau) = 10t^3 - 15t^4 + 6t^5 has zero velocity AND zero acceleration
        at both endpoints -- the smoothest point-to-point reach (Flash & Hogan).
        Time-warping the input by tau**skew (skew<1) shifts the velocity peak
        earlier, lengthening the deceleration tail like a real hand.  Because
        p'(0)=p'(1)=0, any monotone warp keeps the endpoints velocity-free.
        """
        w = tau ** skew if skew != 1.0 else tau
        return w * w * w * (10.0 + w * (-15.0 + 6.0 * w))

    @staticmethod
    def _point_at_arc(poly: list[tuple[float, float]], cum: list[float],
                      target_len: float) -> tuple[float, float]:
        """Interpolate the point at a given cumulative arc length along poly."""
        j = bisect.bisect_left(cum, target_len)
        if j <= 0:
            return poly[0]
        if j >= len(poly):
            return poly[-1]
        seg = cum[j] - cum[j - 1]
        f = 0.0 if seg < 1e-9 else (target_len - cum[j - 1]) / seg
        x = poly[j - 1][0] + (poly[j][0] - poly[j - 1][0]) * f
        y = poly[j - 1][1] + (poly[j][1] - poly[j - 1][1]) * f
        return (x, y)

    @staticmethod
    def _point_at_time(poly: list[tuple[float, float]], tprof: list[float],
                       tau: float) -> tuple[float, float]:
        """Interpolate the point at normalized time tau using a recorded
        cumulative-time profile (reproduces real human velocity)."""
        j = bisect.bisect_left(tprof, tau)
        if j <= 0:
            return poly[0]
        if j >= len(poly):
            return poly[-1]
        span = tprof[j] - tprof[j - 1]
        f = 0.0 if span < 1e-9 else (tau - tprof[j - 1]) / span
        x = poly[j - 1][0] + (poly[j][0] - poly[j - 1][0]) * f
        y = poly[j - 1][1] + (poly[j][1] - poly[j - 1][1]) * f
        return (x, y)

    def _resample_kinematic(
        self, poly: list[tuple[float, float]], total_ms: float, dist: float,
        time_profile: list[float] | None = None,
    ) -> list[tuple[int, int, int]]:
        """Re-time a dense geometric polyline onto a moderate number of
        waypoints whose spacing follows a smooth velocity profile.

        poly:          dense (x, y) points describing the curve SHAPE only.
        total_ms:      desired total movement duration.
        time_profile:  optional normalized cumulative times (0..1), one per
            poly point.  When provided, the curve is resampled by *recorded*
            time to reproduce real human velocity; otherwise a synthetic
            minimum-jerk acceleration profile drives the spacing.

        Returns (x, y, delay_ms) waypoints where delay_ms is the travel time
        from the previous waypoint to this one (the ESP32 interpolates the
        sub-steps over that interval -> continuous accelerated motion).
        """
        if len(poly) < 2:
            x, y = poly[-1] if poly else (0.0, 0.0)
            return [(int(round(x)), int(round(y)), max(5, int(total_ms)))]

        n_seg = int(round(total_ms / self._seg_ms))
        n_seg = max(self._min_waypoints, min(self._max_waypoints, n_seg))
        base_ms = total_ms / n_seg

        use_time = (
            time_profile is not None
            and len(time_profile) == len(poly)
            and time_profile[-1] > time_profile[0]
        )

        if not use_time:
            cum = [0.0]
            for i in range(1, len(poly)):
                cum.append(cum[-1] + _hypot(poly[i][0] - poly[i - 1][0],
                                            poly[i][1] - poly[i - 1][1]))
            total_len = cum[-1]
            if total_len < 1e-6:
                return [(int(round(poly[-1][0])), int(round(poly[-1][1])),
                         max(5, int(total_ms)))]
            skew = self._accel_skew * random.uniform(0.95, 1.06)

        path: list[tuple[int, int, int]] = []
        for i in range(1, n_seg + 1):
            tau = i / n_seg
            if use_time:
                px, py = self._point_at_time(poly, time_profile, tau)
            else:
                frac = self._pos_fraction(tau, skew)
                px, py = self._point_at_arc(poly, cum, frac * total_len)
            delay_ms = max(2, int(round(base_ms * random.uniform(0.9, 1.12))))
            path.append((int(round(px)), int(round(py)), delay_ms))

        return path

    # -----------------------------------------------------------------------
    # Main entry point
    # -----------------------------------------------------------------------

    def humanize_move(
        self, x1: int, y1: int, x2: int, y2: int,
    ) -> list[tuple[int, int, int]]:
        dist = _hypot(x2 - x1, y2 - y1)
        if dist < 2:
            return [(x2, y2, 0)]

        # Pick generator with weighted random. In strict acceleration-noise mode
        # this stays inside the force integrator; no coordinate noise is added
        # after the path has been generated.
        path = self._pick_and_generate(x1, y1, x2, y2, dist)

        # Maybe insert a mid-movement micro-pause
        if dist >= self._pause_min_dist and random.random() < self._pause_chance:
            path = self._insert_mid_pause(path)

        return path

    def _pick_and_generate(
        self, x1: int, y1: int, x2: int, y2: int, dist: float,
    ) -> list[tuple[int, int, int]]:
        if self._accel_noise_only:
            return self._force_move(x1, y1, x2, y2, dist)

        # Try replay first if bank available
        if self._bank:
            has_data = bool(self._bank.get(_bucket_for_distance(dist)))
            if has_data:
                r = random.random()
                total = self._w_replay + self._w_windmouse + self._w_bezier
                replay_thresh = self._w_replay / total
                wm_thresh = replay_thresh + self._w_windmouse / total

                if r < replay_thresh:
                    result = self._replay_trajectory(x1, y1, x2, y2, dist)
                    if result is not None:
                        return result
                elif r < wm_thresh:
                    return self._force_move(x1, y1, x2, y2, dist)
                else:
                    return self._bezier_move(x1, y1, x2, y2, dist)

        # No bank or no data for this distance: force model vs Bezier
        wm_share = self._w_windmouse / (self._w_windmouse + self._w_bezier)
        if random.random() < wm_share:
            return self._force_move(x1, y1, x2, y2, dist)
        return self._bezier_move(x1, y1, x2, y2, dist)

    # -----------------------------------------------------------------------
    # Force / acceleration-driven generator (control signal = acceleration)
    # -----------------------------------------------------------------------

    def _force_move(
        self, x1: int, y1: int, x2: int, y2: int, dist: float,
    ) -> list[tuple[int, int, int]]:
        """Motion produced the way a hand actually moves: by commanding a
        FORCE (acceleration), not a position.

        The acceleration command has three parts -- a longitudinal
        push-then-brake impulse toward the target, a lateral 'wind' force
        (smooth correlated noise) that bends the path, and small motor noise.
        Integrating acceleration -> velocity -> position yields a velocity
        bell (accelerate, cruise, decelerate to rest) and an organic curve,
        rather than imposing a position profile and reverse-engineering speed.
        """
        total_ms = max(30, dist / self._speed_for_distance(dist) * 1000)
        n = int(round(total_ms / self._seg_ms))
        n = max(self._min_waypoints, min(self._max_waypoints, n))
        seg_ms = total_ms / n

        ux, uy = (x2 - x1) / dist, (y2 - y1) / dist     # along-target unit
        perp_x, perp_y = -uy, ux                        # perpendicular unit
        skew = self._accel_skew * random.uniform(0.95, 1.06)

        # Lateral 'wind' acceleration: smooth correlated noise (not white)
        wind = _SmoothNoise(wavelength=max(2.0, n / 3.0), amplitude=1.0,
                            octaves=2, persistence=0.5)

        # Double-integrate the acceleration command (longitudinal s, lateral l)
        v = s = 0.0
        lat_v = lat = 0.0
        svals: list[float] = []
        latvals: list[float] = []
        for k in range(n + 1):
            w = (k / n) ** skew
            a_par = math.sin(_TWOPI * w) + _gauss(0, self._force_motor_noise)
            v += a_par
            s += v
            svals.append(s)

            lat_v += wind.sample(k)
            lat += lat_v
            latvals.append(lat)

        s0 = svals[0]
        s_span = (svals[-1] - s0) or 1.0
        # De-trend the lateral drift so both endpoints sit on the straight line
        l0, l1 = latvals[0], latvals[-1]
        detrended = [latvals[k] - (l0 + (l1 - l0) * k / n) for k in range(n + 1)]
        max_lat = max((abs(d) for d in detrended), default=1.0) or 1.0
        amp = (dist * self._curve_for_distance(dist) * self._force_curve
               * random.uniform(0.5, 1.1))

        path: list[tuple[int, int, int]] = []
        for k in range(1, n + 1):
            s_n = (svals[k] - s0) / s_span * dist
            lat_off = detrended[k] / max_lat * amp
            px = x1 + ux * s_n + perp_x * lat_off
            py = y1 + uy * s_n + perp_y * lat_off
            delay_ms = max(2, int(round(seg_ms * random.uniform(0.9, 1.12))))
            path.append((int(round(px)), int(round(py)), delay_ms))

        # Overshoot or micro-correction at end
        if self.should_overshoot():
            path.extend(self._generate_overshoot(x2, y2, path[-1][2]))
        else:
            path[-1] = (x2, y2, path[-1][2])
            corr_chance = self._micro_corr_chance * max(0.1, 1.0 - dist / 500)
            if random.random() < corr_chance:
                path.extend(self._generate_micro_correction(x2, y2))

        return path

    # -----------------------------------------------------------------------
    # WindMouse path generator (physics-based)
    # -----------------------------------------------------------------------

    def _windmouse_move(
        self, x1: int, y1: int, x2: int, y2: int, dist: float,
    ) -> list[tuple[int, int, int]]:
        total_ms = max(30, dist / self._speed_for_distance(dist) * 1000)

        G_0 = self._wm_gravity * random.uniform(0.85, 1.15)
        W_0 = self._wm_wind * random.uniform(0.80, 1.20)
        M_0 = self._wm_max_vel * random.uniform(0.85, 1.15)
        D_0 = self._wm_target_dist * random.uniform(0.90, 1.10)

        sx, sy = float(x1), float(y1)
        cx, cy = float(x1), float(y1)
        vx = vy = 0.0
        wx = wy = 0.0

        raw_points: list[tuple[float, float]] = []

        max_iters = int(dist * 3) + 200
        for _ in range(max_iters):
            d = _hypot(x2 - sx, y2 - sy)
            if d < 1:
                break

            w_mag = min(W_0, d)

            if d >= D_0:
                wx = wx / _SQRT3 + (random.random() * 2 - 1) * w_mag / _SQRT5
                wy = wy / _SQRT3 + (random.random() * 2 - 1) * w_mag / _SQRT5
            else:
                wx /= _SQRT3
                wy /= _SQRT3
                if M_0 < 3:
                    M_0 = random.random() * 3 + 3
                else:
                    M_0 /= _SQRT5

            vx += wx + G_0 * (x2 - sx) / d
            vy += wy + G_0 * (y2 - sy) / d

            v_mag = _hypot(vx, vy)
            if v_mag > M_0:
                v_clip = M_0 / 2 + random.random() * M_0 / 2
                vx = (vx / v_mag) * v_clip
                vy = (vy / v_mag) * v_clip

            sx += vx
            sy += vy

            mx, my = int(round(sx)), int(round(sy))
            if mx != int(round(cx)) or my != int(round(cy)):
                raw_points.append((float(mx), float(my)))
                cx, cy = float(mx), float(my)

        if not raw_points or (int(raw_points[-1][0]) != x2 or int(raw_points[-1][1]) != y2):
            raw_points.append((float(x2), float(y2)))

        # Re-time the dense WindMouse curve onto a smooth acceleration profile
        poly = [(float(x1), float(y1))] + raw_points
        path = self._resample_kinematic(poly, total_ms, dist)

        # Overshoot or micro-correction at end
        if self.should_overshoot():
            overshoot = self._generate_overshoot(x2, y2, path[-1][2])
            path.extend(overshoot)
        else:
            path[-1] = (x2, y2, path[-1][2])
            corr_chance = self._micro_corr_chance * max(0.1, 1.0 - dist / 500)
            if random.random() < corr_chance:
                path.extend(self._generate_micro_correction(x2, y2))

        return path

    # -----------------------------------------------------------------------
    # Bezier path generator (geometry sampled densely, re-timed kinematically)
    # -----------------------------------------------------------------------

    def _bezier_move(
        self, x1: int, y1: int, x2: int, y2: int, dist: float,
    ) -> list[tuple[int, int, int]]:
        speed = self._speed_for_distance(dist)
        total_ms = max(30, dist / speed * 1000)

        control_pts = self._make_control_points(x1, y1, x2, y2, dist)

        # Sample the Bezier densely in its native parameter to get the curve
        # SHAPE only; the kinematic re-timer owns the velocity profile.
        n_geo = 160
        poly = [_bezier_point(k / n_geo, control_pts) for k in range(n_geo + 1)]
        path = self._resample_kinematic(poly, total_ms, dist)

        if self.should_overshoot():
            overshoot_path = self._generate_overshoot(x2, y2, path[-1][2])
            path.extend(overshoot_path)
        else:
            path[-1] = (x2, y2, path[-1][2])
            corr_chance = self._micro_corr_chance * max(0.1, 1.0 - dist / 500)
            if random.random() < corr_chance:
                path.extend(self._generate_micro_correction(x2, y2))

        return path

    # -----------------------------------------------------------------------
    # Replay trajectory (from recorded human data)
    # -----------------------------------------------------------------------

    def _replay_trajectory(
        self, x1: int, y1: int, x2: int, y2: int, dist: float,
    ) -> list[tuple[int, int, int]] | None:
        bucket = _bucket_for_distance(dist)
        entries = self._bank.get(bucket, [])
        if not entries:
            return None

        if len(entries) >= 2 and random.random() < self._blend_chance:
            entry = self._blend_trajectories(random.sample(entries, 2))
        else:
            entry = self._pick_by_speed(entries)
        norm = entry["norm_path"]
        if len(norm) < 3:
            return None

        if random.random() < self._mirror_chance:
            norm = [(nx, -ny * self._handedness_bias, nt) for nx, ny, nt in norm]

        angle = math.atan2(y2 - y1, x2 - x1)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)

        orig_speed = entry["speed"]
        speed = orig_speed * random.lognormvariate(0, self._speed_sigma)
        total_ms = max(30, dist / speed * 1000)

        warp_base = random.uniform(0.96, 1.04)
        warp_drift = random.uniform(-0.02, 0.02)

        tw_lo, tw_hi = self._time_warp_range
        time_warp_knots = sorted([random.uniform(0.15, 0.85) for _ in range(2)])
        time_warp_vals = [random.uniform(tw_lo, tw_hi) for _ in range(2)]

        # Keep the recorded curve DENSE -- map every point to screen space and
        # build a normalized cumulative-time profile.  The kinematic re-timer
        # then resamples by recorded time, reproducing the real human velocity
        # envelope, while the ESP32 fills in continuous sub-steps.
        jitter_sigma = max(0.2, dist * 0.003)

        poly: list[tuple[float, float]] = []
        tprof: list[float] = []
        n_pts = len(norm)
        for i, pt in enumerate(norm):
            nx, ny, t_norm = pt[0], pt[1], pt[2]

            progress = i / max(1, n_pts - 1)
            warp = warp_base + warp_drift * (progress - 0.5) * 2
            warp += _gauss(0, 0.008)
            ny_warped = ny * warp

            jx = _gauss(0, jitter_sigma)
            jy = _gauss(0, jitter_sigma)

            rx = nx * dist
            ry = ny_warped * dist
            px = x1 + rx * cos_a - ry * sin_a + jx
            py = y1 + rx * sin_a + ry * cos_a + jy
            poly.append((px, py))

            warped_t = self._warp_time(t_norm, time_warp_knots, time_warp_vals)
            tprof.append(warped_t)

        # Normalize the time profile to [0,1] and enforce monotonicity
        t0 = tprof[0]
        span = tprof[-1] - t0
        if span <= 1e-6:
            tprof = None
        else:
            norm_t = []
            last = 0.0
            for t in tprof:
                v = (t - t0) / span
                last = v if v > last else last
                norm_t.append(last)
            tprof = norm_t

        path = self._resample_kinematic(poly, total_ms, dist, time_profile=tprof)
        path[-1] = (x2, y2, path[-1][2])

        if self.should_overshoot():
            overshoot_path = self._generate_overshoot(x2, y2, path[-1][2])
            path.extend(overshoot_path)
        else:
            corr_chance = self._micro_corr_chance * max(0.1, 1.0 - dist / 500)
            if random.random() < corr_chance:
                path.extend(self._generate_micro_correction(x2, y2))

        return path

    def _pick_by_speed(self, entries: list[dict]) -> dict:
        speeds = sorted(e["speed"] for e in entries)
        target = speeds[int(self._speed_percentile * (len(speeds) - 1))]
        sigma = target * 0.2
        weights = []
        for e in entries:
            diff = e["speed"] - target
            weights.append(math.exp(-0.5 * (diff / max(sigma, 1)) ** 2))
        total = sum(weights)
        r = random.uniform(0, total)
        acc = 0.0
        for e, w in zip(entries, weights):
            acc += w
            if acc >= r:
                return e
        return entries[-1]

    @staticmethod
    def _warp_time(t: float, knots: list[float], vals: list[float]) -> float:
        scale = 1.0
        for k, v in zip(knots, vals):
            influence = max(0, 1.0 - abs(t - k) * 4)
            scale += (v - 1.0) * influence
        return _clamp(t * scale, 0.0, 1.0)

    @staticmethod
    def _blend_trajectories(pair: list[dict]) -> dict:
        a, b = pair[0], pair[1]
        na, nb = a["norm_path"], b["norm_path"]
        blend = random.uniform(0.3, 0.7)
        n = min(len(na), len(nb))
        merged = []
        for i in range(n):
            t = i / max(1, n - 1)
            w = blend + _gauss(0, 0.05) * math.sin(t * math.pi)
            w = _clamp(w, 0.15, 0.85)
            mx = na[i][0] * w + nb[i][0] * (1 - w)
            my = na[i][1] * w + nb[i][1] * (1 - w)
            mt = na[i][2] * w + nb[i][2] * (1 - w)
            merged.append((mx, my, mt))
        return {
            "norm_path": merged,
            "distance": a["distance"] * blend + b["distance"] * (1 - blend),
            "duration": a["duration"] * blend + b["duration"] * (1 - blend),
            "speed": a["speed"] * blend + b["speed"] * (1 - blend),
        }

    def _insert_mid_pause(
        self, path: list[tuple[int, int, int]],
    ) -> list[tuple[int, int, int]]:
        if len(path) < 5:
            return path

        # Insert pause at 55-75% of the way (deceleration zone)
        idx = int(len(path) * random.uniform(0.55, 0.75))
        idx = min(idx, len(path) - 2)

        lo, hi = self._pause_ms
        pause_ms = random.randint(lo, hi)

        px, py, orig_ms = path[idx]
        path[idx] = (px, py, orig_ms + pause_ms)
        return path

    # -----------------------------------------------------------------------
    # Click humanization
    # -----------------------------------------------------------------------

    def humanize_click(self, x: int, y: int) -> tuple[int, int, int]:
        ox = int(_gauss(0, self._click_spread))
        oy = int(_gauss(0, self._click_spread))
        if random.random() < 0.08:
            hold = random.randint(200, 400)
        else:
            hold = random.randint(self._hold_ms[0], self._hold_ms[1])
        return (ox, oy, hold)

    def should_overshoot(self) -> bool:
        return random.random() < self._overshoot_chance

    def should_misclick(self) -> bool:
        return random.random() < self._misclick_chance

    # -----------------------------------------------------------------------
    # Bezier control points
    # -----------------------------------------------------------------------

    def _make_control_points(
        self, x1: int, y1: int, x2: int, y2: int, dist: float,
    ) -> list[tuple[float, float]]:
        points: list[tuple[float, float]] = [(float(x1), float(y1))]

        curve = self._curve_for_distance(dist)
        spread = max(5, dist * curve)
        num_mid = max(1, self._control_points - 1)
        for i in range(num_mid):
            frac = (i + 1) / (num_mid + 1)
            mx = x1 + (x2 - x1) * frac + _gauss(0, spread * 0.5)
            my = y1 + (y2 - y1) * frac + _gauss(0, spread * 0.5)
            points.append((mx, my))

        points.append((float(x2), float(y2)))
        return points

    # -----------------------------------------------------------------------
    # Overshoot
    # -----------------------------------------------------------------------

    def _generate_overshoot(
        self, tx: int, ty: int, step_ms: int,
    ) -> list[tuple[int, int, int]]:
        lo, hi = self._overshoot_dist
        dist = _gauss((lo + hi) / 2, (hi - lo) / 4)
        angle = _gauss(0, 0.3)

        ox = tx + int(dist * math.cos(angle))
        oy = ty + int(dist * math.sin(angle))

        pause_ms = random.randint(40, 120)

        mid1_x = ox + int((tx - ox) * 0.35 + _gauss(0, dist * 0.15))
        mid1_y = oy + int((ty - oy) * 0.35 + _gauss(0, dist * 0.15))
        mid2_x = ox + int((tx - ox) * 0.7 + _gauss(0, dist * 0.1))
        mid2_y = oy + int((ty - oy) * 0.7 + _gauss(0, dist * 0.1))

        seg_ms = random.randint(25, 50)
        return [
            (ox, oy, step_ms),
            (ox, oy, pause_ms),
            (mid1_x, mid1_y, seg_ms),
            (mid2_x, mid2_y, seg_ms),
            (tx, ty, random.randint(20, 40)),
        ]

    # -----------------------------------------------------------------------
    # Micro-correction
    # -----------------------------------------------------------------------

    def _generate_micro_correction(
        self, tx: int, ty: int,
    ) -> list[tuple[int, int, int]]:
        lo, hi = self._micro_corr_steps
        num = random.randint(lo, hi)
        lo_d, hi_d = self._micro_corr_dist
        path: list[tuple[int, int, int]] = []
        init_d = _gauss((lo_d + hi_d) / 2, (hi_d - lo_d) / 3)
        drift_angle = random.uniform(0, _TWOPI)
        cx = tx + int(init_d * math.cos(drift_angle))
        cy = ty + int(init_d * math.sin(drift_angle))
        path.append((cx, cy, random.randint(15, 35)))
        for i in range(1, num):
            frac = (i + 1) / (num + 1)
            nx = cx + int((tx - cx) * frac + _gauss(0, 1))
            ny = cy + int((ty - cy) * frac + _gauss(0, 1))
            path.append((nx, ny, random.randint(15, 40)))
            cx, cy = nx, ny
        path.append((tx, ty, random.randint(20, 40)))
        return path
