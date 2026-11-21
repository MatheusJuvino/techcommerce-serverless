from __future__ import annotations

from decimal import Decimal


def to_dynamo(value):
    """Converte floats em Decimal e remove valores None (o DynamoDB não aceita float)."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: to_dynamo(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [to_dynamo(v) for v in value]
    return value
