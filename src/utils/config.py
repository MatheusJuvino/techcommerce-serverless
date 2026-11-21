"""Configuração das funções, lida exclusivamente de variáveis de ambiente.

Nenhuma credencial é lida aqui: em produção a função usa a role IAM de execução;
no modo local o simulador define credenciais fictícias para o moto.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal

LOCAL_ENV = "local"


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "sim", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str
    region: str
    orders_table: str
    idempotency_table: str
    automation_log_table: str
    event_bus_name: str
    notifications_topic_arn: str
    reports_bucket: str
    max_order_value: Decimal
    max_item_quantity: int
    enable_fault_injection: bool
    allowed_origin: str
    idempotency_ttl_seconds: int
    automation_log_ttl_days: int

    @property
    def is_local(self) -> bool:
        return self.app_env == LOCAL_ENV


def get_settings() -> Settings:
    env = os.environ
    return Settings(
        app_env=env.get("APP_ENV", LOCAL_ENV),
        region=env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or "sa-east-1",
        orders_table=env.get("ORDERS_TABLE", "techcommerce-local-orders"),
        idempotency_table=env.get("IDEMPOTENCY_TABLE", "techcommerce-local-idempotency"),
        automation_log_table=env.get("AUTOMATION_LOG_TABLE", "techcommerce-local-automation-log"),
        event_bus_name=env.get("EVENT_BUS_NAME", "techcommerce-local-bus"),
        notifications_topic_arn=env.get("NOTIFICATIONS_TOPIC_ARN", ""),
        reports_bucket=env.get("REPORTS_BUCKET", "techcommerce-local-reports"),
        max_order_value=Decimal(env.get("MAX_ORDER_VALUE", "10000")),
        max_item_quantity=int(env.get("MAX_ITEM_QUANTITY", "50")),
        enable_fault_injection=_bool(env.get("ENABLE_FAULT_INJECTION"), default=False),
        allowed_origin=env.get("ALLOWED_ORIGIN", "*"),
        idempotency_ttl_seconds=int(env.get("IDEMPOTENCY_TTL_SECONDS", "86400")),
        automation_log_ttl_days=int(env.get("AUTOMATION_LOG_TTL_DAYS", "30")),
    )
