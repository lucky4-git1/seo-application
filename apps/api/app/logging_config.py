"""Structured JSON logging with request_id / org / project context."""
from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or request_id_ctx.get() or None,
            "organization_id": getattr(record, "organization_id", None),
            "project_id": getattr(record, "project_id", None),
            "service": getattr(record, "service", "api"),
            "event": getattr(record, "event", None),
        }
        # attach extras
        for k, v in getattr(record, "__dict__", {}).items():
            if k not in payload and k not in ("args", "msg", "levelname", "levelno", "pathname",
                    "filename", "module", "exc_info", "exc_text", "stack_info", "lineno",
                    "funcName", "created", "msecs", "relativeCreated", "thread",
                    "threadName", "processName", "process"):
                try:
                    json.dumps(v)
                    payload[k] = v
                except Exception:
                    pass
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps({k: v for k, v in payload.items() if v is not None})


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())


def new_request_id() -> str:
    rid = uuid.uuid4().hex[:12]
    request_id_ctx.set(rid)
    return rid
