"""Fluxo 1: recebimento (API) e processamento (EventBridge) de pedidos."""
import json
from unittest.mock import patch

import pytest

from handlers import create_order, process_order
from models.events import EventType, Source
from repositories.orders_repository import OrdersRepository
from services.automation_log import AutomationLog
from tests.conftest import VALID_ORDER, api_event, eventbridge_event, to_eventbridge
from utils.errors import EventPublishError, TransientError


def _create(published, payload=VALID_ORDER, headers=None):
    result = create_order.lambda_handler(api_event(payload, headers), None)
    return result, json.loads(result["body"])


def test_create_order_persists_and_publishes_order_received(published):
    result, body = _create(published)
    assert result["statusCode"] == 202
    order = OrdersRepository().get(body["orderId"])
    assert order["status"] == "RECEIVED"
    assert len(published) == 1
    assert published[0]["DetailType"] == EventType.ORDER_RECEIVED
    assert published[0]["Source"] == Source.ORDERS
    detail = json.loads(published[0]["Detail"])
    assert detail["data"]["orderId"] == body["orderId"]
    assert detail["metadata"]["eventId"] and detail["metadata"]["correlationId"] == body["correlationId"]


def test_create_order_rejects_invalid_payload_without_publishing(published):
    result, body = _create(published, {"customer": {}, "items": []})
    assert result["statusCode"] == 400
    assert body["details"]
    assert published == []


def test_create_order_rejects_malformed_json(published):
    event = api_event(None)
    event["body"] = "{not json"
    assert create_order.lambda_handler(event, None)["statusCode"] == 400


def test_create_order_idempotency_key_returns_same_order(published):
    _, first = _create(published, headers={"Idempotency-Key": "abc-123"})
    replay, second = _create(published, headers={"Idempotency-Key": "abc-123"})
    assert replay["statusCode"] == 200
    assert second["orderId"] == first["orderId"] and second["idempotentReplay"] is True
    assert len(published) == 1


def test_create_order_marks_failed_when_eventbridge_unavailable(published):
    with patch("handlers.create_order.EventPublisher.publish", side_effect=EventPublishError("indisponível")):
        result, body = _create(published)
    assert result["statusCode"] == 502
    orders = OrdersRepository().list_recent()
    assert orders[0]["status"] == "FAILED"


def test_process_order_approves_and_publishes(published):
    _, body = _create(published)
    result = process_order.lambda_handler(to_eventbridge(published[0]), None)
    assert result["status"] == "APPROVED"
    order = OrdersRepository().get(body["orderId"])
    assert order["status"] == "APPROVED"
    assert [h["status"] for h in order["history"]] == ["RECEIVED", "APPROVED"]
    assert order["history"][1]["automatic"] is True
    assert published[-1]["DetailType"] == EventType.ORDER_APPROVED


def test_process_order_rejects_above_limit(published):
    payload = {**VALID_ORDER, "items": [{"sku": "SKU-BIG", "quantity": 2, "unitPrice": 9000}]}
    _create(published, payload)
    result = process_order.lambda_handler(to_eventbridge(published[0]), None)
    assert result["status"] == "REJECTED" and result["reasons"]
    assert published[-1]["DetailType"] == EventType.ORDER_REJECTED


def test_process_order_is_idempotent_for_duplicate_delivery(published):
    _create(published)
    event = to_eventbridge(published[0])
    process_order.lambda_handler(event, None)
    count = len(published)
    duplicate = process_order.lambda_handler(event, None)
    assert duplicate["duplicate"] is True
    assert len(published) == count  # nenhum evento repetido
    statuses = [e["status"] for e in AutomationLog().recent()]
    assert "DUPLICATE_IGNORED" in statuses


def test_process_order_unknown_order_publishes_processing_failed(published):
    event = eventbridge_event(EventType.ORDER_RECEIVED, Source.ORDERS, {"orderId": "ORD-NAO-EXISTE"})
    result = process_order.lambda_handler(event, None)
    assert result["status"] == "FAILED"
    assert published[-1]["DetailType"] == EventType.PROCESSING_FAILED


def test_process_order_transient_failure_raises_for_retry_and_releases_lock(published):
    payload = {**VALID_ORDER, "items": [{"sku": "SKU-FALHA-TEMPORARIA", "quantity": 1, "unitPrice": 10}]}
    _, body = _create(published, payload)
    event = to_eventbridge(published[0])
    with pytest.raises(TransientError):
        process_order.lambda_handler(event, None)
    # a chave de idempotência foi liberada: a retentativa executa novamente (e falha de novo)
    with pytest.raises(TransientError):
        process_order.lambda_handler(event, None)
    assert OrdersRepository().get(body["orderId"])["status"] == "RECEIVED"


def test_event_with_invalid_shape_is_rejected(aws):
    from utils.errors import ValidationError

    with pytest.raises(ValidationError):
        process_order.lambda_handler({"foo": "bar"}, None)
