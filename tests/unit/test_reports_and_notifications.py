import csv
import io
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from models.events import NOTIFIABLE_EVENTS, EventType
from services.notifications import _ascii, build_notification
from services.reports import build_orders_csv, build_summary_csv, consolidate, report_keys, resolve_period
from utils.errors import ValidationError

NOW = datetime(2026, 11, 20, 15, 30, tzinfo=timezone.utc)


def _order(order_id, status, total, sku="SKU-A", qty=1, payment="PIX"):
    return {"orderId": order_id, "createdAt": "2026-11-20T10:00:00.000Z", "status": status, "paymentStatus": "PENDING",
            "paymentMethod": payment, "total": Decimal(total), "customer": {"name": "Cliente", "email": "c@x.com"},
            "items": [{"sku": sku, "quantity": qty, "unitPrice": Decimal(total) / qty}]}


def test_resolve_period():
    start, end = resolve_period("yesterday", NOW)
    assert start.isoformat().startswith("2026-11-19T00:00") and end.isoformat().startswith("2026-11-20T00:00")
    start, end = resolve_period("last_24h", NOW)
    assert (end - start).total_seconds() == 86400
    with pytest.raises(ValidationError):
        resolve_period("sempre", NOW)


def test_consolidation_counts_only_approved_and_paid_as_revenue():
    orders = [_order("1", "PAID", "100.00", qty=2), _order("2", "APPROVED", "50.00", payment="CREDIT_CARD"),
              _order("3", "REJECTED", "9999.00")]
    summary = consolidate(orders, NOW, NOW)
    assert summary["totalOrders"] == 3
    assert summary["grossRevenue"] == Decimal("150.00")
    assert summary["confirmedRevenue"] == Decimal("100.00")
    assert summary["averageTicket"] == Decimal("75.00")
    assert summary["ordersByStatus"] == {"PAID": 1, "APPROVED": 1, "REJECTED": 1}
    assert summary["topProducts"][0] == {"sku": "SKU-A", "quantity": 3, "amount": Decimal("150.00")}


def test_empty_report_is_valid():
    summary = consolidate([], NOW, NOW)
    assert summary["totalOrders"] == 0 and summary["averageTicket"] == Decimal("0.00")
    assert "total_pedidos,0" in build_summary_csv(summary)


def test_csv_outputs():
    orders = [_order("ORD-1", "PAID", "100.00")]
    rows = list(csv.DictReader(io.StringIO(build_orders_csv(orders))))
    assert rows[0]["orderId"] == "ORD-1" and rows[0]["total"] == "100.00"
    summary_rows = dict(csv.reader(io.StringIO(build_summary_csv(consolidate(orders, NOW, NOW)))))
    assert summary_rows["receita_bruta_aprovada"] == "100.00"
    orders_key, summary_key = report_keys(NOW)
    assert orders_key == "reports/2026/11/20/sales-report-20261120T153000Z.csv"
    assert summary_key.endswith("sales-summary-20261120T153000Z.csv")


@pytest.mark.parametrize(
    "event_type, team",
    [(EventType.ORDER_APPROVED, "logistics"), (EventType.ORDER_REJECTED, "support"),
     (EventType.TRANSACTION_UPDATED, "finance"), (EventType.PROCESSING_FAILED, "operations"),
     (EventType.SALES_REPORT_GENERATED, "management")],
)
def test_every_notifiable_event_has_a_team(event_type, team):
    assert event_type in NOTIFIABLE_EVENTS
    notification = build_notification(event_type, {"orderId": "ORD-1", "summary": {}})
    assert notification.team == team
    assert len(_ascii(notification.subject)) < 100


def test_sns_subject_is_ascii():
    assert _ascii("Relatório de transação\nnovo") == "Relatorio de transacao novo"
