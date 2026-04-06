"""
Structured JSON logger for the social sentiment subsystem.
Compatible with Loki label set: service_name, platform, level.
Logs ship to OTEL collector → Loki via existing pipeline.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_obj: dict[str, Any] = {
            "ts":           time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level":        record.levelname.lower(),
            "service_name": "social-sentiment",
            "logger":       record.name,
            "msg":          record.getMessage(),
        }

        # Attach extra fields added via logger.info("msg", extra={...})
        skip = {
            "args", "created", "exc_info", "exc_text", "filename",
            "funcName", "levelname", "levelno", "lineno", "message",
            "module", "msecs", "msg", "name", "pathname", "process",
            "processName", "relativeCreated", "stack_info", "taskName",
            "thread", "threadName",
        }
        for k, v in record.__dict__.items():
            if k not in skip:
                log_obj[k] = v

        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    from config.settings import LOG_FORMAT
    if LOG_FORMAT == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()
    root.addHandler(handler)
