from __future__ import annotations

import json
import math
import random
from pathlib import Path

_TWOPI = 2 * math.pi


def _gauss(mu: float, sigma: float) -> float:
    return random.gauss(mu, sigma)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


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


class MouseHumanizer:
    def __init__(self, profile: dict):
        m = profile.get("mouse", {})
        self._control_points = m.get("bezier_control_points", 3)
        self._overshoot_chance = m.get("overshoot_chance", 0.18)
        self._overshoot_dist = m.get("overshoot_distance", [10, 55])
        self._misclick_chance = m.get("misclick_chance", 0.003)
        self._click_spread = m.get("click_spread", 2)
        self._hold_ms = m.get("hold_ms", [35, 90])
        self._jitter_px = m.get("jitter_px", 1)
        self._curve_spread = m.get("curve_spread", 0.35)
        self._micro_corr_chance = m.get("micro_correction_chance", 0.47)
        self._micro_corr_steps = m.get("micro_correction_steps", [2, 4])
        self._micro_corr_dist = m.get("micro_correction_dist", [3, 12])

        fitts = m.get("fitts_law", {})
        self._fitts_slope = fitts.get("slope", 1.11)
        self._fitts_intercept = fitts.get("intercept", 86.0)
        self._fitts_noise = fitts.get("noise_pct", 0.18)

        self._tremor_freq = random.uniform(8, 12)
        self._tremor_amp = random.uniform(0.1, 0.4)

        bank_path = m.get("trajectory_bank")
        self._bank = _load_trajectory_bank(bank_path)
        self._replay_chance = m.get("replay_chance", 0.85)

        self._handedness_bias = random.choice([-1, 1])
        self._mirror_chance = m.get("mirror_chance", 0.12)
        self._blend_chance = m.get("blend_chance", 0.10)
        self._speed_sigma = m.get("speed_sigma", 0.08)
        self._time_warp_range = m.get("time_warp_range", [0.93, 1.07])
        self._speed_percentile = random.uniform(0.35, 0.65)

    def _speed_for_distance(self, dist: float) -> float:
        """Fitts' law: longer distance = faster speed."""
        base = self._fitts_slope * dist + self._fitts_intercept
        noise = _gauss(0, base * self._fitts_noise)
        return max(40, base + noise)

    def _curve_for_distance(self, dist: float) -> float:
        """Shorter moves are more curved, longer moves straighter."""
        if dist < 80:
            return self._curve_spread * 1.6
        elif dist < 200:
            return self._curve_spread
        elif dist < 400:
            return self._curve_spread * 0.6
        return self._curve_spread * 0.35

    def humanize_move(
        self, x1: int, y1: int, x2: int, y2: int,
    ) -> list[tuple[int, int, int]]:
        dist = math.hypot(x2 - x1, y2 - y1)
        if dist < 2:
            return [(x2, y2, 0)]

        if self._bank and random.random() < self._replay_chance:
            replay = self._replay_trajectory(x1, y1, x2, y2, dist)
            if replay is not None:
                return replay

        return self._bezier_move(x1, y1, x2, y2, dist)

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

        if dist < 80:
            target_steps = max(3, int(dist / 10))
        elif dist < 200:
            target_steps = max(6, int(dist / 15))
        elif dist < 400:
            target_steps = max(8, min(int(dist / 15), 28))
        else:
            target_steps = max(10, min(int(dist / 18), 35))
        step_sz = max(1, len(norm) // target_steps)
        sampled = norm[::step_sz]
        if norm[-1] not in sampled:
            sampled.append(norm[-1])

        jitter_sigma = max(0.2, dist * 0.003)

        path: list[tuple[int, int, int]] = []
        prev_warped_t = 0.0
        n_pts = len(sampled)
        for i, pt in enumerate(sampled):
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

            warped_t = self._warp_time(t_norm, time_warp_knots, time_warp_vals)
            dt = max(0, warped_t - prev_warped_t)
            delay_ms = max(2, int(dt * total_ms))
            prev_warped_t = warped_t

            path.append((int(px), int(py), delay_ms))

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
            mx = na[i][0] * w + nb[i][1 - 0] * (1 - w)
            my = na[i][1] * w + nb[i][1] * (1 - w)
            mt = na[i][2] * w + nb[i][2] * (1 - w)
            merged.append((mx, my, mt))
        return {
            "norm_path": merged,
            "distance": a["distance"] * blend + b["distance"] * (1 - blend),
            "duration": a["duration"] * blend + b["duration"] * (1 - blend),
            "speed": a["speed"] * blend + b["speed"] * (1 - blend),
        }

    def _bezier_move(
        self, x1: int, y1: int, x2: int, y2: int, dist: float,
    ) -> list[tuple[int, int, int]]:
        speed = self._speed_for_distance(dist)
        total_ms = max(30, dist / speed * 1000)

        control_pts = self._make_control_points(x1, y1, x2, y2, dist)

        if dist < 50:
            num_steps = max(3, int(dist / 12))
        elif dist < 200:
            num_steps = max(5, int(dist / 8))
        elif dist < 400:
            num_steps = max(8, int(dist / 10))
        else:
            num_steps = max(10, int(dist / 15))

        submovement_at = random.uniform(0.6, 0.8) if dist > 200 else None

        if dist < 100:
            noise_zone = 0.4
        elif dist < 250:
            noise_zone = 0.2
        else:
            noise_zone = 0.1

        path: list[tuple[int, int, int]] = []
        t_accum = 0.0
        for i in range(1, num_steps + 1):
            t = i / num_steps
            ease_t = self._ease_ramp_decel(t)

            if submovement_at and abs(t - submovement_at) < (1.0 / num_steps):
                ease_t *= random.uniform(0.92, 0.98)

            bx, by = _bezier_point(ease_t, control_pts)

            step_ms = int(total_ms / num_steps)
            t_accum += step_ms / 1000.0

            near_edge = t < noise_zone or t > (1.0 - noise_zone)
            if near_edge and self._jitter_px > 0:
                tx = self._tremor_amp * math.sin(_TWOPI * self._tremor_freq * t_accum
                                                  + random.uniform(0, 0.3))
                ty = self._tremor_amp * math.sin(_TWOPI * self._tremor_freq * 1.1 * t_accum)
                jx = _gauss(0, self._jitter_px) + tx
                jy = _gauss(0, self._jitter_px) + ty
            else:
                jx = jy = 0.0

            path.append((int(bx + jx), int(by + jy), step_ms))

        if self.should_overshoot():
            overshoot_path = self._generate_overshoot(x2, y2, path[-1][2])
            path.extend(overshoot_path)
        else:
            path[-1] = (x2, y2, path[-1][2])
            corr_chance = self._micro_corr_chance * max(0.1, 1.0 - dist / 500)
            if random.random() < corr_chance:
                path.extend(self._generate_micro_correction(x2, y2))

        return path

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

    @staticmethod
    def _ease_ramp_decel(t: float) -> float:
        """Velocity profile matched to real mouse data:
        fast ramp 0-0.3, plateau 0.3-0.5, gradual decel 0.5-1.0.
        """
        if t <= 0.3:
            s = t / 0.3
            return 0.35 * (3 * s * s - 2 * s * s * s)
        elif t <= 0.5:
            return 0.35 + (t - 0.3) / 0.2 * 0.30
        else:
            s = (t - 0.5) / 0.5
            return 0.65 + 0.35 * (3 * s * s - 2 * s * s * s)

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

    def _generate_micro_correction(
        self, tx: int, ty: int,
    ) -> list[tuple[int, int, int]]:
        """Small converging correction toward target (seen in 47% of real data)."""
        lo, hi = self._micro_corr_steps
        num = random.randint(lo, hi)
        lo_d, hi_d = self._micro_corr_dist
        path: list[tuple[int, int, int]] = []
        # Start offset from target, converge back
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
