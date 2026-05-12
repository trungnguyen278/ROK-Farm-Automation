# State Machine & Task Scheduler

> **AI Note:** 3 file: state_machine (enum states + transition table), task_scheduler (priority queue + retry backoff), farm_strategies (task sequences per farm type). Main thread chạy loop: poll vision → update state → schedule tasks.

## Game States

```python
# logic/state_machine.py
class GameState(Enum):
    INIT = "init"                    # Starting up, detecting game
    CITY_VIEW = "city_view"          # Inside city
    WORLD_MAP = "world_map"          # World map view
    MARCHING = "marching"            # March in progress
    POPUP = "popup"                  # Dialog/popup open
    COMMANDER_SELECT = "commander"   # Selecting commander
    LOADING = "loading"              # Screen transition
    DISCONNECTED = "disconnected"    # Game window lost
    IDLE = "idle"                    # On break (session manager)
    ERROR = "error"                  # Unknown state, waiting
```

## Transition Table

```
INIT ──(window found)──▶ CITY_VIEW or WORLD_MAP
CITY_VIEW ──(click world)──▶ WORLD_MAP
WORLD_MAP ──(click city)──▶ CITY_VIEW
CITY_VIEW ──(start march)──▶ COMMANDER_SELECT ──(confirm)──▶ MARCHING
* ──(popup detected)──▶ POPUP ──(dismissed)──▶ previous_state
* ──(loading screen)──▶ LOADING ──(loaded)──▶ detected_state
* ──(window lost)──▶ DISCONNECTED ──(window found)──▶ INIT
* ──(unknown screen)──▶ ERROR ──(5s timeout + recognized)──▶ detected_state
* ──(break time)──▶ IDLE ──(break over)──▶ previous_state
```

## State Machine Class

```python
class StateMachine:
    def __init__(self)
    state: GameState
    previous_state: GameState
    state_entered_at: float              # timestamp
    
    def update(self, vision_result: VisionResult)  # main update
    def can_transition(self, target: GameState) -> bool
    def on_enter(self, state: GameState)   # entry actions
    def on_exit(self, state: GameState)    # exit actions
    def time_in_state(self) -> float       # seconds in current state
```

## Task Scheduler

```python
# logic/task_scheduler.py
class TaskScheduler:
    def __init__(self)
    queue: PriorityQueue[Task]
    
    def add(self, task: Task)
    def next(self) -> Task | None          # pop highest priority ready task
    def retry(self, task: Task)            # re-add with backoff
    def clear(self)
    def pending_count(self) -> int

@dataclass
class Task:
    id: str
    type: TaskType
    priority: int                  # lower = higher priority
    params: dict
    retry_count: int = 0
    max_retries: int = 3
    created_at: float = field(default_factory=time.time)
    next_retry_at: float = 0       # backoff timestamp

class TaskType(Enum):
    GATHER_RESOURCE = "gather"     # Send troops to gather
    TRAIN_TROOPS = "train"         # Train troops in buildings  
    COLLECT_REWARDS = "collect"    # Collect free rewards/chests
    ALLIANCE_HELP = "help"         # Help alliance members
    SCOUT = "scout"                # Scout targets
    USE_AP = "use_ap"              # Use action points
    HEAL_TROOPS = "heal"           # Heal wounded troops
    UPGRADE_BUILDING = "upgrade"   # Start building upgrade
    RESEARCH_TECH = "research"     # Start research
    DISMISS_POPUP = "dismiss"      # Close unexpected popup
```

### Retry Backoff
```python
backoff_delay = min(2 ** task.retry_count * 2.0, 30.0)  # 2s, 4s, 8s, 16s, max 30s
task.next_retry_at = time.time() + backoff_delay
```

## Farm Strategies

```python
# logic/farm_strategies.py
class FarmStrategy:
    def __init__(self, name: str, tasks: list[TaskConfig])
    def generate_tasks(self, state: GameState) -> list[Task]

# Each strategy = ordered list of task types with conditions
STRATEGIES = {
    "basic_gather": [
        TaskConfig(TaskType.COLLECT_REWARDS, interval=300, priority=1),
        TaskConfig(TaskType.ALLIANCE_HELP, interval=60, priority=2),
        TaskConfig(TaskType.GATHER_RESOURCE, interval=600, priority=3),
        TaskConfig(TaskType.TRAIN_TROOPS, interval=1800, priority=5),
    ],
    "war_prep": [
        TaskConfig(TaskType.HEAL_TROOPS, interval=120, priority=1),
        TaskConfig(TaskType.TRAIN_TROOPS, interval=300, priority=2),
        TaskConfig(TaskType.COLLECT_REWARDS, interval=300, priority=3),
    ],
}
```

## Main Loop Pseudocode

```python
def main_loop(state_machine, scheduler, serial, vision_queue, anti_detection):
    while running:
        # 1. Get vision result
        if not vision_queue.empty():
            result = vision_queue.get()
            state_machine.update(result)
        
        # 2. Generate tasks from strategy
        new_tasks = strategy.generate_tasks(state_machine.state)
        for task in new_tasks:
            scheduler.add(task)
        
        # 3. Execute next task
        task = scheduler.next()
        if task:
            actions = task_to_actions(task, state_machine.state)
            for action in actions:
                humanized = anti_detection.process(action)
                serial.send(humanized)
        
        time.sleep(0.1)  # 10Hz decision loop
```
