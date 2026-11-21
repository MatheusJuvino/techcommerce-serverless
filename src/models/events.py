"""Contrato dos eventos de domínio trafegados no Amazon EventBridge.

Todo evento possui o envelope:
    detail = {
        "metadata": {"eventId", "correlationId", "occurredAt", "schemaVersion", "producer"},
        "data": {...}
    }
O `eventId` é gerado pelo produtor e é a base da idempotência dos consumidores: mesmo que
o produtor reenvie o evento (gerando outro `id` no EventBridge), o `eventId` se mantém.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from utils.clock import now_iso
from utils.errors import ValidationError

SCHEMA_VERSION = "1.0"


class Source:
    ORDERS = "techcommerce.orders"
    PAYMENTS = "techcommerce.payments"
    REPORTS = "techcommerce.reports"
    OPERATIONS = "techcommerce.operations"


class EventType:
    ORDER_RECEIVED = "OrderReceived"
    ORDER_APPROVED = "OrderApproved"
    ORDER_REJECTED = "OrderRejected"
    TRANSACTION_STATUS_CHANGED = "TransactionStatusChanged"
    TRANSACTION_UPDATED = "TransactionUpdated"
    SALES_REPORT_REQUESTED = "SalesReportRequested"
    SALES_REPORT_GENERATED = "SalesReportGenerated"
    PROCESSING_FAILED = "ProcessingFailed"


NOTIFIABLE_EVENTS = (
    EventType.ORDER_APPROVED,
    EventType.ORDER_REJECTED,
    EventType.TRANSACTION_UPDATED,
    EventType.PROCESSING_FAILED,
    EventType.SALES_REPORT_GENERATED,
)


def build_detail(data: dict, producer: str, correlation_id: str | None = None, event_id: str | None = None) -> dict:
    return {
        "metadata": {
            "eventId": event_id or str(uuid.uuid4()),
            "correlationId": correlation_id or str(uuid.uuid4()),
            "occurredAt": now_iso(),
            "schemaVersion": SCHEMA_VERSION,
            "producer": producer,
        },
        "data": data,
    }


@dataclass
class DomainEvent:
    id: str
    detail_type: str
    source: str
    time: str
    metadata: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)

    @property
    def event_id(self) -> str:
        return self.metadata.get("eventId") or self.id

    @property
    def correlation_id(self) -> str:
        return self.metadata.get("correlationId") or self.id


def parse_eventbridge_event(event: dict) -> DomainEvent:
    """Converte o evento entregue pelo EventBridge ao Lambda no modelo de domínio."""
    if not isinstance(event, dict) or "detail-type" not in event or "detail" not in event:
        raise ValidationError("Evento não está no formato do Amazon EventBridge.")
    detail = event.get("detail") or {}
    if not isinstance(detail, dict):
        raise ValidationError("Campo 'detail' do evento deve ser um objeto.")
    return DomainEvent(
        id=event.get("id", str(uuid.uuid4())),
        detail_type=event["detail-type"],
        source=event.get("source", ""),
        time=event.get("time", now_iso()),
        metadata=detail.get("metadata") or {},
        data=detail.get("data") or {},
    )
