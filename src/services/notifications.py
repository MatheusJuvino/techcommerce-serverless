"""Montagem e envio das notificações operacionais pelo Amazon SNS.

Cada mensagem recebe os atributos `eventType`, `team` e `severity`. Assinaturas do tópico podem
usar *filter policies* para que cada equipe receba apenas o que lhe interessa
(ex.: logística recebe somente `team = logistics`).
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from models.events import EventType
from utils import aws_clients
from utils.config import get_settings
from utils.errors import TransientError
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Notification:
    subject: str
    message: str
    team: str
    severity: str
    event_type: str


def _ascii(text: str) -> str:
    # O Subject do SNS aceita apenas ASCII e no máximo 100 caracteres.
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return normalized.replace("\n", " ")[:99]


def build_notification(event_type: str, data: dict) -> Notification:
    order_id = data.get("orderId", "-")
    if event_type == EventType.ORDER_APPROVED:
        return Notification(
            subject=f"[TechCommerce] Pedido aprovado {order_id}",
            message=(
                f"Pedido {order_id} aprovado automaticamente.\n"
                f"Cliente: {data.get('customerName', '-')}\nValor: R$ {data.get('total', '-')}\n"
                f"Itens: {data.get('itemsCount', '-')}\nAção: iniciar separação e expedição."
            ),
            team="logistics",
            severity="INFO",
            event_type=event_type,
        )
    if event_type == EventType.ORDER_REJECTED:
        return Notification(
            subject=f"[TechCommerce] Pedido rejeitado {order_id}",
            message=(
                f"Pedido {order_id} rejeitado pelas regras automáticas.\n"
                f"Motivos: {'; '.join(data.get('reasons', [])) or '-'}\nAção: contatar o cliente."
            ),
            team="support",
            severity="WARNING",
            event_type=event_type,
        )
    if event_type == EventType.TRANSACTION_UPDATED:
        return Notification(
            subject=f"[TechCommerce] Transacao {data.get('transactionStatus', '')} pedido {order_id}",
            message=(
                f"Transação {data.get('transactionId', '-')} do pedido {order_id} atualizada para "
                f"{data.get('transactionStatus', '-')}.\nNovo status do pedido: {data.get('orderStatus', '-')}\n"
                f"Valor: R$ {data.get('amount', '-')}"
            ),
            team="finance",
            severity="INFO",
            event_type=event_type,
        )
    if event_type == EventType.PROCESSING_FAILED:
        return Notification(
            subject=f"[TechCommerce] Falha no processamento ({data.get('stage', 'desconhecido')})",
            message=(
                f"Falha na etapa {data.get('stage', '-')}.\nReferência: {data.get('reference', '-')}\n"
                f"Erro: {data.get('error', '-')}\nAção: verificar logs no CloudWatch (correlationId abaixo)."
            ),
            team="operations",
            severity="ERROR",
            event_type=event_type,
        )
    if event_type == EventType.SALES_REPORT_GENERATED:
        summary = data.get("summary", {})
        return Notification(
            subject="[TechCommerce] Relatorio de vendas gerado",
            message=(
                f"Relatório de vendas disponível em {data.get('reportUri', '-')}.\n"
                f"Gatilho: {data.get('trigger', '-')}\nPedidos no período: {summary.get('totalOrders', '-')}\n"
                f"Receita bruta aprovada: R$ {summary.get('grossRevenue', '-')}"
            ),
            team="management",
            severity="INFO",
            event_type=event_type,
        )
    raise ValueError(f"Evento {event_type} não gera notificação.")


class SnsNotifier:
    def __init__(self, topic_arn: str | None = None):
        self.topic_arn = topic_arn or get_settings().notifications_topic_arn

    def send(self, notification: Notification, correlation_id: str) -> str:
        try:
            result = aws_clients.client("sns").publish(
                TopicArn=self.topic_arn,
                Subject=_ascii(notification.subject),
                Message=f"{notification.message}\n\ncorrelationId: {correlation_id}",
                MessageAttributes={
                    "eventType": {"DataType": "String", "StringValue": notification.event_type},
                    "team": {"DataType": "String", "StringValue": notification.team},
                    "severity": {"DataType": "String", "StringValue": notification.severity},
                },
            )
        except Exception as exc:
            raise TransientError(f"Falha ao publicar no SNS: {exc}") from exc
        logger.info(
            "Notificação enviada ao SNS",
            extra={"team": notification.team, "eventType": notification.event_type, "messageId": result["MessageId"]},
        )
        return result["MessageId"]
