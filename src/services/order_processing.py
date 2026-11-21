"""Regras de negócio para aprovação automática de pedidos."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from utils.config import Settings
from utils.errors import TransientError

# SKU reservado para demonstrar retentativas e DLQ. Só tem efeito com ENABLE_FAULT_INJECTION=true
# (habilitado no modo local; desabilitado por padrão no template AWS).
FAULT_INJECTION_SKU = "SKU-FALHA-TEMPORARIA"


@dataclass
class Decision:
    approved: bool
    reasons: list[str] = field(default_factory=list)


def check_fault_injection(order: dict, settings: Settings) -> None:
    if settings.enable_fault_injection and any(i["sku"] == FAULT_INJECTION_SKU for i in order.get("items", [])):
        raise TransientError("Falha temporária simulada (fault injection) para demonstrar retentativas e DLQ.")


def evaluate_order(order: dict, settings: Settings) -> Decision:
    reasons: list[str] = []
    total = Decimal(str(order["total"]))
    if total > settings.max_order_value:
        reasons.append(
            f"Valor total R$ {total:.2f} acima do limite de aprovação automática (R$ {settings.max_order_value:.2f})."
        )
    for item in order.get("items", []):
        if int(item["quantity"]) > settings.max_item_quantity:
            reasons.append(
                f"Item {item['sku']} com quantidade {item['quantity']} acima do máximo por item ({settings.max_item_quantity})."
            )
    if order.get("paymentMethod") == "BOLETO" and total > Decimal("5000"):
        reasons.append("Pagamento via boleto limitado a R$ 5000.00 por pedido.")
    return Decision(approved=not reasons, reasons=reasons)
