from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from heapq import heappop, heappush

logger = logging.getLogger(__name__)


class TaskType(Enum):
    GATHER_RESOURCE = "gather"
    TRAIN_TROOPS = "train"
    COLLECT_REWARDS = "collect"
    ALLIANCE_HELP = "help"
    SCOUT = "scout"
    USE_AP = "use_ap"
    HEAL_TROOPS = "heal"
    UPGRADE_BUILDING = "upgrade"
    RESEARCH_TECH = "research"
    DISMISS_POPUP = "dismiss"


@dataclass(order=False)
class Task:
    id: str
    type: TaskType
    priority: int
    params: dict = field(default_factory=dict)
    retry_count: int = 0
    max_retries: int = 3
    created_at: float = field(default_factory=time.time)
    next_retry_at: float = 0.0

    def __lt__(self, other: Task) -> bool:
        return self.priority < other.priority

    def __le__(self, other: Task) -> bool:
        return self.priority <= other.priority


class TaskScheduler:
    def __init__(self, max_queue: int = 50):
        self._heap: list[Task] = []
        self._max_queue = max_queue
        self._task_ids: set[str] = set()

    def add(self, task: Task) -> bool:
        if task.id in self._task_ids:
            return False
        if len(self._heap) >= self._max_queue:
            logger.warning("Task queue full, dropping %s", task.id)
            return False
        heappush(self._heap, task)
        self._task_ids.add(task.id)
        return True

    def next(self) -> Task | None:
        now = time.time()
        ready: list[Task] = []
        deferred: list[Task] = []

        while self._heap:
            task = heappop(self._heap)
            if task.next_retry_at <= now:
                ready.append(task)
                break
            else:
                deferred.append(task)

        for t in deferred:
            heappush(self._heap, t)

        if not ready:
            return None

        task = ready[0]
        self._task_ids.discard(task.id)
        return task

    def retry(self, task: Task) -> bool:
        if task.retry_count >= task.max_retries:
            logger.warning("Max retries reached for %s", task.id)
            return False
        task.retry_count += 1
        backoff = min(2 ** task.retry_count * 2.0, 30.0)
        task.next_retry_at = time.time() + backoff
        self._task_ids.discard(task.id)
        return self.add(task)

    def clear(self):
        self._heap.clear()
        self._task_ids.clear()

    @property
    def pending_count(self) -> int:
        return len(self._heap)

    @property
    def task_ids(self) -> set[str]:
        return set(self._task_ids)
