import logging
import os
from logging.handlers import RotatingFileHandler

_initialized = False

LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: str = "INFO",
    log_file: str = "logs/rok_automation.log",
    max_size_mb: int = 10,
    backup_count: int = 5,
) -> logging.Logger:
    global _initialized
    if _initialized:
        return logging.getLogger()

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.setLevel(logging.DEBUG)
    root.addHandler(console)

    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_size_mb * 1024 * 1024,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)
    root.addHandler(file_handler)

    _initialized = True
    root.info("Logging initialized: level=%s file=%s", level, log_file)
    return root


def setup_from_config(logging_config) -> logging.Logger:
    return setup_logging(
        level=logging_config.level,
        log_file=logging_config.file,
        max_size_mb=logging_config.max_size_mb,
        backup_count=logging_config.backup_count,
    )
