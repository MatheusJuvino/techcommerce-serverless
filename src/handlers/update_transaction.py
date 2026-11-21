"""Atualiza automaticamente o status de transações de pagamento.

Gatilho: regra do Amazon EventBridge `source = techcommerce.payments`,
`detail-type = TransactionStatusChanged` (publicado pelo gateway de pagamento ou pela API de demonstração).

Idempotência pela chave de negócio transactionId + status: se o gateway reenviar a mesma
notificação (mesmo com outro eventId), a transação não é aplicada duas vezes.
"""
from __future__ import annotations

import time

from models.events import EventType, Source, parse_eventbridge_event
from models.transaction import resolve_transition, validate_transaction
from repositories.orders_repository import OrdersRepository
from services.automation_log import AutomationLog, Trigger
from services.events import EventPublisher
from services.failures import publish_processing_failure
from services.idempotency import IdempotencyStore, run_idempotent
from utils.clock import now_iso
from utils.errors import NotFoundError, PermanentError
from utils.logger import bind_context, emit_metric, get_logger

logger = get_logger(__name__)
FUNCTION = "update_transaction"


def lambda_handler(event, context):
    started = time.perf_counter()
    bind_context(function_name=FUNCTION)
    audit = AutomationLog()
    domain_event = parse_eventbridge_event(event)
    correlation_id = domain_event.correlation_id
    bind_context(correlation_id=correlation_id)
    reference = f"{domain_event.data.get('orderId', '-')}/{domain_event.data.get('transactionId', '-')}"

    def elapsed():
        return (time.perf_counter() - started) * 1000

    try:
        transaction = validate_transaction(domain_event.data)
        key = f"{FUNCTION}#{transaction['transactionId']}#{transaction['status']}"
        result, duplicate = run_idempotent(IdempotencyStore(), key, lambda: _apply(transaction, correlation_id))
    except PermanentError as exc:
        details = getattr(exc, "details", None)
        error = f"{exc} {' '.join(details)}" if details else str(exc)
        logger.warning("Transação não aplicada", extra={"reference": reference, "error": error})
        publish_processing_failure(FUNCTION, reference, error, correlation_id)
        audit.record(FUNCTION, Trigger.EVENTBRIDGE_RULE, domain_event.detail_type, "FAILED", error,
                     correlation_id, {"reference": reference}, elapsed())
        return {"status": "FAILED", "reference": reference, "error": error}
    except Exception as exc:
        logger.exception("Falha transitória ao atualizar transação", extra={"reference": reference})
        audit.record(FUNCTION, Trigger.EVENTBRIDGE_RULE, domain_event.detail_type, "RETRYING", str(exc),
                     correlation_id, {"reference": reference}, elapsed())
        raise

    if duplicate:
        audit.record(FUNCTION, Trigger.EVENTBRIDGE_RULE, domain_event.detail_type, "DUPLICATE_IGNORED",
                     f"Transação {reference} com status {domain_event.data.get('status')} já aplicada.",
                     correlation_id, {"reference": reference}, elapsed())
        return {**result, "duplicate": True}

    emit_metric("TechCommerce", "TransactionsUpdated", 1, TransactionStatus=result["transactionStatus"])
    audit.record(FUNCTION, Trigger.EVENTBRIDGE_RULE, domain_event.detail_type, "SUCCESS",
                 f"Transação {result['transactionId']} ({result['transactionStatus']}) aplicada; "
                 f"pedido {result['orderId']} agora {result['orderStatus']}.",
                 correlation_id, result, elapsed())
    return result


def _apply(transaction: dict, correlation_id: str) -> dict:
    repository = OrdersRepository()
    order = repository.get(transaction["orderId"])
    if order is None:
        raise NotFoundError(f"Pedido {transaction['orderId']} não encontrado para a transação {transaction['transactionId']}.")
    transition = resolve_transition(order, transaction)
    new_status = transition.new_order_status or order["status"]
    updated = repository.apply_transaction(
        order["orderId"],
        transaction,
        new_status=new_status,
        payment_status=transition.payment_status,
        expected_statuses=transition.allowed_from,
        history_entry={
            "at": now_iso(),
            "status": new_status,
            "actor": FUNCTION,
            "trigger": Trigger.EVENTBRIDGE_RULE,
            "automatic": True,
            "note": f"Transação {transaction['transactionId']} {transaction['status']} (R$ {transaction['amount']}).",
        },
    )
    result = {
        "orderId": updated["orderId"],
        "orderStatus": updated["status"],
        "transactionId": transaction["transactionId"],
        "transactionStatus": transaction["status"],
        "amount": transaction["amount"],
    }
    EventPublisher(Source.PAYMENTS, producer=FUNCTION).publish(EventType.TRANSACTION_UPDATED, result, correlation_id=correlation_id)
    return result
