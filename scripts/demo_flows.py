"""Demonstração ponta a ponta dos 4 fluxos via HTTP.

Sem argumentos: sobe o ambiente LOCAL simulado numa porta livre e executa os fluxos.
Com --api-url: executa contra a API implantada na AWS (saída do stack: ApiUrl).

    python scripts/demo_flows.py
    python scripts/demo_flows.py --api-url https://abc123.execute-api.sa-east-1.amazonaws.com/dev
    python scripts/demo_flows.py --output entrega/evidencias/demo_flows_local.txt
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


class Api:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def call(self, method: str, path: str, body: dict | None = None, headers: dict | None = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self.base_url + path, data=data, method=method,
                                         headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=30) as resp:
                raw = resp.read().decode("utf-8-sig")
                status = resp.status
        except urllib.error.HTTPError as exc:
            raw, status = exc.read().decode("utf-8"), exc.code
        try:
            return status, json.loads(raw)
        except json.JSONDecodeError:
            return status, raw

    def wait_order(self, order_id: str, statuses: set[str], timeout: float = 60) -> dict:
        deadline = time.time() + timeout
        order = {}
        while time.time() < deadline:
            _, order = self.call("GET", f"/orders/{order_id}")
            if isinstance(order, dict) and order.get("status") in statuses:
                return order
            time.sleep(1)
        return order


def sample_order(name: str, items: list[tuple[str, str, int, float]], payment: str = "PIX") -> dict:
    return {
        "customer": {"name": name, "email": f"{name.split()[0].lower()}@exemplo.com.br"},
        "paymentMethod": payment,
        "items": [{"sku": s, "name": n, "quantity": q, "unitPrice": p} for s, n, q, p in items],
    }


def step(title: str):
    print(f"\n{'-' * 78}\n{title}\n{'-' * 78}")


def run(api: Api, local: bool) -> bool:
    ok = True
    _, health = api.call("GET", "/health")
    print(f"Ambiente: {health.get('mode')} | região: {health.get('region')} | barramento: {health.get('eventBus')}")
    if local:
        print("ATENÇÃO: execução LOCAL SIMULADA (moto + simulador EventBridge/Scheduler), não é AWS real.")

    step("FLUXO 1 - Recebimento, validação e processamento automático de pedido")
    status, invalid = api.call("POST", "/orders", {"customer": {"name": "X"}, "items": []})
    print(f"Pedido inválido -> HTTP {status}: {invalid.get('error')} {invalid.get('details')}")
    ok &= status == 400

    key = str(uuid.uuid4())
    status, created = api.call("POST", "/orders", sample_order("Maria Souza", [
        ("SKU-NOTEBOOK-01", "Notebook 14", 1, 3899.90), ("SKU-MOUSE-02", "Mouse sem fio", 2, 89.90)]),
        {"Idempotency-Key": key})
    print(f"Pedido válido -> HTTP {status}: {created}")
    ok &= status == 202
    status_replay, replay = api.call("POST", "/orders", sample_order("Maria Souza", [
        ("SKU-NOTEBOOK-01", "Notebook 14", 1, 3899.90), ("SKU-MOUSE-02", "Mouse sem fio", 2, 89.90)]),
        {"Idempotency-Key": key})
    print(f"Reenvio com a mesma Idempotency-Key -> HTTP {status_replay}, mesmo orderId: {replay.get('orderId') == created.get('orderId')}")
    ok &= replay.get("orderId") == created.get("orderId")

    order = api.wait_order(created["orderId"], {"APPROVED", "REJECTED"})
    print(f"Status após processamento automático (EventBridge -> process_order): {order.get('status')}")
    for h in order.get("history", []):
        print(f"   {h['at']}  {h['status']:<10} {h['actor']:<20} via {h['trigger']:<17} {'[AUTOMÁTICO]' if h.get('automatic') else ''}")
    ok &= order.get("status") == "APPROVED"

    _, rejected = api.call("POST", "/orders", sample_order("João Lima", [("SKU-SERVIDOR-99", "Servidor rack", 3, 8500.00)], "BOLETO"))
    rejected_order = api.wait_order(rejected["orderId"], {"APPROVED", "REJECTED"})
    print(f"Pedido de alto valor {rejected['orderId']}: {rejected_order.get('status')} - {rejected_order.get('decisionReasons')}")
    ok &= rejected_order.get("status") == "REJECTED"

    step("FLUXO 2 - Atualização automática de transações (TransactionStatusChanged)")
    status, tx = api.call("POST", "/transactions", {"orderId": created["orderId"], "status": "CAPTURED"})
    print(f"Evento de pagamento publicado -> HTTP {status}: {tx.get('message')}")
    paid = api.wait_order(created["orderId"], {"PAID"})
    print(f"Pedido {created['orderId']}: status={paid.get('status')} paymentStatus={paid.get('paymentStatus')}")
    ok &= paid.get("status") == "PAID"
    api.call("POST", "/transactions", {"orderId": created["orderId"], "status": "CAPTURED", "transactionId": tx.get("transactionId")})
    status, bad = api.call("POST", "/transactions", {"orderId": "ORD-INEXISTENTE", "status": "CAPTURED", "amount": 10})
    print(f"Transação para pedido inexistente publicada (deve gerar ProcessingFailed) -> HTTP {status}")

    step("FLUXO 3 - Relatório de vendas (sob demanda via evento; agendado via Scheduler)")
    status, report_req = api.call("POST", "/reports", {"period": "last_24h"})
    print(f"SalesReportRequested -> HTTP {status}: {report_req.get('message')}")
    reports = []
    for _ in range(30):
        _, data = api.call("GET", "/reports")
        reports = data.get("reports", [])
        if any("sales-summary" in r["key"] for r in reports):
            break
        time.sleep(1)
    for r in reports[:4]:
        print(f"   {r['key']} ({r['size']} bytes)")
    ok &= bool(reports)
    summary_key = next((r["key"] for r in reports if "sales-summary" in r["key"]), None)
    if summary_key:
        _, csv_text = api.call("GET", f"/reports/download?key={summary_key}")
        print("   Conteúdo do resumo consolidado:")
        for line in str(csv_text).splitlines():
            print(f"      {line}")

    step("FLUXO 4 - Notificações operacionais (SNS) e histórico de automações")
    time.sleep(3)
    _, automations = api.call("GET", "/automations?limit=100")
    entries = automations.get("automations", [])
    notifications = [e for e in entries if e["function"] == "notification_dispatcher"]
    for e in reversed(notifications):
        print(f"   [{e['status']}] {e['eventType']:<22} -> {e['summary']}")
    ok &= any(e["eventType"] == "ProcessingFailed" for e in notifications)
    ok &= any(e["eventType"] == "OrderApproved" for e in notifications)
    duplicates = [e for e in entries if e["status"] == "DUPLICATE_IGNORED"]
    print(f"\nExecuções ignoradas por idempotência: {len(duplicates)}")
    print("\nHistórico (mais recentes primeiro):")
    for e in entries[:25]:
        auto = "AUTO" if e.get("automatic") else "API "
        print(f"   {e['timestamp']} {auto} {e['trigger']:<21} {e['function']:<24} {e['status']:<18} {e['eventType']}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", help="URL base da API na AWS (sem barra final).")
    parser.add_argument("--output", help="Também grava a saída neste arquivo (evidência).")
    args = parser.parse_args()

    runtime = server = None
    if args.api_url:
        api, local = Api(args.api_url), False
    else:
        from local_runtime.runtime import LocalRuntime
        from local_runtime.server import serve

        runtime = LocalRuntime(schedule_interval_seconds=0).start()
        server = serve(runtime, port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        api, local = Api(f"http://127.0.0.1:{server.server_address[1]}/api"), True

    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer) if args.output else redirect_stdout(sys.stdout):
            print(f"Execução: {datetime.now().isoformat(timespec='seconds')}  |  alvo: {api.base_url}")
            success = run(api, local)
            print(f"\nRESULTADO: {'TODOS OS FLUXOS OK' if success else 'HÁ FALHAS - verifique acima'}")
    finally:
        if server:
            server.shutdown()
        if runtime:
            runtime.stop()
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(buffer.getvalue(), encoding="utf-8")
        print(buffer.getvalue())
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
