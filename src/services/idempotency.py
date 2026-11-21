"""Idempotência baseada em escrita condicional no DynamoDB.

EventBridge, EventBridge Scheduler e invocações assíncronas do Lambda garantem entrega
"pelo menos uma vez" (at-least-once): o mesmo evento pode chegar mais de uma vez.
Antes de executar efeitos colaterais, o consumidor tenta gravar a chave de idempotência com
`attribute_not_exists(pk)`. Somente a primeira execução obtém o "lock"; as demais recebem o
resultado já gravado e encerram sem reprocessar.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from botocore.exceptions import ClientError

from utils import aws_clients
from utils.clock import now_iso
from utils.config import get_settings
from utils.dynamo import to_dynamo
from utils.errors import IdempotencyInProgressError, PermanentError
from utils.logger import get_logger

logger = get_logger(__name__)

IN_PROGRESS = "IN_PROGRESS"
COMPLETED = "COMPLETED"


class IdempotencyStore:
    def __init__(self, table_name: str | None = None, ttl_seconds: int | None = None, lock_timeout_seconds: int = 120):
        settings = get_settings()
        self.table = aws_clients.resource("dynamodb").Table(table_name or settings.idempotency_table)
        self.ttl_seconds = ttl_seconds or settings.idempotency_ttl_seconds
        self.lock_timeout_seconds = lock_timeout_seconds

    def acquire(self, key: str) -> dict | None:
        """Retorna None se o lock foi obtido; retorna o registro anterior se já foi concluído."""
        now = int(time.time())
        try:
            self.table.put_item(
                Item={
                    "pk": key,
                    "status": IN_PROGRESS,
                    "lockExpiresAt": now + self.lock_timeout_seconds,
                    "expireAt": now + self.ttl_seconds,
                    "createdAt": now_iso(),
                },
                ConditionExpression="attribute_not_exists(pk) OR (#s = :inprogress AND lockExpiresAt < :now)",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":inprogress": IN_PROGRESS, ":now": now},
            )
            return None
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
        existing = self.table.get_item(Key={"pk": key}, ConsistentRead=True).get("Item") or {}
        if existing.get("status") == COMPLETED:
            return existing
        raise IdempotencyInProgressError(f"Chave {key} já está sendo processada por outra execução.")

    def complete(self, key: str, result: Any) -> None:
        self.table.update_item(
            Key={"pk": key},
            UpdateExpression="SET #s = :done, #r = :result, completedAt = :at",
            ExpressionAttributeNames={"#s": "status", "#r": "result"},
            ExpressionAttributeValues={":done": COMPLETED, ":result": to_dynamo(result), ":at": now_iso()},
        )

    def release(self, key: str) -> None:
        """Remove o lock após falha transitória para permitir que a retentativa execute."""
        try:
            self.table.delete_item(Key={"pk": key})
        except ClientError:
            logger.warning("Não foi possível liberar a chave de idempotência", extra={"idempotencyKey": key})


def run_idempotent(store: IdempotencyStore, key: str, operation: Callable[[], dict]) -> tuple[dict, bool]:
    """Executa `operation` uma única vez por chave. Retorna (resultado, foi_duplicado)."""
    previous = store.acquire(key)
    if previous is not None:
        logger.info("Evento duplicado ignorado (idempotência)", extra={"idempotencyKey": key})
        return previous.get("result") or {}, True
    try:
        result = operation()
    except PermanentError as exc:
        # Repetir não muda o resultado: registra a falha para que reentregas não reprocessem.
        store.complete(key, {"status": "FAILED", "error": str(exc)})
        raise
    except Exception:
        store.release(key)
        raise
    store.complete(key, result)
    return result, False
