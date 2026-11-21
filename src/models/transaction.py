"""Máquina de estados das transações de pagamento e seu efeito sobre o pedido."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from models.order import OrderStatus, _decimal
from utils.errors import InvalidTransitionError, ValidationError


@dataclass(frozen=True)
class Transition:
    allowed_from: tuple[str, ...]
    new_order_status: str | None  # None = mantém o status atual do pedido
    payment_status: str


TRANSITIONS: dict[str, Transition] = {
    "AUTHORIZED": Transition((OrderStatus.APPROVED.value,), None, "AUTHORIZED"),
    "CAPTURED": Transition((OrderStatus.APPROVED.value,), OrderStatus.PAID.value, "CAPTURED"),
    "DECLINED": Transition((OrderStatus.APPROVED.value,), OrderStatus.PAYMENT_DECLINED.value, "DECLINED"),
    "REFUNDED": Transition((OrderStatus.PAID.value,), OrderStatus.REFUNDED.value, "REFUNDED"),
}


def validate_transaction(data: dict) -> dict:
    errors = []
    transaction_id = str(data.get("transactionId", "")).strip()
    order_id = str(data.get("orderId", "")).strip()
    status = str(data.get("status", "")).strip().upper()
    amount = _decimal(data.get("amount"))
    if not transaction_id:
        errors.append("transactionId: obrigatório.")
    if not order_id:
        errors.append("orderId: obrigatório.")
    if status not in TRANSITIONS:
        errors.append(f"status: deve ser um de {', '.join(TRANSITIONS)}.")
    if amount is None or amount <= 0:
        errors.append("amount: número maior que zero.")
    if errors:
        raise ValidationError("Evento de transação inválido.", errors)
    return {
        "transactionId": transaction_id,
        "orderId": order_id,
        "status": status,
        "amount": amount.quantize(Decimal("0.01")),
        "gateway": str(data.get("gateway") or "simulated-gateway"),
    }


def resolve_transition(order: dict, transaction: dict) -> Transition:
    transition = TRANSITIONS[transaction["status"]]
    if order["status"] not in transition.allowed_from:
        raise InvalidTransitionError(
            f"Transação {transaction['status']} não é permitida para pedido com status {order['status']} "
            f"(permitido: {', '.join(transition.allowed_from)})."
        )
    if transaction["status"] in ("CAPTURED", "AUTHORIZED") and Decimal(str(order["total"])) != transaction["amount"]:
        raise InvalidTransitionError(
            f"Valor da transação ({transaction['amount']}) diverge do total do pedido ({order['total']})."
        )
    return transition
