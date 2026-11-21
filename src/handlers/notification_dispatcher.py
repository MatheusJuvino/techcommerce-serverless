"""Envia notificações operacionais pelo Amazon SNS.

Gatilho: regra do Amazon EventBridge que captura OrderApproved, OrderRejected,
TransactionUpdated, ProcessingFailed e SalesReportGenerated. Centralizar o envio em uma
única função desacopla os produtores do canal de notificação (e-mail, SMS, Slack via SNS).
"""
from __future__ import annotations

import time

from models.events import NOTIFIABLE_EVENTS, parse_eventbridge_event
from services.automation_log import AutomationLog, Trigger
from services.idempotency import IdempotencyStore, run_idempotent
from services.notifications import SnsNotifier, build_notification
from utils.logger import bind_context, get_logger

logger = get_logger(__name__)
FUNCTION = "notification_dispatcher"


def lambda_handler(event, context):
    started = time.perf_counter()
    bind_context(function_name=FUNCTION)
    audit = AutomationLog()
    domain_event = parse_eventbridge_event(event)
    bind_context(correlation_id=domain_event.correlation_id)

    if domain_event.detail_type not in NOTIFIABLE_EVENTS:
        logger.warning("Evento sem notificação configurada", extra={"detailType": domain_event.detail_type})
        return {"status": "IGNORED"}

    notification = build_notification(domain_event.detail_type, domain_event.data)

    def send() -> dict:
        message_id = SnsNotifier().send(notification, domain_event.correlation_id)
        return {"messageId": message_id, "team": notification.team, "eventType": notification.event_type}

    try:
        result, duplicate = run_idempotent(IdempotencyStore(), f"{FUNCTION}#{domain_event.event_id}", send)
    except Exception as exc:
        logger.exception("Falha ao enviar notificação; o evento será reprocessado")
        audit.record(FUNCTION, Trigger.EVENTBRIDGE_RULE, domain_event.detail_type, "RETRYING", str(exc),
                     domain_event.correlation_id, {}, (time.perf_counter() - started) * 1000)
        raise

    audit.record(
        FUNCTION,
        Trigger.EVENTBRIDGE_RULE,
        domain_event.detail_type,
        "DUPLICATE_IGNORED" if duplicate else "SUCCESS",
        f"Notificação para equipe '{notification.team}': {notification.subject}",
        domain_event.correlation_id,
        {"team": notification.team, "severity": notification.severity, "subject": notification.subject,
         "message": notification.message, "messageId": result.get("messageId")},
        (time.perf_counter() - started) * 1000,
    )
    return {**result, "duplicate": duplicate}
