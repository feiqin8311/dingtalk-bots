from __future__ import annotations

import logging
import sys


def setup_logger(log_format: str, log_level: str) -> logging.Logger:
    logger = logging.getLogger()
    if logger.handlers:
        logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(log_format))
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, log_level, logging.INFO))
    logger.propagate = False
    return logger

