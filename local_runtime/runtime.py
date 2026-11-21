"""Orquestrador do ambiente local: AWS emulada + EventBridge local + Scheduler local + API local."""
from __future__ import annotations

import importlib
import json
import os
import queue
import re
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
from moto import mock_aws

from local_runtime.aws_simulation import LOCAL_REGION, create_resources, function_environment, use_fake_credentials
from local_runtime.event_pattern import matches
from local_runtime.template_loader import FunctionDef, ScheduleDef, load_template

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
TEMPLATE_PATH = PROJECT_ROOT / "infrastructure" / "template.yaml"
ACCOUNT_ID = "123456789012"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


class LocalLambdaContext:
    def __init__(self, fn: FunctionDef, timeout_seconds: int = 15):
        self.function_name = fn.function_name
        self.function_version = "$LATEST"
        self.memory_limit_in_mb = 256
        self.invoked_function_arn = f"arn:aws:lambda:{LOCAL_REGION}:{ACCOUNT_ID}:function:{fn.function_name}"
        self.aws_request_id = str(uuid.uuid4())
        self.log_group_name = f"/aws/lambda/{fn.function_name}"
        self.log_stream_name = "local"
        self._deadline = time.time() + timeout_seconds

    def get_remaining_time_in_millis(self) -> int:
        return max(0, int((self._deadline - time.time()) * 1000))


@dataclass
class _Invocation:
    fn: FunctionDef
    payload: dict
    origin: str
    attempt: int = 0


