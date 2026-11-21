"""Utilitários para integração Lambda Proxy com o Amazon API Gateway."""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from utils.config import get_settings
from utils.errors import ValidationError


class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return int(o) if o == o.to_integral_value() else float(o)
        if isinstance(o, set):
            return sorted(o)
        return super().default(o)


def to_json(data: Any) -> str:
    return json.dumps(data, cls=DecimalEncoder, ensure_ascii=False)


def cors_headers() -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": get_settings().allowed_origin,
        "Access-Control-Allow-Headers": "Content-Type,Idempotency-Key,X-Correlation-Id",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    }


def response(status: int, body: Any, headers: dict[str, str] | None = None) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json; charset=utf-8", **cors_headers(), **(headers or {})},
        "body": to_json(body),
    }


def text_response(status: int, body: str, content_type: str, headers: dict[str, str] | None = None) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": content_type, **cors_headers(), **(headers or {})},
        "body": body,
    }


def error_response(status: int, message: str, details: list[str] | None = None, correlation_id: str | None = None) -> dict:
    body: dict[str, Any] = {"error": message}
    if details:
        body["details"] = details
    if correlation_id:
        body["correlationId"] = correlation_id
    return response(status, body)


def parse_json_body(event: dict) -> dict:
    raw = event.get("body")
    if raw in (None, ""):
        return {}
    if event.get("isBase64Encoded"):
        import base64

        raw = base64.b64decode(raw).decode("utf-8")
    try:
        data = json.loads(raw, parse_float=Decimal)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValidationError("Corpo da requisição não é um JSON válido.") from exc
    if not isinstance(data, dict):
        raise ValidationError("O corpo da requisição deve ser um objeto JSON.")
    return data


def header(event: dict, name: str) -> str | None:
    headers = event.get("headers") or {}
    lowered = {k.lower(): v for k, v in headers.items()}
    return lowered.get(name.lower())
