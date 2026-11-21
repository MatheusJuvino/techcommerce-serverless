"""POST /orders — recebe, valida e registra o pedido; publica OrderReceived no EventBridge.

Gatilho: Amazon API Gateway (integração Lambda Proxy).
A resposta é 202 Accepted: o processamento continua de forma assíncrona e automática,
orquestrado pelo EventBridge, sem que o cliente precise aguardar.
"""
from __future__ import annotations

import time
import uuid

from models.events import EventType, Source
from models.order import OrderStatus, new_order, validate_order_payload
from repositories.orders_repository import OrdersRepository
from services.automation_log import AutomationLog, Trigger
from services.events import EventPublisher
from services.idempotency import IdempotencyStore
from utils.errors import IdempotencyInProgressError, TechCommerceError, ValidationError
from utils.http import error_response, header, parse_json_body, response
from utils.logger import bind_context, get_logger

logger = get_logger(__name__)
FUNCTION = "create_order"


def lambda_handler(event, context):
    started = time.perf_counter()
    correlation_id = header(event, "X-Correlation-Id") or str(uuid.uuid4())
    bind_context(correlation_id=correlation_id, function_name=FUNCTION)
    audit = AutomationLog()

    try:
        payload = parse_json_body(event)
        validated = validate_order_payload(payload)
    except ValidationError as exc:
        logger.info("Pedido rejeitado na validação", extra={"errors": exc.details})
        audit.record(FUNCTION, Trigger.API, "POST /orders", "VALIDATION_ERROR", str(exc), correlation_id,
                     {"errors": exc.details}, (time.perf_counter() - started) * 1000)
        return error_response(400, str(exc), exc.details, correlation_id)

    idempotency_key = header(event, "Idempotency-Key")
    store = IdempotencyStore()
    store_key = f"create_order#{idempotency_key}" if idempotency_key else None
    if store_key:
        try:
            previous = store.acquire(store_key)
        except IdempotencyInProgressError:
            return error_response(409, "Requisição com esta Idempotency-Key ainda está em processamento.", correlation_id=correlation_id)
        if previous:
            logger.info("Requisição repetida: devolvendo pedido já criado", extra={"idempotencyKey": idempotency_key})
            return response(200, {**previous["result"], "idempotentReplay": True}, {"Idempotent-Replay": "true"})

    order = new_order(validated, correlation_id)
    repository = OrdersRepository()
    try:
        repository.create(order)
        logger.info("Pedido gravado no DynamoDB", extra={"orderId": order["orderId"], "total": order["total"]})
        EventPublisher(Source.ORDERS, producer=FUNCTION).publish(
            EventType.ORDER_RECEIVED,
            {
                "orderId": order["orderId"],
                "total": order["total"],
                "paymentMethod": order["paymentMethod"],
                "customerEmail": order["customer"]["email"],
                "itemsCount": sum(i["quantity"] for i in order["items"]),
            },
            correlation_id=correlation_id,
        )
    except TechCommerceError as exc:
        logger.error("Falha ao registrar/publicar pedido", extra={"orderId": order["orderId"], "error": str(exc)})
        if store_key:
            store.release(store_key)
        try:
            repository.update_status(
                order["orderId"], OrderStatus.FAILED.value, (OrderStatus.RECEIVED.value,),
                {"at": order["createdAt"], "status": OrderStatus.FAILED.value, "actor": FUNCTION,
                 "trigger": Trigger.API, "automatic": False, "note": f"Falha ao enviar para processamento: {exc}"},
            )
        except Exception:  # noqa: BLE001
            logger.exception("Não foi possível marcar o pedido como FAILED")
        audit.record(FUNCTION, Trigger.API, "POST /orders", "ERROR", str(exc), correlation_id,
                     {"orderId": order["orderId"]}, (time.perf_counter() - started) * 1000)
        return error_response(502, "Não foi possível enviar o pedido para processamento. Tente novamente.",
                              correlation_id=correlation_id)

    body = {
        "orderId": order["orderId"],
        "status": order["status"],
        "total": order["total"],
        "correlationId": correlation_id,
        "message": "Pedido recebido. O processamento seguirá automaticamente via Amazon EventBridge.",
    }
    if store_key:
        store.complete(store_key, body)
    audit.record(FUNCTION, Trigger.API, "POST /orders", "SUCCESS",
                 f"Pedido {order['orderId']} validado, gravado e evento OrderReceived publicado.",
                 correlation_id, {"orderId": order["orderId"]}, (time.perf_counter() - started) * 1000)
    return response(202, body)
