"""Integração ponta a ponta no ambiente LOCAL SIMULADO, via HTTP (API -> EventBridge -> Lambdas).

Valida o encadeamento automático real entre as funções, as regras lidas do template,
as retentativas assíncronas com envio à DLQ e o agendador.
"""
import json
import threading
import time
import urllib.request

import pytest

from local_runtime.runtime import LocalRuntime
from local_runtime.server import serve
from tests.conftest import VALID_ORDER

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def local_stack():
    runtime = LocalRuntime(schedule_interval_seconds=0, retry_delays=(0.1, 0.1)).start()
    server = serve(runtime, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield runtime, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    runtime.stop()


def call(base, method, path, body=None, headers=None):
    request = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body else None,
                                     headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8-sig") or "null")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def test_order_is_processed_automatically_end_to_end(local_stack):
    runtime, base = local_stack
    status, created = call(base, "POST", "/api/orders", VALID_ORDER)
    assert status == 202
    assert runtime.wait_idle()
    _, order = call(base, "GET", f"/api/orders/{created['orderId']}")
    assert order["status"] == "APPROVED"

    status, _ = call(base, "POST", "/api/transactions", {"orderId": created["orderId"], "status": "CAPTURED"})
    assert status == 202
    assert runtime.wait_idle()
    _, order = call(base, "GET", f"/api/orders/{created['orderId']}")
    assert order["status"] == "PAID"

    _, events = call(base, "GET", "/local/events")
    types = [e["detailType"] for e in events["events"]]
    for expected in ("OrderReceived", "OrderApproved", "TransactionStatusChanged", "TransactionUpdated"):
        assert expected in types
    received = next(e for e in events["events"] if e["detailType"] == "OrderReceived")
    assert received["matchedRules"][0]["target"].endswith("process-order")

    _, automations = call(base, "GET", "/api/automations?limit=100")
    notified = {a["eventType"] for a in automations["automations"] if a["function"] == "notification_dispatcher"}
    assert {"OrderApproved", "TransactionUpdated"} <= notified


def test_transient_failure_is_retried_and_sent_to_dlq(local_stack):
    runtime, base = local_stack
    payload = {**VALID_ORDER, "items": [{"sku": "SKU-FALHA-TEMPORARIA", "quantity": 1, "unitPrice": 10}]}
    _, created = call(base, "POST", "/api/orders", payload)
    time.sleep(0.5)
    assert runtime.wait_idle()
    _, dlq = call(base, "GET", "/local/dead-letters")
    entry = dlq["deadLetters"][0]
    assert entry["function"].endswith("process-order") and entry["attempts"] == 3
    assert entry["event"]["detail"]["data"]["orderId"] == created["orderId"]
    _, automations = call(base, "GET", "/api/automations?limit=100")
    statuses = [a["status"] for a in automations["automations"]]
    assert statuses.count("RETRYING") >= 3 and "SENT_TO_DLQ" in statuses


def test_scheduler_triggers_report_generation(local_stack):
    runtime, base = local_stack
    status, data = call(base, "POST", "/local/scheduler/run")
    assert status == 202 and data["triggered"][0]["target"].endswith("generate-sales-report")
    assert runtime.wait_idle()
    _, reports = call(base, "GET", "/api/reports")
    assert any("sales-report" in r["key"] for r in reports["reports"])
    _, automations = call(base, "GET", "/api/automations?limit=100")
    assert any(a["trigger"] == "EventBridge Scheduler" and a["status"] == "SUCCESS" for a in automations["automations"])
