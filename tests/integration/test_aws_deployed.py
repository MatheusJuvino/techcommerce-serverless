"""Testes de integração contra o stack REAL implantado na AWS.

Executar somente após `sam deploy`:
    $env:TECHCOMMERCE_API_URL = "https://xxxx.execute-api.sa-east-1.amazonaws.com/dev"
    pytest -m aws
"""
import json
import os
import time
import urllib.request

import pytest

from tests.conftest import VALID_ORDER

API_URL = os.environ.get("TECHCOMMERCE_API_URL", "").rstrip("/")
pytestmark = [pytest.mark.aws, pytest.mark.integration,
              pytest.mark.skipif(not API_URL, reason="TECHCOMMERCE_API_URL não definida (stack AWS não implantado)")]


def call(method, path, body=None):
    request = urllib.request.Request(API_URL + path, method=method, data=json.dumps(body).encode() if body else None,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8-sig"))


def wait_status(order_id, expected, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, order = call("GET", f"/orders/{order_id}")
        if order["status"] in expected:
            return order
        time.sleep(2)
    return order


def test_health_reports_aws_mode():
    status, health = call("GET", "/health")
    assert status == 200 and health["mode"] == "aws"


def test_order_flow_on_aws():
    status, created = call("POST", "/orders", VALID_ORDER)
    assert status == 202
    assert wait_status(created["orderId"], {"APPROVED"})["status"] == "APPROVED"
    call("POST", "/transactions", {"orderId": created["orderId"], "status": "CAPTURED"})
    assert wait_status(created["orderId"], {"PAID"})["status"] == "PAID"


def test_on_demand_report_on_aws():
    status, _ = call("POST", "/reports", {"period": "last_24h"})
    assert status == 202
    time.sleep(10)
    _, reports = call("GET", "/reports")
    assert reports["reports"]