class LocalRuntime:
    def __init__(self, schedule_interval_seconds: int = 120, retry_delays: tuple[float, ...] = (2.0, 4.0), workers: int = 2):
        self.schedule_interval_seconds = schedule_interval_seconds
        self.retry_delays = retry_delays
        self.workers = workers
        self.model = load_template(TEMPLATE_PATH, overrides={"Environment": "local"})
        self.functions = self.model.functions
        self.routes = self._compile_routes()
        self.rules = [(fn, rule) for fn in self.functions.values() for rule in fn.rules]
        self.schedules: list[tuple[FunctionDef, ScheduleDef]] = [
            (fn, s) for fn in self.functions.values() for s in fn.schedules
        ]
        self.event_trace: deque[dict] = deque(maxlen=300)
        self.dead_letters: deque[dict] = deque(maxlen=100)
        self.invocations: queue.Queue[_Invocation | None] = queue.Queue()
        self.scheduler_state = {"lastRunAt": None, "nextRunAt": None, "runs": 0}
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._pending = 0
        self._pending_lock = threading.Lock()
        self._mock = None
        self.physical: dict[str, str] = {}

    # ------------------------------------------------------------------ ciclo de vida
    def start(self) -> "LocalRuntime":
        use_fake_credentials()
        self._mock = mock_aws()
        self._mock.start()
        self.physical = create_resources(self.model)
        os.environ.update(
            function_environment(
                self.model, self.physical, {"APP_ENV": "local", "ENABLE_FAULT_INJECTION": "true", "LOG_LEVEL": "INFO"}
            )
        )
        from utils import aws_clients
        from services import events as events_service

        aws_clients.reset_clients()
        events_service.clear_after_publish_hooks()
        events_service.register_after_publish_hook(self._on_event_published)

        for index in range(self.workers):
            thread = threading.Thread(target=self._worker, name=f"lambda-async-{index}", daemon=True)
            thread.start()
            self._threads.append(thread)
        if self.schedule_interval_seconds > 0 and self.schedules:
            thread = threading.Thread(target=self._scheduler_loop, name="eventbridge-scheduler", daemon=True)
            thread.start()
            self._threads.append(thread)
        return self

    def stop(self) -> None:
        self._stop.set()
        for _ in range(self.workers):
            self.invocations.put(None)
        from services import events as events_service

        events_service.clear_after_publish_hooks()
        if self._mock:
            self._mock.stop()
            self._mock = None

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Aguarda até que não haja invocações assíncronas pendentes (útil em testes)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._pending_lock:
                if self._pending == 0:
                    return True
            time.sleep(0.05)
        return False

    # ------------------------------------------------------------------ invocação de funções
    def invoke(self, fn: FunctionDef, payload: dict):
        module_name, handler_name = fn.handler.rsplit(".", 1)
        handler = getattr(importlib.import_module(module_name), handler_name)
        return handler(payload, LocalLambdaContext(fn))

    def _enqueue(self, invocation: _Invocation, delay: float = 0.0) -> None:
        with self._pending_lock:
            self._pending += 1
        if delay:
            timer = threading.Timer(delay, self.invocations.put, args=(invocation,))
            timer.daemon = True
            timer.start()
        else:
            self.invocations.put(invocation)

    def _worker(self) -> None:
        while not self._stop.is_set():
            invocation = self.invocations.get()
            if invocation is None:
                return
            try:
                self.invoke(invocation.fn, invocation.payload)
            except Exception as exc:  # noqa: BLE001
                self._handle_failure(invocation, exc)
            finally:
                with self._pending_lock:
                    self._pending -= 1

    def _handle_failure(self, invocation: _Invocation, exc: Exception) -> None:
        if invocation.attempt < invocation.fn.async_retry_attempts:
            delay = self.retry_delays[min(invocation.attempt, len(self.retry_delays) - 1)]
            self._enqueue(_Invocation(invocation.fn, invocation.payload, invocation.origin, invocation.attempt + 1), delay)
            return
        record = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "function": invocation.fn.function_name,
            "origin": invocation.origin,
            "attempts": invocation.attempt + 1,
            "error": str(exc),
            "event": invocation.payload,
        }
        self.dead_letters.appendleft(record)
        boto3.client("sqs", region_name=LOCAL_REGION).send_message(
            QueueUrl=self.physical["EventsDeadLetterQueue"], MessageBody=json.dumps(record, default=str)
        )
        from services.automation_log import AutomationLog

        audit = AutomationLog()
        audit.record(
            "lambda-async-runtime (simulado)", "Lambda Destination (OnFailure)",
            invocation.payload.get("detail-type", "Scheduled Event"), "SENT_TO_DLQ",
            f"{invocation.fn.function_name} falhou após {invocation.attempt + 1} tentativas; evento enviado à DLQ.",
            details={"error": str(exc)},
        )
        # Na AWS, o alarme DeadLetterQueueAlarm (CloudWatch) publica no tópico SNS. Aqui é simulado.
        alarm_name = "techcommerce-local-dlq-has-messages"
        message = (f"ALARM: {alarm_name}\nHá eventos na DLQ após todas as retentativas.\n"
                   f"Função: {invocation.fn.function_name}\nErro: {exc}")
        boto3.client("sns", region_name=LOCAL_REGION).publish(
            TopicArn=self.physical["NotificationsTopic"], Subject=f"ALARM: {alarm_name}", Message=message
        )
        audit.record(
            "cloudwatch-alarm (simulado)", "CloudWatch Alarm", "ApproximateNumberOfMessagesVisible >= 1", "SUCCESS",
            "Alarme da DLQ disparado e notificação de falha publicada no SNS (equipe operations).",
            details={"team": "operations", "severity": "ERROR", "subject": f"ALARM: {alarm_name}", "message": message},
        )

    # ------------------------------------------------------------------ EventBridge local
    def _on_event_published(self, entry: dict) -> None:
        event = {
            "version": "0",
            "id": entry.get("EventId") or str(uuid.uuid4()),
            "detail-type": entry["DetailType"],
            "source": entry["Source"],
            "account": ACCOUNT_ID,
            "time": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "region": LOCAL_REGION,
            "resources": [],
            "detail": json.loads(entry["Detail"]),
        }
        matched = []
        for fn, rule in self.rules:
            if matches(rule.pattern, event):
                matched.append({"rule": rule.name, "target": fn.function_name})
                self._enqueue(_Invocation(fn, event, origin=f"rule:{rule.name}"))
        self.event_trace.appendleft(
            {
                "timestamp": event["time"],
                "eventBus": entry["EventBusName"],
                "source": event["source"],
                "detailType": event["detail-type"],
                "eventId": event["detail"].get("metadata", {}).get("eventId"),
                "correlationId": event["detail"].get("metadata", {}).get("correlationId"),
                "matchedRules": matched,
                "data": event["detail"].get("data", {}),
            }
        )

    # ------------------------------------------------------------------ EventBridge Scheduler local
    def run_schedules_now(self) -> list[dict]:
        now = datetime.now(tz=timezone.utc)
        triggered = []
        for fn, schedule in self.schedules:
            payload_text = (
                schedule.input.replace("<aws.scheduler.scheduled-time>", now.strftime("%Y-%m-%dT%H:%M:%SZ"))
                .replace("<aws.scheduler.execution-id>", str(uuid.uuid4()))
            )
            self._enqueue(_Invocation(fn, json.loads(payload_text), origin=f"schedule:{schedule.name}"))
            triggered.append({"schedule": schedule.name, "target": fn.function_name})
        self.scheduler_state["lastRunAt"] = now.isoformat()
        self.scheduler_state["runs"] += 1
        return triggered

    def _scheduler_loop(self) -> None:
        interval = self.schedule_interval_seconds
        next_run = datetime.now(tz=timezone.utc) + timedelta(seconds=interval)
        self.scheduler_state["nextRunAt"] = next_run.isoformat()
        while not self._stop.wait(1.0):
            if datetime.now(tz=timezone.utc) >= next_run:
                self.run_schedules_now()
                next_run = datetime.now(tz=timezone.utc) + timedelta(seconds=interval)
                self.scheduler_state["nextRunAt"] = next_run.isoformat()

    # ------------------------------------------------------------------ API Gateway local
    def _compile_routes(self):
        routes = []
        for fn in self.functions.values():
            for method, path in fn.api_routes:
                regex = "^" + re.sub(r"\{([^}+]+)\+?\}", r"(?P<\1>[^/]+)", path) + "$"
                routes.append((method, path, re.compile(regex), fn))
        # rotas estáticas antes das parametrizadas (ex.: /reports/download antes de /reports/{x})
        routes.sort(key=lambda r: ("{" in r[1], r[1]))
        return routes

    def handle_api(self, method: str, path: str, query: dict, headers: dict, body: str | None) -> dict:
        for route_method, resource, regex, fn in self.routes:
            match = regex.match(path)
            if match and route_method == method:
                event = {
                    "resource": resource,
                    "path": path,
                    "httpMethod": method,
                    "headers": headers,
                    "queryStringParameters": query or None,
                    "pathParameters": match.groupdict() or None,
                    "body": body,
                    "isBase64Encoded": False,
                    "requestContext": {"requestId": str(uuid.uuid4()), "stage": "local", "resourcePath": resource},
                }
                return self.invoke(fn, event)
        return {"statusCode": 404, "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": f"Rota não encontrada: {method} {path}"})}

    # ------------------------------------------------------------------ status para a interface
    def status(self) -> dict:
        return {
            "mode": "local-simulation",
            "warning": "Execução local simulada (moto + simulador de EventBridge/Scheduler). Não é uma execução na AWS.",
            "functions": [
                {"name": fn.function_name, "handler": fn.handler, "apiRoutes": fn.api_routes,
                 "rules": [r.name for r in fn.rules], "schedules": [s.name for s in fn.schedules]}
                for fn in self.functions.values()
            ],
            "rules": [{"name": r.name, "target": fn.function_name, "pattern": r.pattern} for fn, r in self.rules],
            "scheduler": {
                "schedules": [
                    {"name": s.name, "awsExpression": s.expression, "timezone": s.timezone, "target": fn.function_name}
                    for fn, s in self.schedules
                ],
                "localIntervalSeconds": self.schedule_interval_seconds,
                **self.scheduler_state,
            },
            "deadLetterCount": len(self.dead_letters),
            "pendingInvocations": self._pending,
        }
