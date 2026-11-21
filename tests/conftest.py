from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from moto import mock_aws  # noqa: E402

from local_runtime.aws_simulation import create_resources, function_environment, use_fake_credentials  # noqa: E402
from local_runtime.template_loader import load_template  # noqa: E402
from services import events as events_service  # noqa: E402
from utils import aws_clients  # noqa: E402

TEMPLATE = ROOT / "infrastructure" / "template.yaml"


@pytest.fixture
def aws(monkeypatch):
    """Ambiente AWS emulado (moto) com os recursos criados a partir do template SAM."""
    use_fake_credentials()
    with mock_aws():
        model = load_template(TEMPLATE, {"Environment": "test"})
        physical = create_resources(model)
        env = function_environment(model, physical, {"APP_ENV": "local", "ENABLE_FAULT_INJECTION": "true"})
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        aws_clients.reset_clients()
        yield physical
        aws_clients.reset_clients()


@pytest.fixture
def published(aws):
    """Captura os eventos publicados no EventBridge durante o teste."""
    captured: list[dict] = []
    events_service.clear_after_publish_hooks()
    events_service.register_after_publish_hook(captured.append)
    yield captured
    events_service.clear_after_publish_hooks()


def api_event(body=None, headers=None, method="POST", resource="/orders", path_params=None, query=None) -> dict:
    return {
        "resource": resource,
        "path": resource,
        "httpMethod": method,
        "headers": headers or {},
        "queryStringParameters": query,
        "pathParameters": path_params,
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
    }


def eventbridge_event(detail_type: str, source: str, data: dict, event_id: str | None = None) -> dict:
    return {
        "version": "0",
        "id": str(uuid.uuid4()),
        "detail-type": detail_type,
        "source": source,
        "account": "123456789012",
        "time": "2026-11-20T12:00:00Z",
        "region": "sa-east-1",
        "resources": [],
        "detail": {
            "metadata": {"eventId": event_id or str(uuid.uuid4()), "correlationId": "test-correlation"},
            "data": data,
        },
    }


def to_eventbridge(entry: dict) -> dict:
    """Converte uma entrada capturada do PutEvents no evento que o EventBridge entregaria ao Lambda."""
    return {
        "version": "0",
        "id": entry.get("EventId") or str(uuid.uuid4()),
        "detail-type": entry["DetailType"],
        "source": entry["Source"],
        "detail": json.loads(entry["Detail"]),
    }


VALID_ORDER = {
    "customer": {"name": "Maria Souza", "email": "maria@exemplo.com.br"},
    "paymentMethod": "PIX",
    "items": [
        {"sku": "SKU-NOTEBOOK-01", "name": "Notebook", "quantity": 1, "unitPrice": 3899.90},
        {"sku": "SKU-MOUSE-02", "name": "Mouse", "quantity": 2, "unitPrice": 89.90},
    ],
}
