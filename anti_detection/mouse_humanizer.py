from __future__ import annotations

import math
import random

_TWOPI = 2 * math.pi


def _gauss(mu: float, sigma: float) -> float:
    return random.gauss(mu, sigma)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


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
        self._speed_base = m.get("speed_base", 400)
        self._speed_variance = m.get("speed_variance", 150)
        self._overshoot_chance = m.get("overshoot_chance", 0.15)
        self._overshoot_dist = m.get("overshoot_distance", [5, 15])
        self._misclick_chance = m.get("misclick_chance", 0.01)
        self._click_spread = m.get("click_spread", 8)
        self._hold_ms = m.get("hold_ms", [50, 150])
        self._jitter_px = m.get("jitter_px", 2)
        self._curve_spread = m.get("curve_spread", 0.3)
        self._speed_lo = max(50, self._speed_base - self._speed_variance)
        self._speed_hi = self._speed_base + self._speed_variance
        self._speed_current = float(self._speed_base)
        self._speed_target = float(self._speed_base)
        self._tremor_freq = random.uniform(8, 12)
        self._tremor_amp = random.uniform(0.3, 1.5)

    def humanize_move(
        self, x1: int, y1: int, x2: int, y2: int,
    ) -> list[tuple[int, int, int]]:
        dist = math.hypot(x2 - x1, y2 - y1)
        if dist < 2:
            return [(x2, y2, 0)]

        if random.random() < 0.06:
            self._speed_target = random.uniform(self._speed_lo, self._speed_hi)
        self._speed_current += (self._speed_target - self._speed_current) * random.uniform(0.03, 0.07)
        speed = max(50, self._speed_current + _gauss(0, self._speed_variance * 0.08))
        total_ms = max(30, dist / speed * 1000)

        control_pts = self._make_control_points(x1, y1, x2, y2, dist)

        if dist < 50:
            num_steps = max(3, int(dist / 12))
        elif dist < 200:
            num_steps = max(5, int(dist / 8))
        else:
            num_steps = max(8, int(dist / 6))

        peak_shift = random.uniform(-0.05, 0.08)
        submovement_at = random.uniform(0.6, 0.8) if dist > 200 else None

        path: list[tuple[int, int, int]] = []
        t_accum = 0.0
        for i in range(1, num_steps + 1):
            t = i / num_steps
            ease_t = self._ease_asymmetric(t, peak_shift)

            if submovement_at and abs(t - submovement_at) < (1.0 / num_steps):
                ease_t *= random.uniform(0.92, 0.98)

            bx, by = _bezier_point(ease_t, control_pts)

            step_ms = int(total_ms / num_steps)
            t_accum += step_ms / 1000.0
            tx = self._tremor_amp * math.sin(_TWOPI * self._tremor_freq * t_accum
                                              + random.uniform(0, 0.3))
            ty = self._tremor_amp * math.sin(_TWOPI * self._tremor_freq * 1.1 * t_accum)

            jx = _gauss(0, self._jitter_px) + tx if self._jitter_px > 0 else tx
            jy = _gauss(0, self._jitter_px) + ty if self._jitter_px > 0 else ty

            path.append((int(bx + jx), int(by + jy), step_ms))

        if self.should_overshoot():
            overshoot_path = self._generate_overshoot(x2, y2, path[-1][2])
            path.extend(overshoot_path)
        else:
            path[-1] = (x2, y2, path[-1][2])

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

        spread = max(10, dist * self._curve_spread)
        num_mid = max(1, self._control_points - 1)
        for i in range(num_mid):
            frac = (i + 1) / (num_mid + 1)
            mx = x1 + (x2 - x1) * frac + _gauss(0, spread * 0.5)
            my = y1 + (y2 - y1) * frac + _gauss(0, spread * 0.5)
            points.append((mx, my))

        points.append((float(x2), float(y2)))
        return points

    @staticmethod
    def _ease_in_out(t: float) -> float:
        return 6*t**5 - 15*t**4 + 10*t**3

    @staticmethod
    def _ease_asymmetric(t: float, peak_shift: float = 0.0) -> float:
        t_adj = t + peak_shift * math.sin(t * math.pi)
        t_adj = max(0.0, min(1.0, t_adj))
        return 6*t_adj**5 - 15*t_adj**4 + 10*t_adj**3

    def _generate_overshoot(
        self, tx: int, ty: int, step_ms: int,
    ) -> list[tuple[int, int, int]]:
        lo, hi = self._overshoot_dist
        dist = _gauss((lo + hi) / 2, (hi - lo) / 4)
        angle = _gauss(0, 0.3)

        ox = tx + int(dist * math.cos(angle))
        oy = ty + int(dist * math.sin(angle))

        pause_ms = random.randint(50, 150)

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
