from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from .state_machine import GameState
from .task_scheduler import Task, TaskType

logger = logging.getLogger(__name__)


@dataclass
class TaskConfig:
    type: TaskType
    interval: float
    priority: int
    required_states: set[GameState] = field(default_factory=lambda: {
        GameState.CITY_VIEW, GameState.WORLD_MAP,
    })
    params: dict = field(default_factory=dict)


STRATEGIES: dict[str, list[TaskConfig]] = {
    "basic_gather": [
        TaskConfig(TaskType.COLLECT_REWARDS, interval=300, priority=1,
                   required_states={GameState.CITY_VIEW}),
        TaskConfig(TaskType.ALLIANCE_HELP, interval=60, priority=2,
                   required_states={GameState.CITY_VIEW}),
        TaskConfig(TaskType.GATHER_RESOURCE, interval=600, priority=3,
                   required_states={GameState.CITY_VIEW, GameState.WORLD_MAP}),
        TaskConfig(TaskType.TRAIN_TROOPS, interval=1800, priority=5,
                   required_states={GameState.CITY_VIEW}),
        TaskConfig(TaskType.DISMISS_POPUP, interval=0, priority=0,
                   required_states={GameState.POPUP}),
    ],
    "war_prep": [
        TaskConfig(TaskType.HEAL_TROOPS, interval=120, priority=1,
                   required_states={GameState.CITY_VIEW}),
        TaskConfig(TaskType.TRAIN_TROOPS, interval=300, priority=2,
                   required_states={GameState.CITY_VIEW}),
        TaskConfig(TaskType.COLLECT_REWARDS, interval=300, priority=3,
                   required_states={GameState.CITY_VIEW}),
        TaskConfig(TaskType.DISMISS_POPUP, interval=0, priority=0,
                   required_states={GameState.POPUP}),
    ],
    "alliance_focus": [
        TaskConfig(TaskType.ALLIANCE_HELP, interval=30, priority=1,
                   required_states={GameState.CITY_VIEW}),
        TaskConfig(TaskType.COLLECT_REWARDS, interval=300, priority=2,
                   required_states={GameState.CITY_VIEW}),
        TaskConfig(TaskType.GATHER_RESOURCE, interval=600, priority=3,
                   required_states={GameState.CITY_VIEW, GameState.WORLD_MAP}),
        TaskConfig(TaskType.DISMISS_POPUP, interval=0, priority=0,
                   required_states={GameState.POPUP}),
    ],
    "gem_farm": [
        TaskConfig(TaskType.GATHER_RESOURCE, interval=300, priority=1,
                   required_states={
                       GameState.CITY_VIEW, GameState.WORLD_MAP,
                       GameState.IDLE, GameState.ERROR, GameState.INIT,
                   },
                   params={"resource_type": "gem"}),
        TaskConfig(TaskType.COLLECT_REWARDS, interval=600, priority=3,
                   required_states={GameState.CITY_VIEW}),
        TaskConfig(TaskType.ALLIANCE_HELP, interval=120, priority=4,
                   required_states={GameState.CITY_VIEW}),
        TaskConfig(TaskType.DISMISS_POPUP, interval=0, priority=0,
                   required_states={GameState.POPUP}),
    ],
}


class FarmStrategy:
    def __init__(self, name: str):
        if name not in STRATEGIES:
            logger.warning("Unknown strategy '%s', falling back to basic_gather", name)
            name = "basic_gather"
        self._name = name
        self._configs = STRATEGIES[name]
        self._last_generated: dict[TaskType, float] = {}
        self._counter = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def task_configs(self) -> list[TaskConfig]:
        return list(self._configs)

    def generate_tasks(self, state: GameState) -> list[Task]:
        now = time.time()
        tasks: list[Task] = []

        for cfg in self._configs:
            if state not in cfg.required_states:
                continue

            if cfg.interval > 0:
                last = self._last_generated.get(cfg.type, 0.0)
                if now - last < cfg.interval:
                    continue

            self._counter += 1
            task = Task(
                id=f"{cfg.type.value}_{self._counter}",
                type=cfg.type,
                priority=cfg.priority,
                params=dict(cfg.params),
            )
            tasks.append(task)
            self._last_generated[cfg.type] = now

        return tasks

    def reset(self):
        self._last_generated.clear()
        self._counter = 0

    @staticmethod
    def available_strategies() -> list[str]:
        return list(STRATEGIES.keys())
