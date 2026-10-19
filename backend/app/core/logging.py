"""Structured JSON logs (`00-ARCHITECTURE.md` section 9).

One line per event, `correlation_id` included when the record carries one.
`03-SECURITY.md` section 9 forbids putting raw configuration values or
tokens in logs, so nothing here reflects the environment into a record: the
formatter emits only the message and a short allowlist of extras.
"""

from __future__ import annotations

import json
import logging
import sys

_ALLOWED_EXTRAS = ("correlation_id", "duration_ms", "detail")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            # Cloud Logging reads a JSON line's level from `severity` only.
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in _ALLOWED_EXTRAS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
