# Config Reference

> **AI Note:** Một file config.yaml duy nhất ở root. Profile JSON override timing/behavior. Dùng pyyaml load, dataclass validate.

## config.yaml Full Schema

```yaml
# === Serial ===
serial:
  port: "COM3"                    # ESP32 COM port
  baud: 115200
  timeout: 0.5                    # read timeout (s)
  heartbeat_interval: 2.0         # PING interval (s)
  heartbeat_timeout: 5.0          # reconnect if no PONG (s)
  max_retries: 3                  # per command
  ack_timeout: 0.5                # wait for ACK (s)

# === Capture ===
capture:
  window_title: "Rise of Kingdoms"
  fps: 5                          # vision analysis rate
  roi:
    top_bar:    { x: 0.0,  y: 0.0,  w: 1.0,  h: 0.05 }
    center:     { x: 0.1,  y: 0.15, w: 0.8,  h: 0.55 }
    bottom_bar: { x: 0.0,  y: 0.9,  w: 1.0,  h: 0.1  }
    popup:      { x: 0.25, y: 0.2,  w: 0.5,  h: 0.5  }
    minimap:    { x: 0.8,  y: 0.75, w: 0.2,  h: 0.25 }

# === Vision ===
vision:
  template_dir: "templates/"
  match_threshold: 0.8            # minimum confidence
  scales: [0.8, 0.9, 1.0, 1.1, 1.2]
  cache_max_size: 100

# === Logic ===
logic:
  strategy: "basic_gather"        # farm strategy name
  decision_rate: 10               # Hz
  unknown_state_timeout: 5.0      # seconds before ERROR
  max_task_queue: 50

# === Anti-Detection ===
anti_detection:
  profile: "default"              # profile name or "random"
  profile_dir: "profiles/"

# === Session ===
session:
  enabled: true
  farm_duration: { mean: 25, std: 8 }      # minutes
  break_duration: { mean: 8, std: 3 }      # minutes
  daily_hours_max: 6
  active_window: ["08:00", "23:00"]

# === Logging ===
logging:
  level: "INFO"                   # DEBUG, INFO, WARNING, ERROR
  file: "logs/rok_automation.log"
  max_size_mb: 10
  backup_count: 5
```

## Python Config Loader

```python
# config.py
@dataclass
class Config:
    serial: SerialConfig
    capture: CaptureConfig
    vision: VisionConfig
    logic: LogicConfig
    anti_detection: AntiDetectionConfig
    session: SessionConfig
    logging: LoggingConfig

    @staticmethod
    def load(path: str = "config.yaml") -> "Config"
    
    def validate(self) -> list[str]  # returns list of errors, empty = OK
```

## Profile JSON Override Priority

```
config.yaml (base) → profiles/{name}.json (overrides timing/behavior only)
```

Profile chỉ override các key trong `anti_detection`, `session`. Không override `serial`, `capture`, `vision`.
