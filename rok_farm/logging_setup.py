"""Logging + console colour tokens, configured once on import."""

from __future__ import annotations

import logging
from datetime import datetime

from rok_farm.config import LOG_DIR

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            LOG_DIR / f"gem_farm_test_{datetime.now():%Y%m%d_%H%M%S}.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("gem_farm_test")
# asyncio logs "Using proactor: IocpProactor" on every event loop -- the
# notification poll spins one each cycle, which spams the wait phase. Quiet it.
logging.getLogger("asyncio").setLevel(logging.WARNING)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"
INFO = "\033[94mINFO\033[0m"
