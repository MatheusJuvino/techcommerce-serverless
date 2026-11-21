"""Histórico de execuções das automações (exibido na interface de demonstração).

Cada execução de Lambda grava um registro com: função, gatilho (API Gateway, regra do
EventBridge ou EventBridge Scheduler), tipo de evento, resultado e duração.
Partição por dia (pk = DAY#AAAA-MM-DD) e ordenação por horário (sk); expira via TTL.
Falhas ao gravar o histórico nunca interrompem o fluxo de negócio.
"""
from __future__ import annotations

import time
import uuid
from datetime import timedelta

from boto3.dynamodb.conditions import Key

from utils import aws_clients
from utils.clock import iso, utc_now
from utils.config import get_settings
from utils.dynamo import to_dynamo
from utils.logger import get_logger

logger = get_logger(__name__)


class Trigger:
    API = "API Gateway"
    EVENTBRIDGE_RULE = "EventBridge Rule"
    SCHEDULER = "EventBridge Scheduler"


class AutomationLog:
    def __init__(self, table_name: str | None = None):
        settings = get_settings()
        self.table = aws_clients.resource("dynamodb").Table(table_name or settings.automation_log_table)
        self.ttl_days = settings.automation_log_ttl_days
        self.environment = "local-simulation" if settings.is_local else "aws"

    def record(
        self,
        function: str,
        trigger: str,
        event_type: str,
        status: str,
        summary: str,
        correlation_id: str | None = None,
        details: dict | None = None,
        duration_ms: float | None = None,
    ) -> None:
        now = utc_now()
        item = {
            "pk": f"DAY#{now.date().isoformat()}",
            "sk": f"{iso(now)}#{uuid.uuid4().hex[:8]}",
            "timestamp": iso(now),
            "function": function,
            "trigger": trigger,
            "automatic": trigger != Trigger.API,
            "eventType": event_type,
            "status": status,
            "summary": summary,
            "correlationId": correlation_id,
            "details": details or {},
            "durationMs": round(duration_ms, 1) if duration_ms is not None else None,
            "environment": self.environment,
            "expireAt": int(time.time()) + self.ttl_days * 86400,
        }
        try:
            self.table.put_item(Item=to_dynamo(item))
        except Exception:  # noqa: BLE001 - o histórico é auxiliar e não pode quebrar o fluxo
            logger.warning("Falha ao gravar histórico de automação", exc_info=True)

    def recent(self, limit: int = 50) -> list[dict]:
        today = utc_now().date()
        entries: list[dict] = []
        for offset in range(2):
            day = (today - timedelta(days=offset)).isoformat()
            page = self.table.query(
                KeyConditionExpression=Key("pk").eq(f"DAY#{day}"), ScanIndexForward=False, Limit=limit
            )
            entries.extend(page.get("Items", []))
            if len(entries) >= limit:
                break
        return entries[:limit]
