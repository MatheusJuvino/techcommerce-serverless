"""Publicação padronizada do evento ProcessingFailed (gera notificação para a equipe de operações)."""
from __future__ import annotations

from models.events import EventType, Source
from services.events import EventPublisher
from utils.logger import get_logger

logger = get_logger(__name__)


def publish_processing_failure(stage: str, reference: str, error: str, correlation_id: str | None) -> None:
    try:
        EventPublisher(Source.OPERATIONS, producer=stage).publish(
            EventType.PROCESSING_FAILED,
            {"stage": stage, "reference": reference, "error": error},
            correlation_id=correlation_id,
        )
    except Exception:  # noqa: BLE001 - não mascarar o erro original
        logger.exception("Não foi possível publicar ProcessingFailed", extra={"stage": stage, "reference": reference})
