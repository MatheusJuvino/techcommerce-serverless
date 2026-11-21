from dataclasses import replace
from decimal import Decimal

import pytest

from models.transaction import resolve_transition, validate_transaction
from services.order_processing import FAULT_INJECTION_SKU, check_fault_injection, evaluate_order
from utils.config import get_settings
from utils.errors import InvalidTransitionError, TransientError, ValidationError


def _order(total="100.00", qty=1, payment="PIX", sku="SKU-1", status="APPROVED"):
    return {"total": Decimal(total), "paymentMethod": payment, "status": status,
            "items": [{"sku": sku, "quantity": qty, "unitPrice": Decimal(total)}]}


def test_order_within_limits_is_approved():
    assert evaluate_order(_order(), get_settings()).approved


def test_order_above_value_limit_is_rejected():
    decision = evaluate_order(_order(total="10000.01"), get_settings())
    assert not decision.approved
    assert "limite" in decision.reasons[0]


def test_item_quantity_limit_and_boleto_rule():
    settings = replace(get_settings(), max_item_quantity=5)
    assert not evaluate_order(_order(qty=6), settings).approved
    assert not evaluate_order(_order(total="6000", payment="BOLETO"), get_settings()).approved


def test_fault_injection_only_when_enabled():
    order = _order(sku=FAULT_INJECTION_SKU)
    check_fault_injection(order, replace(get_settings(), enable_fault_injection=False))
    with pytest.raises(TransientError):
        check_fault_injection(order, replace(get_settings(), enable_fault_injection=True))


def test_transaction_validation():
    with pytest.raises(ValidationError):
        validate_transaction({"orderId": "ORD-1", "status": "PAID", "amount": 0})
    tx = validate_transaction({"transactionId": "TX-1", "orderId": "ORD-1", "status": "captured", "amount": "100"})
    assert tx["status"] == "CAPTURED" and tx["amount"] == Decimal("100.00")


@pytest.mark.parametrize(
    "order_status, tx_status, expected",
    [("APPROVED", "CAPTURED", "PAID"), ("APPROVED", "DECLINED", "PAYMENT_DECLINED"),
     ("PAID", "REFUNDED", "REFUNDED"), ("APPROVED", "AUTHORIZED", None)],
)
def test_allowed_transitions(order_status, tx_status, expected):
    tx = validate_transaction({"transactionId": "TX", "orderId": "O", "status": tx_status, "amount": "100"})
    assert resolve_transition(_order(status=order_status), tx).new_order_status == expected


def test_forbidden_transition_and_amount_mismatch():
    captured = validate_transaction({"transactionId": "TX", "orderId": "O", "status": "CAPTURED", "amount": "100"})
    with pytest.raises(InvalidTransitionError):
        resolve_transition(_order(status="REJECTED"), captured)
    wrong_amount = validate_transaction({"transactionId": "TX", "orderId": "O", "status": "CAPTURED", "amount": "1"})
    with pytest.raises(InvalidTransitionError):
        resolve_transition(_order(status="APPROVED"), wrong_amount)
