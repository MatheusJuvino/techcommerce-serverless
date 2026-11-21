"""Consolidação de vendas e geração dos arquivos CSV."""
from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from utils.errors import ValidationError

PERIODS = ("last_24h", "today", "yesterday", "last_7d")
REVENUE_STATUSES = {"APPROVED", "PAID"}
ORDER_COLUMNS = [
    "orderId", "createdAt", "customerName", "customerEmail", "paymentMethod",
    "status", "paymentStatus", "itemsCount", "total",
]


def resolve_period(period: str, now: datetime) -> tuple[datetime, datetime]:
    now = now.astimezone(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "last_24h":
        return now - timedelta(hours=24), now
    if period == "today":
        return midnight, now
    if period == "yesterday":
        return midnight - timedelta(days=1), midnight
    if period == "last_7d":
        return now - timedelta(days=7), now
    raise ValidationError(f"Período inválido: {period}. Use um de {', '.join(PERIODS)}.")


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def consolidate(orders: list[dict], start: datetime, end: datetime) -> dict:
    by_status = Counter(o["status"] for o in orders)
    by_payment = defaultdict(lambda: {"orders": 0, "amount": Decimal("0")})
    products = defaultdict(lambda: {"quantity": 0, "amount": Decimal("0")})
    revenue_orders = [o for o in orders if o["status"] in REVENUE_STATUSES]
    gross_revenue = sum((_money(o["total"]) for o in revenue_orders), Decimal("0"))
    confirmed_revenue = sum((_money(o["total"]) for o in orders if o["status"] == "PAID"), Decimal("0"))

    for order in revenue_orders:
        bucket = by_payment[order["paymentMethod"]]
        bucket["orders"] += 1
        bucket["amount"] += _money(order["total"])
        for item in order.get("items", []):
            product = products[item["sku"]]
            product["quantity"] += int(item["quantity"])
            product["amount"] += _money(item["unitPrice"]) * int(item["quantity"])

    top_products = sorted(products.items(), key=lambda kv: kv[1]["quantity"], reverse=True)[:5]
    return {
        "periodStart": start.isoformat(),
        "periodEnd": end.isoformat(),
        "totalOrders": len(orders),
        "ordersByStatus": dict(by_status),
        "grossRevenue": gross_revenue,
        "confirmedRevenue": confirmed_revenue,
        "averageTicket": (gross_revenue / len(revenue_orders)).quantize(Decimal("0.01")) if revenue_orders else Decimal("0.00"),
        "approvalRate": (
            Decimal(len(revenue_orders) + by_status.get("REFUNDED", 0) + by_status.get("PAYMENT_DECLINED", 0))
            / len(orders) * 100
        ).quantize(Decimal("0.1")) if orders else Decimal("0.0"),
        "byPaymentMethod": {k: {"orders": v["orders"], "amount": v["amount"]} for k, v in by_payment.items()},
        "topProducts": [{"sku": sku, **values} for sku, values in top_products],
    }


def build_orders_csv(orders: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=ORDER_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for o in orders:
        writer.writerow(
            {
                "orderId": o["orderId"],
                "createdAt": o["createdAt"],
                "customerName": o["customer"]["name"],
                "customerEmail": o["customer"]["email"],
                "paymentMethod": o["paymentMethod"],
                "status": o["status"],
                "paymentStatus": o.get("paymentStatus", ""),
                "itemsCount": sum(int(i["quantity"]) for i in o.get("items", [])),
                "total": f"{_money(o['total']):.2f}",
            }
        )
    return buffer.getvalue()


def build_summary_csv(summary: dict) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["indicador", "valor"])
    writer.writerow(["periodo_inicio", summary["periodStart"]])
    writer.writerow(["periodo_fim", summary["periodEnd"]])
    writer.writerow(["total_pedidos", summary["totalOrders"]])
    for status, count in sorted(summary["ordersByStatus"].items()):
        writer.writerow([f"pedidos_{status.lower()}", count])
    writer.writerow(["receita_bruta_aprovada", f"{summary['grossRevenue']:.2f}"])
    writer.writerow(["receita_confirmada_paga", f"{summary['confirmedRevenue']:.2f}"])
    writer.writerow(["ticket_medio", f"{summary['averageTicket']:.2f}"])
    writer.writerow(["taxa_aprovacao_percentual", f"{summary['approvalRate']}"])
    for method, values in sorted(summary["byPaymentMethod"].items()):
        writer.writerow([f"receita_{method.lower()}", f"{values['amount']:.2f}"])
    for rank, product in enumerate(summary["topProducts"], start=1):
        writer.writerow([f"top{rank}_produto", f"{product['sku']} ({product['quantity']} un.)"])
    return buffer.getvalue()


def report_keys(generated_at: datetime) -> tuple[str, str]:
    stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    prefix = generated_at.strftime("reports/%Y/%m/%d")
    return f"{prefix}/sales-report-{stamp}.csv", f"{prefix}/sales-summary-{stamp}.csv"
