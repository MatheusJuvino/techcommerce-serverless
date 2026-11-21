"""Fluxo 2: atualização automática de transações."""
import json

from handlers import create_order, demo_events, process_order, update_transaction
from models.events import EventType, Source
from repositories.orders_repository import OrdersRepository
from tests.conftest import VALID_ORDER, api_event, eventbridge_event, to_eventbridge


def _approved_order(published) -> str:
    body = json.loads(create_order.lambda_handler(api_event(VALID_ORDER), None)["body"])
    process_order.lambda_handler(to_eventbridge(published[-1]), None)
    return body["orderId"]


def _tx_event(order_id, status, amount="4079.70", tx_id="TX-1"):
    return eventbridge_event(EventType.TRANSACTION_STATUS_CHANGED, Source.PAYMENTS,
                             {"transactionId": tx_id, "orderId": order_id, "status": status, "amount": amount})


def test_captured_transaction_marks_order_paid(published):
    order_id = _approved_order(published)
    result = update_transaction.lambda_handler(_tx_event(order_id, "CAPTURED"), None)
    assert result["orderStatus"] == "PAID"
    order = OrdersRepository().get(order_id)
    assert order["paymentStatus"] == "CAPTURED"
    assert order["transactions"]["TX-1"]["status"] == "CAPTURED"
    assert published[-1]["DetailType"] == EventType.TRANSACTION_UPDATED


def test_refund_after_capture(published):
    order_id = _approved_order(published)
    update_transaction.lambda_handler(_tx_event(order_id, "CAPTURED"), None)
    result = update_transaction.lambda_handler(_tx_event(order_id, "REFUNDED", tx_id="TX-2"), None)
    assert result["orderStatus"] == "REFUNDED"


def test_same_transaction_with_new_event_id_is_applied_once(published):
    order_id = _approved_order(published)
    update_transaction.lambda_handler(_tx_event(order_id, "CAPTURED"), None)
    count = len(published)
    again = update_transaction.lambda_handler(_tx_event(order_id, "CAPTURED"), None)  # outro eventId
    assert again["duplicate"] is True
    assert len(published) == count
    assert len(OrdersRepository().get(order_id)["history"]) == 3


def test_invalid_transition_publishes_processing_failed(published):
    order_id = _approved_order(published)
    result = update_transaction.lambda_handler(_tx_event(order_id, "REFUNDED"), None)
    assert result["status"] == "FAILED"
    assert published[-1]["DetailType"] == EventType.PROCESSING_FAILED
    assert OrdersRepository().get(order_id)["status"] == "APPROVED"


def test_validation_and_unknown_order_failures(published):
    result = update_transaction.lambda_handler(_tx_event("ORD-X", "PAGO"), None)
    assert result["status"] == "FAILED" and "status" in result["error"]
    result = update_transaction.lambda_handler(_tx_event("ORD-INEXISTENTE", "CAPTURED"), None)
    assert result["status"] == "FAILED" and "não encontrado" in result["error"]


def test_demo_endpoint_publishes_transaction_event_with_order_total(published):
    order_id = _approved_order(published)
    event = api_event({"orderId": order_id, "status": "CAPTURED"}, resource="/transactions")
    response = demo_events.lambda_handler(event, None)
    assert response["statusCode"] == 202
    detail = json.loads(published[-1]["Detail"])
    assert published[-1]["DetailType"] == EventType.TRANSACTION_STATUS_CHANGED
    assert detail["data"]["amount"] == 4079.7
