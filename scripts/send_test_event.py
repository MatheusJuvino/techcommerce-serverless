"""Publica eventos de teste DIRETAMENTE no barramento do EventBridge na AWS (sem passar pela API).

Usa a cadeia padrão de credenciais do boto3 (aws configure / AWS SSO / variáveis de ambiente).
Nenhuma credencial é lida ou gravada por este script.

Exemplos:
    python scripts/send_test_event.py --bus techcommerce-dev-bus transaction --order-id ORD-XXXX --status CAPTURED --amount 4079.70
    python scripts/send_test_event.py --bus techcommerce-dev-bus report --period last_24h
"""
from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone

import boto3


def detail(data: dict, producer: str) -> str:
    return json.dumps({
        "metadata": {"eventId": str(uuid.uuid4()), "correlationId": str(uuid.uuid4()),
                     "occurredAt": datetime.now(tz=timezone.utc).isoformat(), "schemaVersion": "1.0",
                     "producer": producer},
        "data": data,
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bus", required=True, help="Nome do barramento (saída EventBusName do stack)")
    parser.add_argument("--region", default=None)
    sub = parser.add_subparsers(dest="kind", required=True)
    tx = sub.add_parser("transaction")
    tx.add_argument("--order-id", required=True)
    tx.add_argument("--status", default="CAPTURED", choices=["AUTHORIZED", "CAPTURED", "DECLINED", "REFUNDED"])
    tx.add_argument("--amount", required=True)
    tx.add_argument("--transaction-id", default=None)
    report = sub.add_parser("report")
    report.add_argument("--period", default="last_24h", choices=["last_24h", "today", "yesterday", "last_7d"])
    args = parser.parse_args()

    if args.kind == "transaction":
        entry = {"Source": "techcommerce.payments", "DetailType": "TransactionStatusChanged",
                 "Detail": detail({"transactionId": args.transaction_id or f"TX-{uuid.uuid4().hex[:10].upper()}",
                                   "orderId": args.order_id, "status": args.status, "amount": args.amount,
                                   "gateway": "cli-test"}, "send_test_event")}
    else:
        entry = {"Source": "techcommerce.reports", "DetailType": "SalesReportRequested",
                 "Detail": detail({"period": args.period, "requestedBy": "cli"}, "send_test_event")}
    entry["EventBusName"] = args.bus
    result = boto3.client("events", region_name=args.region).put_events(Entries=[entry])
    print(json.dumps(result["Entries"], indent=2))
    if result.get("FailedEntryCount"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
