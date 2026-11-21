from decimal import Decimal

import pytest

from models.order import OrderStatus, new_order, validate_order_payload
from tests.conftest import VALID_ORDER
from utils.errors import ValidationError


def test_valid_order_is_normalized_and_total_calculated():
    result = validate_order_payload(VALID_ORDER)
    assert result["total"] == Decimal("4079.70")
    assert result["customer"]["email"] == "maria@exemplo.com.br"
    assert result["items"][0]["sku"] == "SKU-NOTEBOOK-01"
    assert result["currency"] == "BRL"


def test_invalid_order_reports_all_errors():
    with pytest.raises(ValidationError) as exc:
        validate_order_payload({"customer": {"name": "X", "email": "invalido"}, "paymentMethod": "CHEQUE", "items": []})
    details = " ".join(exc.value.details)
    assert "customer.name" in details
    assert "customer.email" in details
    assert "paymentMethod" in details
    assert "items" in details


@pytest.mark.parametrize(
    "item, field",
    [
        ({"sku": "A", "quantity": 1, "unitPrice": 10}, "sku"),
        ({"sku": "SKU-1", "quantity": 0, "unitPrice": 10}, "quantity"),
        ({"sku": "SKU-1", "quantity": 1.5, "unitPrice": 10}, "quantity"),
        ({"sku": "SKU-1", "quantity": True, "unitPrice": 10}, "quantity"),
        ({"sku": "SKU-1", "quantity": 1, "unitPrice": -5}, "unitPrice"),
        ({"sku": "SKU-1", "quantity": 1, "unitPrice": "abc"}, "unitPrice"),
    ],
)
def test_item_validation(item, field):
    payload = {**VALID_ORDER, "items": [item]}
    with pytest.raises(ValidationError) as exc:
        validate_order_payload(payload)
    assert any(f"items[0].{field}" in d for d in exc.value.details)


def test_new_order_starts_received_with_history():
    order = new_order(validate_order_payload(VALID_ORDER), "corr-1")
    assert order["orderId"].startswith("ORD-")
    assert order["status"] == OrderStatus.RECEIVED.value
    assert order["createdDay"] == order["createdAt"][:10]
    assert order["history"][0]["actor"] == "create_order"
