"""Acesso à tabela de pedidos no Amazon DynamoDB.

Modelo:
- Chave primária: orderId.
- GSI `ByCreatedDay` (createdDay + createdAt): permite consultar pedidos por período
  sem Scan completo da tabela (usado pelo relatório e pela listagem).
- Atualizações de status usam ConditionExpression, garantindo que transições só ocorram a
  partir dos estados esperados (controle de concorrência otimista).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from utils import aws_clients
from utils.clock import iso, now_iso
from utils.config import get_settings
from utils.errors import InvalidTransitionError, TransientError

CREATED_DAY_INDEX = "ByCreatedDay"
_TRANSIENT_CODES = {"ProvisionedThroughputExceededException", "ThrottlingException", "RequestLimitExceeded", "InternalServerError"}


def _is_conditional_failure(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


def _raise_translated(exc: ClientError):
    code = exc.response.get("Error", {}).get("Code")
    if code in _TRANSIENT_CODES:
        raise TransientError(f"DynamoDB indisponível temporariamente: {code}") from exc
    raise exc


class OrdersRepository:
    def __init__(self, table_name: str | None = None):
        self.table = aws_clients.resource("dynamodb").Table(table_name or get_settings().orders_table)

    def create(self, order: dict) -> None:
        try:
            self.table.put_item(Item=order, ConditionExpression="attribute_not_exists(orderId)")
        except ClientError as exc:
            if _is_conditional_failure(exc):
                raise InvalidTransitionError(f"Pedido {order['orderId']} já existe.") from exc
            _raise_translated(exc)

    def get(self, order_id: str) -> dict | None:
        try:
            return self.table.get_item(Key={"orderId": order_id}, ConsistentRead=True).get("Item")
        except ClientError as exc:
            _raise_translated(exc)

    def update_status(
        self,
        order_id: str,
        new_status: str,
        expected_statuses: tuple[str, ...],
        history_entry: dict,
        extra: dict | None = None,
    ) -> dict:
        """Atualiza o status de forma condicional e registra o passo no histórico do pedido."""
        names = {"#status": "status", "#history": "history", "#updatedAt": "updatedAt"}
        values = {
            ":new": new_status,
            ":entry": [history_entry],
            ":now": now_iso(),
        }
        sets = ["#status = :new", "#history = list_append(#history, :entry)", "#updatedAt = :now"]
        for idx, (field, value) in enumerate((extra or {}).items()):
            names[f"#f{idx}"] = field
            values[f":v{idx}"] = value
            sets.append(f"#f{idx} = :v{idx}")
        expected_keys = []
        for idx, status in enumerate(expected_statuses):
            values[f":e{idx}"] = status
            expected_keys.append(f":e{idx}")
        try:
            result = self.table.update_item(
                Key={"orderId": order_id},
                UpdateExpression="SET " + ", ".join(sets),
                ConditionExpression=f"attribute_exists(orderId) AND #status IN ({', '.join(expected_keys)})",
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ReturnValues="ALL_NEW",
            )
            return result["Attributes"]
        except ClientError as exc:
            if _is_conditional_failure(exc):
                raise InvalidTransitionError(
                    f"Pedido {order_id} não está em um dos status esperados {expected_statuses}."
                ) from exc
            _raise_translated(exc)

    def apply_transaction(
        self,
        order_id: str,
        transaction: dict,
        new_status: str,
        payment_status: str,
        expected_statuses: tuple[str, ...],
        history_entry: dict,
    ) -> dict:
        record = {**transaction, "processedAt": now_iso()}
        names = {
            "#status": "status",
            "#history": "history",
            "#updatedAt": "updatedAt",
            "#paymentStatus": "paymentStatus",
            "#transactions": "transactions",
            "#txId": transaction["transactionId"],
        }
        values = {
            ":new": new_status,
            ":payment": payment_status,
            ":entry": [history_entry],
            ":now": now_iso(),
            ":tx": record,
        }
        expected_keys = []
        for idx, status in enumerate(expected_statuses):
            values[f":e{idx}"] = status
            expected_keys.append(f":e{idx}")
        try:
            result = self.table.update_item(
                Key={"orderId": order_id},
                UpdateExpression=(
                    "SET #status = :new, #paymentStatus = :payment, #updatedAt = :now, "
                    "#history = list_append(#history, :entry), #transactions.#txId = :tx"
                ),
                ConditionExpression=f"attribute_exists(orderId) AND #status IN ({', '.join(expected_keys)})",
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ReturnValues="ALL_NEW",
            )
            return result["Attributes"]
        except ClientError as exc:
            if _is_conditional_failure(exc):
                raise InvalidTransitionError(f"Pedido {order_id} mudou de status durante a atualização.") from exc
            _raise_translated(exc)

    def list_between(self, start: datetime, end: datetime) -> list[dict]:
        """Retorna todos os pedidos criados no intervalo [start, end), consultando o GSI dia a dia."""
        start_iso, end_iso = iso(start), iso(end)
        orders: list[dict] = []
        day = start.astimezone(timezone.utc).date()
        last_day = end.astimezone(timezone.utc).date()
        while day <= last_day:
            orders.extend(self._query_day(day.isoformat(), start_iso, end_iso))
            day += timedelta(days=1)
        return sorted(orders, key=lambda o: o["createdAt"])

    def list_recent(self, limit: int = 50, status: str | None = None, days: int = 7) -> list[dict]:
        today = datetime.now(tz=timezone.utc).date()
        orders: list[dict] = []
        for offset in range(days):
            day = (today - timedelta(days=offset)).isoformat()
            orders.extend(self._query_day(day, None, None, status=status, descending=True, limit=limit - len(orders)))
            if len(orders) >= limit:
                break
        return orders[:limit]

    def _query_day(self, day, start_iso, end_iso, status=None, descending=False, limit=None) -> list[dict]:
        condition = Key("createdDay").eq(day)
        if start_iso and end_iso:
            condition = condition & Key("createdAt").between(start_iso, end_iso)
        kwargs = {"IndexName": CREATED_DAY_INDEX, "KeyConditionExpression": condition, "ScanIndexForward": not descending}
        if status:
            kwargs["FilterExpression"] = Attr("status").eq(status)
        items: list[dict] = []
        try:
            while True:
                page = self.table.query(**kwargs)
                for item in page.get("Items", []):
                    if end_iso and item["createdAt"] >= end_iso:
                        continue
                    items.append(item)
                if limit and len(items) >= limit:
                    return items[:limit]
                if "LastEvaluatedKey" not in page:
                    return items
                kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        except ClientError as exc:
            _raise_translated(exc)
