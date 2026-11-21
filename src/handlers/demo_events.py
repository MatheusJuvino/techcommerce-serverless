"""Endpoints de demonstração que PUBLICAM eventos no EventBridge (não executam a lógica).

POST /transactions -> simula o gateway de pagamento publicando TransactionStatusChanged.
POST /reports      -> solicita um relatório sob demanda publicando SalesReportRequested.

A lógica continua sendo executada pelas funções acionadas pelas regras do EventBridge,
exatamente como aconteceria com um produtor externo. Pode ser desabilitada em produção
pelo parâmetro EnableDemoEndpoints do template.
"""
from __future__ import annotations

import time
import uuid

from models.events import EventType, Source
from models.transaction import TRANSITIONS
from repositories.orders_repository import OrdersRepository
from services.automation_log import AutomationLog, Trigger
from services.events import EventPublisher
from services.reports import PERIODS
from utils.errors import TechCommerceError, ValidationError
from utils.http import error_response, header, parse_json_body, response
from utils.logger import bind_context, get_logger

logger = get_logger(__name__)
FUNCTION = "demo_events"


def lambda_handler(event, context):
    started = time.perf_counter()
    correlation_id = header(event, "X-Correlation-Id") or str(uuid.uuid4())
    bind_context(correlation_id=correlation_id, function_name=FUNCTION)
    route = f"{event.get('httpMethod')} {event.get('resource')}"
    try:
        body = parse_json_body(event)
        if route == "POST /transactions":
            result = _publish_transaction(body, correlation_id)
        elif route == "POST /reports":
            result = _request_report(body, correlation_id)
        else:
            return error_response(404, f"Rota não encontrada: {route}")
    except ValidationError as exc:
        return error_response(400, str(exc), exc.details, correlation_id)
    except TechCommerceError as exc:
        logger.error("Falha ao publicar evento de demonstração", extra={"error": str(exc)})
        return error_response(502, str(exc), correlation_id=correlation_id)

    AutomationLog().record(FUNCTION, Trigger.API, route, "SUCCESS", result["message"], correlation_id,
                           result, (time.perf_counter() - started) * 1000)
    return response(202, {**result, "correlationId": correlation_id})


def _publish_transaction(body: dict, correlation_id: str) -> dict:
    order_id = str(body.get("orderId", "")).strip()
    status = str(body.get("status", "")).upper()
    if not order_id or status not in TRANSITIONS:
        raise ValidationError("Informe orderId e status válido.", [f"status: um de {', '.join(TRANSITIONS)}"])
    amount = body.get("amount")
    if amount in (None, ""):
        order = OrdersRepository().get(order_id)
        amount = order["total"] if order else "0.01"
    transaction_id = str(body.get("transactionId") or f"TX-{uuid.uuid4().hex[:10].upper()}")
    event_id = EventPublisher(Source.PAYMENTS, producer="payment-gateway-simulator").publish(
        EventType.TRANSACTION_STATUS_CHANGED,
        {"transactionId": transaction_id, "orderId": order_id, "status": status, "amount": amount,
         "gateway": "payment-gateway-simulator"},
        correlation_id=correlation_id,
    )
    return {
        "eventId": event_id,
        "transactionId": transaction_id,
        "message": f"Evento TransactionStatusChanged ({status}) publicado para o pedido {order_id}.",
    }


def _request_report(body: dict, correlation_id: str) -> dict:
    period = str(body.get("period") or "last_24h")
    if period not in PERIODS:
        raise ValidationError("Período inválido.", [f"period: um de {', '.join(PERIODS)}"])
    event_id = EventPublisher(Source.REPORTS, producer=FUNCTION).publish(
        EventType.SALES_REPORT_REQUESTED, {"period": period, "requestedBy": "demo-console"}, correlation_id=correlation_id
    )
    return {"eventId": event_id, "message": f"Evento SalesReportRequested publicado (período {period})."}
