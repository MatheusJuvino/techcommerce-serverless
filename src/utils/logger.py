"""Logs estruturados em JSON, prontos para consulta no CloudWatch Logs Insights.

Exemplo de consulta:
    fields @timestamp, level, message, orderId, correlationId
    | filter service = "techcommerce" and level = "ERROR"
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)
_function_name: contextvars.ContextVar[str | None] = contextvars.ContextVar("function_name", default=None)

_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}


def _default(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (set, tuple)):
        return list(value)
    return str(value)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "service": "techcommerce",
            "function": _function_name.get() or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"),
            "correlationId": _correlation_id.get(),
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=_default, ensure_ascii=False)


def _configure_root() -> None:
    root = logging.getLogger()
    if getattr(root, "_techcommerce_configured", False):
        return
    if not root.handlers:
        root.addHandler(logging.StreamHandler(sys.stdout))
    for handler in root.handlers:
        handler.setFormatter(JsonFormatter())
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    for noisy in ("botocore", "boto3", "urllib3", "moto", "werkzeug"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    root._techcommerce_configured = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    _configure_root()
    return logging.getLogger(name)


def bind_context(correlation_id: str | None = None, function_name: str | None = None) -> None:
    if correlation_id is not None:
        _correlation_id.set(correlation_id)
    if function_name is not None:
        _function_name.set(function_name)


def emit_metric(namespace: str, name: str, value: float, unit: str = "Count", **dimensions: str) -> None:
    """Publica uma métrica customizada via CloudWatch Embedded Metric Format (EMF).

    Na AWS, o CloudWatch extrai a métrica automaticamente desta linha de log,
    sem chamadas adicionais de API (custo e latência menores que PutMetricData).
    """
    record = {
        "_aws": {
            "Timestamp": int(datetime.now(tz=timezone.utc).timestamp() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": namespace,
                    "Dimensions": [list(dimensions.keys())] if dimensions else [[]],
                    "Metrics": [{"Name": name, "Unit": unit}],
                }
            ],
        },
        name: value,
        **dimensions,
    }
    print(json.dumps(record), flush=True)
