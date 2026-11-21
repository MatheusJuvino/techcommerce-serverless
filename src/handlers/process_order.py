"""Processa pedidos recebidos: aplica regras de negócio e atualiza o status no DynamoDB.

Gatilho: regra do Amazon EventBridge `source = techcommerce.orders`, `detail-type = OrderReceived`.
Resultado: publica OrderApproved ou OrderRejected; o notification_dispatcher avisa a equipe
de logística (aprovados) ou de atendimento (rejeitados) via SNS.
"""
from __future__ import annotations

import time

from models.events import EventType, Source, parse_eventbridge_event
from models.order import OrderStatus
from repositories.orders_repository import OrdersRepository
from services.automation_log import AutomationLog, Trigger
from services.events import EventPublisher
from services.failures import publish_processing_failure
from services.idempotency import IdempotencyStore, run_idempotent
from services.order_processing import check_fault_injection, evaluate_order
from utils.clock import now_iso
from utils.config import get_settings
from utils.errors import InvalidTransitionError, NotFoundError, PermanentError
from utils.logger import bind_context, emit_metric, get_logger

logger = get_logger(__name__)
FUNCTION = "process_order"


def lambda_handler(event, context):
    started = time.perf_counter()
    bind_context(function_name=FUNCTION)
    audit = AutomationLog()
    domain_event = parse_eventbridge_event(event)
    bind_context(correlation_id=domain_event.correlation_id)
    order_id = domain_event.data.get("orderId", "")
    logger.info("Evento recebido do EventBridge", extra={"detailType": domain_event.detail_type, "orderId": order_id})

    def elapsed():
        return (time.perf_counter() - started) * 1000

    try:
        result, duplicate = run_idempotent(
            IdempotencyStore(), f"{FUNCTION}#{domain_event.event_id}", lambda: _process(order_id, domain_event.correlation_id)
        )
    except PermanentError as exc:
        logger.warning("Falha permanente no processamento do pedido", extra={"orderId": order_id, "error": str(exc)})
        publish_processing_failure(FUNCTION, order_id, str(exc), domain_event.correlation_id)
        audit.record(FUNCTION, Trigger.EVENTBRIDGE_RULE, domain_event.detail_type, "FAILED", str(exc),
                     domain_event.correlation_id, {"orderId": order_id}, elapsed())
        return {"status": "FAILED", "orderId": order_id, "error": str(exc)}
    except Exception as exc:
        # Falha transitória: propaga para o Lambda aplicar retentativas e, ao esgotar, enviar à DLQ.
        logger.exception("Falha transitória; o evento será reprocessado", extra={"orderId": order_id})
        audit.record(FUNCTION, Trigger.EVENTBRIDGE_RULE, domain_event.detail_type, "RETRYING", str(exc),
                     domain_event.correlation_id, {"orderId": order_id}, elapsed())
        raise

    if duplicate:
        audit.record(FUNCTION, Trigger.EVENTBRIDGE_RULE, domain_event.detail_type, "DUPLICATE_IGNORED",
                     f"Evento {domain_event.event_id} já processado; nenhuma ação repetida.",
                     domain_event.correlation_id, {"orderId": order_id}, elapsed())
        return {**result, "duplicate": True}

    emit_metric("TechCommerce", "OrdersProcessed", 1, Decision=result["status"])
    audit.record(FUNCTION, Trigger.EVENTBRIDGE_RULE, domain_event.detail_type, "SUCCESS",
                 f"Pedido {order_id} {'aprovado' if result['status'] == 'APPROVED' else 'rejeitado'} automaticamente.",
                 domain_event.correlation_id, result, elapsed())
    return result


def _process(order_id: str, correlation_id: str) -> dict:
    settings = get_settings()
    repository = OrdersRepository()
    if not order_id:
        raise NotFoundError("Evento OrderReceived sem orderId.")
    order = repository.get(order_id)
    if order is None:
        raise NotFoundError(f"Pedido {order_id} não encontrado.")
    if order["status"] != OrderStatus.RECEIVED.value:
        raise InvalidTransitionError(f"Pedido {order_id} já está com status {order['status']}.")

    check_fault_injection(order, settings)
    decision = evaluate_order(order, settings)
    new_status = OrderStatus.APPROVED.value if decision.approved else OrderStatus.REJECTED.value
    note = "Aprovado pelas regras automáticas." if decision.approved else "Rejeitado: " + " ".join(decision.reasons)
    updated = repository.update_status(
        order_id,
        new_status,
        (OrderStatus.RECEIVED.value,),
        {"at": now_iso(), "status": new_status, "actor": FUNCTION, "trigger": Trigger.EVENTBRIDGE_RULE,
         "automatic": True, "note": note},
        extra={"decisionReasons": decision.reasons},
    )
    logger.info("Status do pedido atualizado", extra={"orderId": order_id, "status": new_status})

    EventPublisher(Source.ORDERS, producer=FUNCTION).publish(
        EventType.ORDER_APPROVED if decision.approved else EventType.ORDER_REJECTED,
        {
            "orderId": order_id,
            "status": new_status,
            "total": updated["total"],
            "customerName": updated["customer"]["name"],
            "itemsCount": sum(int(i["quantity"]) for i in updated["items"]),
            "reasons": decision.reasons,
        },
        correlation_id=correlation_id,
    )
    return {"orderId": order_id, "status": new_status, "reasons": decision.reasons}
