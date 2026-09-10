"""Headline numbers for the GUI: how many mines, how many marches, what failed.

report.py already knows how to read the run log -- its PATTERNS were tuned
against real runs -- so this reuses them rather than inventing a second set
that would drift. What it adds is a small, ranked summary a non-technical
person can read at a glance, instead of report.py's full diagnostic dump.

Counting is per farm start, because the log is APPENDED across restarts on
purpose (a truncating log erases the evidence of why it restarted).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from tools.dev.overnight.report import ANSI, PATTERNS, START, TS


@dataclass
class Run:
    """One farm start."""
    started: str = ""
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    counts: dict = field(default_factory=dict)

    @property
    def mines(self) -> int:
        return self.counts.get("done", 0)

    @property
    def failed(self) -> int:
        return self.counts.get("failed", 0)

    @property
    def marches(self) -> int:
        # Three mutually exclusive log variants, one per mine.
        return (self.counts.get("march_ok", 0)
                + self.counts.get("march_unver", 0)
                + self.counts.get("march_fixed", 0))

    @property
    def duration_min(self) -> float:
        if not (self.first_ts and self.last_ts):
            return 0.0
        return (self.last_ts - self.first_ts).total_seconds() / 60.0

    @property
    def success_pct(self) -> float:
        attempted = self.mines + self.failed
        return 100.0 * self.mines / attempted if attempted else 0.0

    @property
    def per_hour(self) -> float:
        hours = self.duration_min / 60.0
        return self.mines / hours if hours > 0.05 else 0.0


# Why a mine did not turn into a march, in the order worth reading. The label
# is what a player would call it, not what the log calls it.
FAILURE_LABELS = [
    ("empty_scan", "Quét không thấy mỏ nào", "Scans that found no mine"),
    ("occupied", "Mỏ đã có người chiếm", "Mines already occupied"),
    ("fog", "Camera lạc ra ngoài vương quốc", "Camera left the kingdom"),
    ("clf_reject", "Bộ phân loại loại bỏ", "Rejected by the classifier"),
    ("gather_miss", "Không thấy nút Thu Thập", "Gather button not found"),
    ("march_fail", "Bấm March nhưng không đi", "March pressed but never fired"),
    ("world_fail", "Không vào được bản đồ thế giới", "Could not reach the world map"),
    ("queue_short", "Còn slot lính trống", "March slots left unfilled"),
    ("restart", "Phải khởi động lại game", "Game restarts"),
    ("reconnect", "Hộp thoại mất kết nối", "Reconnect popups"),
    ("client_died", "Game tự thoát", "Client vanished"),
]


def parse(log_path) -> list[Run]:
    """Every farm start in the log, oldest first. Missing log -> []."""
    if not log_path or not log_path.exists():
        return []
    raw = log_path.read_text(encoding="utf-8", errors="replace")

    runs: list[Run] = []
    cur: Run | None = None
    for raw_line in raw.splitlines():
        line = ANSI.sub("", raw_line)
        m = START.search(line)
        if m:
            cur = Run(started=m.group(1), counts={k: 0 for k in PATTERNS})
            runs.append(cur)
            continue
        if cur is None:
            cur = Run(started="(trước lần chạy đầu)",
                      counts={k: 0 for k in PATTERNS})
            runs.append(cur)

        stamp = TS.search(line)
        if stamp:
            when = datetime.strptime(stamp.group(1), "%Y-%m-%d %H:%M:%S")
            cur.first_ts = cur.first_ts or when
            cur.last_ts = when

        for key, pattern in PATTERNS.items():
            if pattern.search(line):
                cur.counts[key] += 1
    return runs


def totals(runs: list[Run]) -> Run:
    """Every run added together, for the all-time figures."""
    out = Run(started="tổng", counts={k: 0 for k in PATTERNS})
    for r in runs:
        for k, v in r.counts.items():
            out.counts[k] = out.counts.get(k, 0) + v
        if r.first_ts and (out.first_ts is None or r.first_ts < out.first_ts):
            out.first_ts = r.first_ts
        if r.last_ts and (out.last_ts is None or r.last_ts > out.last_ts):
            out.last_ts = r.last_ts
    return out


def top_failures(run: Run, limit: int = 6, lang: str = "vi") -> list[tuple[str, int]]:
    """The recurring problems, biggest first, zeros dropped."""
    rows = []
    for key, vi, en in FAILURE_LABELS:
        n = run.counts.get(key, 0)
        if n:
            rows.append((vi if lang == "vi" else en, n))
    rows.sort(key=lambda kv: kv[1], reverse=True)
    return rows[:limit]
