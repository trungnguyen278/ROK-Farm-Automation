from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "config.yaml"


@dataclass
class SerialConfig:
    port: str = "COM3"
    baud: int = 115200
    timeout: float = 0.5
    heartbeat_interval: float = 2.0
    heartbeat_timeout: float = 5.0
    max_retries: int = 3
    ack_timeout: float = 0.5


@dataclass
class ROI:
    x: float = 0.0
    y: float = 0.0
    w: float = 1.0
    h: float = 0.05


@dataclass
class CaptureConfig:
    window_title: str = "Rise of Kingdoms"
    fps: int = 5
    roi: dict[str, ROI] = field(default_factory=dict)


@dataclass
class VisionConfig:
    template_dir: str = "templates/"
    match_threshold: float = 0.8
    scales: list[float] = field(default_factory=lambda: [0.8, 0.9, 1.0, 1.1, 1.2])
    cache_max_size: int = 100


@dataclass
class LogicConfig:
    strategy: str = "basic_gather"
    decision_rate: int = 10
    unknown_state_timeout: float = 5.0
    max_task_queue: int = 50


@dataclass
class AntiDetectionConfig:
    profile: str = "default"
    profile_dir: str = "profiles/"


@dataclass
class DurationConfig:
    mean: float = 25.0
    std: float = 8.0


@dataclass
class SessionConfig:
    enabled: bool = True
    farm_duration: DurationConfig = field(default_factory=lambda: DurationConfig(25, 8))
    break_duration: DurationConfig = field(default_factory=lambda: DurationConfig(8, 3))
    daily_hours_max: int = 6
    active_window: list[str] = field(default_factory=lambda: ["08:00", "23:00"])


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "logs/rok_automation.log"
    max_size_mb: int = 10
    backup_count: int = 5


@dataclass
class Config:
    serial: SerialConfig = field(default_factory=SerialConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    logic: LogicConfig = field(default_factory=LogicConfig)
    anti_detection: AntiDetectionConfig = field(default_factory=AntiDetectionConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @staticmethod
    def load(path: str = DEFAULT_CONFIG_PATH) -> Config:
        p = Path(path)
        if not p.exists():
            logger.warning("Config file %s not found, using defaults", path)
            return Config()

        with open(p, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        return Config(
            serial=_parse_serial(raw.get("serial", {})),
            capture=_parse_capture(raw.get("capture", {})),
            vision=_parse_vision(raw.get("vision", {})),
            logic=_parse_logic(raw.get("logic", {})),
            anti_detection=_parse_anti_detection(raw.get("anti_detection", {})),
            session=_parse_session(raw.get("session", {})),
            logging=_parse_logging(raw.get("logging", {})),
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.serial.baud not in (9600, 19200, 38400, 57600, 115200):
            errors.append(f"Invalid baud rate: {self.serial.baud}")
        if self.capture.fps < 1 or self.capture.fps > 60:
            errors.append(f"FPS out of range [1,60]: {self.capture.fps}")
        if not 0.0 < self.vision.match_threshold <= 1.0:
            errors.append(f"match_threshold must be (0,1]: {self.vision.match_threshold}")
        if self.logic.decision_rate < 1 or self.logic.decision_rate > 60:
            errors.append(f"decision_rate out of range [1,60]: {self.logic.decision_rate}")
        if self.session.daily_hours_max < 1 or self.session.daily_hours_max > 24:
            errors.append(f"daily_hours_max out of range: {self.session.daily_hours_max}")
        if self.logging.level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            errors.append(f"Invalid log level: {self.logging.level}")
        return errors


def _parse_serial(d: dict) -> SerialConfig:
    return SerialConfig(**{k: v for k, v in d.items() if k in SerialConfig.__dataclass_fields__})


def _parse_capture(d: dict) -> CaptureConfig:
    roi_raw = d.pop("roi", {})
    rois = {}
    for name, vals in roi_raw.items():
        rois[name] = ROI(**vals) if isinstance(vals, dict) else vals
    filtered = {k: v for k, v in d.items() if k in CaptureConfig.__dataclass_fields__ and k != "roi"}
    return CaptureConfig(roi=rois, **filtered)


def _parse_vision(d: dict) -> VisionConfig:
    return VisionConfig(**{k: v for k, v in d.items() if k in VisionConfig.__dataclass_fields__})


def _parse_logic(d: dict) -> LogicConfig:
    return LogicConfig(**{k: v for k, v in d.items() if k in LogicConfig.__dataclass_fields__})


def _parse_anti_detection(d: dict) -> AntiDetectionConfig:
    return AntiDetectionConfig(**{k: v for k, v in d.items() if k in AntiDetectionConfig.__dataclass_fields__})


def _parse_session(d: dict) -> SessionConfig:
    farm = d.pop("farm_duration", {})
    brk = d.pop("break_duration", {})
    filtered = {k: v for k, v in d.items() if k in SessionConfig.__dataclass_fields__
                and k not in ("farm_duration", "break_duration")}
    return SessionConfig(
        farm_duration=DurationConfig(**farm) if isinstance(farm, dict) else DurationConfig(),
        break_duration=DurationConfig(**brk) if isinstance(brk, dict) else DurationConfig(),
        **filtered,
    )


def _parse_logging(d: dict) -> LoggingConfig:
    return LoggingConfig(**{k: v for k, v in d.items() if k in LoggingConfig.__dataclass_fields__})
