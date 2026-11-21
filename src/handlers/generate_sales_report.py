"""Gera o relatório consolidado de vendas em CSV e salva no Amazon S3.

Gatilhos:
1. Amazon EventBridge Scheduler (agendamento configurável no template; padrão diário às 06:00
   America/Sao_Paulo). O payload contém `trigger = schedule` e o horário agendado.
2. Regra do EventBridge para `SalesReportRequested` (geração sob demanda).

Ao final publica SalesReportGenerated, que dispara a notificação via SNS.
"""
from __future__ import annotations

import time

from models.events import EventType, Source, parse_eventbridge_event
from repositories.orders_repository import OrdersRepository
from repositories.reports_repository import ReportsRepository
from services.automation_log import AutomationLog, Trigger
from services.events import EventPublisher
from services.failures import publish_processing_failure
from services.idempotency import IdempotencyStore, run_idempotent
from services.reports import build_orders_csv, build_summary_csv, consolidate, report_keys, resolve_period
from utils.clock import utc_now
from utils.errors import PermanentError
from utils.logger import bind_context, emit_metric, get_logger

logger = get_logger(__name__)
FUNCTION = "generate_sales_report"


def _parse_trigger(event: dict) -> tuple[str, str, str, str]:
    """Retorna (gatilho, período, chave de idempotência, correlationId)."""
    if isinstance(event, dict) and event.get("trigger") == "schedule":
        scheduled = event.get("scheduledTime") or utc_now().strftime("%Y-%m-%dT%H:%M")
        return Trigger.SCHEDULER, event.get("period", "last_24h"), f"{FUNCTION}#schedule#{scheduled}", event.get("executionId") or scheduled
    domain_event = parse_eventbridge_event(event)
    return (
        Trigger.EVENTBRIDGE_RULE,
        domain_event.data.get("period", "last_24h"),
        f"{FUNCTION}#{domain_event.event_id}",
        domain_event.correlation_id,
    )


def lambda_handler(event, context):
    started = time.perf_counter()
    bind_context(function_name=FUNCTION)
    audit = AutomationLog()
    trigger, period, key, correlation_id = _parse_trigger(event)
    bind_context(correlation_id=correlation_id)
    logger.info("Geração de relatório iniciada", extra={"trigger": trigger, "period": period})
    event_label = "Scheduled Event" if trigger == Trigger.SCHEDULER else EventType.SALES_REPORT_REQUESTED

    def elapsed():
        return (time.perf_counter() - started) * 1000

    try:
        result, duplicate = run_idempotent(IdempotencyStore(), key, lambda: _generate(period, trigger, correlation_id))
    except PermanentError as exc:
        publish_processing_failure(FUNCTION, f"period={period}", str(exc), correlation_id)
        audit.record(FUNCTION, trigger, event_label, "FAILED", str(exc), correlation_id, {"period": period}, elapsed())
        return {"status": "FAILED", "error": str(exc)}
    except Exception as exc:
        logger.exception("Falha transitória na geração do relatório")
        audit.record(FUNCTION, trigger, event_label, "RETRYING", str(exc), correlation_id, {"period": period}, elapsed())
        raise

    if duplicate:
        audit.record(FUNCTION, trigger, event_label, "DUPLICATE_IGNORED", "Execução já realizada para este agendamento.",
                     correlation_id, {}, elapsed())
        return {**result, "duplicate": True}

    emit_metric("TechCommerce", "SalesReportsGenerated", 1, Trigger=trigger)
    audit.record(FUNCTION, trigger, event_label, "SUCCESS",
                 f"Relatório com {result['totalOrders']} pedidos salvo em {result['reportUri']}.",
                 correlation_id, result, elapsed())
    return result


def _generate(period: str, trigger: str, correlation_id: str) -> dict:
    now = utc_now()
    start, end = resolve_period(period, now)
    orders = OrdersRepository().list_between(start, end)
    summary = consolidate(orders, start, end)
    orders_key, summary_key = report_keys(now)
    reports = ReportsRepository()
    metadata = {"period": period, "trigger": trigger.replace(" ", "-").lower(), "orders": str(len(orders))}
    saved = reports.save_csv(orders_key, build_orders_csv(orders), metadata)
    reports.save_csv(summary_key, build_summary_csv(summary), metadata)
    logger.info("Relatório salvo no S3", extra={"key": orders_key, "orders": len(orders), "grossRevenue": summary["grossRevenue"]})

    result = {
        "status": "GENERATED",
        "period": period,
        "trigger": trigger,
        "totalOrders": summary["totalOrders"],
        "grossRevenue": summary["grossRevenue"],
        "reportKey": orders_key,
        "summaryKey": summary_key,
        "reportUri": saved["uri"],
    }
    EventPublisher(Source.REPORTS, producer=FUNCTION).publish(
        EventType.SALES_REPORT_GENERATED,
        {**result, "summary": {"totalOrders": summary["totalOrders"], "grossRevenue": summary["grossRevenue"],
                               "ordersByStatus": summary["ordersByStatus"]}},
        correlation_id=correlation_id,
    )
    return result
