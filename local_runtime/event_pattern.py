"""Implementação local (subconjunto) da correspondência de padrões do Amazon EventBridge.

Suporta: lista de valores exatos, objetos aninhados, `prefix`, `anything-but`, `exists`
e `numeric` — suficiente para as regras definidas no template.
"""
from __future__ import annotations

import operator

_MISSING = object()
_NUMERIC_OPS = {"<": operator.lt, "<=": operator.le, "=": operator.eq, ">=": operator.ge, ">": operator.gt}


def matches(pattern: dict, event: dict) -> bool:
    for key, rule in pattern.items():
        value = event.get(key, _MISSING) if isinstance(event, dict) else _MISSING
        if isinstance(rule, dict):
            if not isinstance(value, dict) or not matches(rule, value):
                return False
        elif isinstance(rule, list):
            if not _match_list(rule, value):
                return False
        else:
            raise ValueError(f"Padrão inválido em '{key}': valores devem ser listas ou objetos.")
    return True


def _match_list(rules: list, value) -> bool:
    values = value if isinstance(value, list) else [value]
    for rule in rules:
        if isinstance(rule, dict):
            if "exists" in rule:
                if bool(rule["exists"]) == (value is not _MISSING):
                    return True
                continue
            if value is _MISSING:
                continue
            if "prefix" in rule and any(isinstance(v, str) and v.startswith(rule["prefix"]) for v in values):
                return True
            if "anything-but" in rule:
                excluded = rule["anything-but"]
                excluded = excluded if isinstance(excluded, list) else [excluded]
                if all(v not in excluded for v in values):
                    return True
            if "numeric" in rule and any(_numeric(rule["numeric"], v) for v in values):
                return True
        elif value is not _MISSING and rule in values:
            return True
    return False


def _numeric(conditions: list, value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    pairs = zip(conditions[::2], conditions[1::2])
    return all(_NUMERIC_OPS[op](value, threshold) for op, threshold in pairs)
