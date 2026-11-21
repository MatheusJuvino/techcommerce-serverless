"""Publicação de eventos de domínio no barramento customizado do Amazon EventBridge."""
from __future__ import annotations

import json
from typing import Callable

from models.events import build_detail
from utils import aws_clients
from utils.config import get_settings
from utils.errors import EventPublishError
from utils.http import DecimalEncoder
from utils.logger import get_logger

logger = get_logger(__name__)

# Ganchos chamados após um PutEvents bem-sucedido. Ficam vazios na AWS (lá quem roteia é o
# EventBridge). O simulador local registra aqui o seu despachante de regras.
_after_publish_hooks: list[Callable[[dict], None]] = []


def register_after_publish_hook(hook: Callable[[dict], None]) -> None:
    _after_publish_hooks.append(hook)


def clear_after_publish_hooks() -> None:
    _after_publish_hooks.clear()


class EventPublisher:
    def __init__(self, source: str, producer: str, bus_name: str | None = None):
        self.source = source
        self.producer = producer
        self.bus_name = bus_name or get_settings().event_bus_name

    def publish(self, detail_type: str, data: dict, correlation_id: str | None = None, event_id: str | None = None) -> str:
        detail = build_detail(data, producer=self.producer, correlation_id=correlation_id, event_id=event_id)
        entry = {
            "EventBusName": self.bus_name,
            "Source": self.source,
            "DetailType": detail_type,
            "Detail": json.dumps(detail, cls=DecimalEncoder, ensure_ascii=False),
        }
        try:
            result = aws_clients.client("events").put_events(Entries=[entry])
        except Exception as exc:  # erros de rede/credenciais após as retentativas do boto3
            raise EventPublishError(f"Falha ao publicar {detail_type} no EventBridge: {exc}") from exc
        if result.get("FailedEntryCount"):
            failure = result["Entries"][0]
            raise EventPublishError(
                f"EventBridge rejeitou {detail_type}: {failure.get('ErrorCode')} {failure.get('ErrorMessage')}"
            )
        aws_event_id = result["Entries"][0].get("EventId")
        logger.info(
            "Evento publicado no EventBridge",
            extra={
                "detailType": detail_type,
                "source": self.source,
                "eventBus": self.bus_name,
                "eventId": detail["metadata"]["eventId"],
                "eventBridgeId": aws_event_id,
            },
        )
        for hook in list(_after_publish_hooks):
            hook({**entry, "EventId": aws_event_id})
        return detail["metadata"]["eventId"]
