"""Modelo de pedido, status e validação dos dados recebidos pela API."""
from __future__ import annotations

import re
import uuid
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from utils.clock import now_iso
from utils.errors import ValidationError


class OrderStatus(str, Enum):
    RECEIVED = "RECEIVED"                  # gravado pela API, aguardando processamento assíncrono
    APPROVED = "APPROVED"                  # aprovado pelas regras de negócio (process_order)
    REJECTED = "REJECTED"                  # reprovado pelas regras de negócio
    PAID = "PAID"                          # pagamento capturado (update_transaction)
    PAYMENT_DECLINED = "PAYMENT_DECLINED"  # pagamento recusado pelo gateway
    REFUNDED = "REFUNDED"                  # pagamento estornado
    FAILED = "FAILED"                      # erro técnico ao enviar para processamento


class PaymentMethod(str, Enum):
    CREDIT_CARD = "CREDIT_CARD"
    PIX = "PIX"
    BOLETO = "BOLETO"


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SKU_RE = re.compile(r"^[A-Za-z0-9\-_.]{2,40}$")
MAX_ITEMS = 50


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() else None


def validate_order_payload(payload: dict) -> dict:
    """Valida e normaliza o pedido. Lança ValidationError com a lista completa de problemas."""
    errors: list[str] = []

    customer = payload.get("customer")
    if not isinstance(customer, dict):
        errors.append("customer: objeto obrigatório com 'name' e 'email'.")
        customer = {}
    name = str(customer.get("name", "")).strip()
    email = str(customer.get("email", "")).strip().lower()
    if not (2 <= len(name) <= 120):
        errors.append("customer.name: obrigatório, entre 2 e 120 caracteres.")
    if not EMAIL_RE.match(email):
        errors.append("customer.email: e-mail inválido.")

    payment_method = str(payload.get("paymentMethod", "")).upper()
    if payment_method not in PaymentMethod.__members__:
        errors.append(f"paymentMethod: deve ser um de {', '.join(PaymentMethod.__members__)}.")

    items_raw = payload.get("items")
    items: list[dict] = []
    if not isinstance(items_raw, list) or not items_raw:
        errors.append("items: lista obrigatória com pelo menos um item.")
        items_raw = []
    elif len(items_raw) > MAX_ITEMS:
        errors.append(f"items: no máximo {MAX_ITEMS} itens por pedido.")

    for index, item in enumerate(items_raw):
        prefix = f"items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: deve ser um objeto.")
            continue
        sku = str(item.get("sku", "")).strip()
        quantity = item.get("quantity")
        unit_price = _decimal(item.get("unitPrice"))
        item_errors = []
        if not SKU_RE.match(sku):
            item_errors.append(f"{prefix}.sku: obrigatório (2-40 caracteres alfanuméricos, '-', '_' ou '.').")
        if isinstance(quantity, bool) or not isinstance(quantity, (int, Decimal)) or int(quantity) != quantity or quantity <= 0:
            item_errors.append(f"{prefix}.quantity: inteiro maior que zero.")
        if unit_price is None or unit_price <= 0:
            item_errors.append(f"{prefix}.unitPrice: número maior que zero.")
        errors.extend(item_errors)
        if not item_errors:
            items.append(
                {
                    "sku": sku.upper(),
                    "name": str(item.get("name") or sku).strip()[:120],
                    "quantity": int(quantity),
                    "unitPrice": unit_price.quantize(Decimal("0.01")),
                }
            )

    if errors:
        raise ValidationError("Pedido inválido.", errors)

    total = sum((i["unitPrice"] * i["quantity"] for i in items), Decimal("0")).quantize(Decimal("0.01"))
    return {
        "customer": {"name": name, "email": email},
        "paymentMethod": payment_method,
        "items": items,
        "total": total,
        "currency": "BRL",
    }


def new_order(validated: dict, correlation_id: str, source_channel: str = "api") -> dict:
    created_at = now_iso()
    return {
        "orderId": f"ORD-{uuid.uuid4().hex[:12].upper()}",
        **validated,
        "status": OrderStatus.RECEIVED.value,
        "paymentStatus": "PENDING",
        "createdAt": created_at,
        "createdDay": created_at[:10],
        "updatedAt": created_at,
        "correlationId": correlation_id,
        "channel": source_channel,
        "transactions": {},
        "history": [
            {
                "at": created_at,
                "status": OrderStatus.RECEIVED.value,
                "actor": "create_order",
                "trigger": "API Gateway",
                "automatic": False,
                "note": "Pedido recebido e validado pela API.",
            }
        ],
    }
