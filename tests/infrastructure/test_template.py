"""Valida a infraestrutura como código (template SAM)."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from local_runtime.template_loader import load_template
from tests.conftest import TEMPLATE

MODEL = load_template(TEMPLATE)
RESOURCES = MODEL.resources
ASYNC_FUNCTIONS = ["ProcessOrderFunction", "UpdateTransactionFunction", "GenerateSalesReportFunction",
                   "NotificationDispatcherFunction"]


def _types():
    return {r["Type"] for r in RESOURCES.values()}


def test_required_services_are_declared():
    required = {"AWS::Serverless::Function", "AWS::Events::EventBus", "AWS::Serverless::Api", "AWS::DynamoDB::Table",
                "AWS::S3::Bucket", "AWS::SNS::Topic", "AWS::Logs::LogGroup", "AWS::SQS::Queue", "AWS::CloudWatch::Alarm"}
    assert required <= _types()


def test_functions_use_python312_and_have_handlers():
    globals_fn = MODEL.raw["Globals"]["Function"]
    assert globals_fn["Runtime"] == "python3.12"
    for fn in MODEL.functions.values():
        module = fn.handler.rsplit(".", 1)[0].replace(".", "/")
        assert (Path(TEMPLATE).parents[1] / "src" / f"{module}.py").exists(), fn.handler


def test_event_rules_wire_events_to_functions():
    rules = {r.pattern["detail-type"][0]: fn.logical_id for fn in MODEL.functions.values() for r in fn.rules}
    assert rules["OrderReceived"] == "ProcessOrderFunction"
    assert rules["TransactionStatusChanged"] == "UpdateTransactionFunction"
    assert rules["SalesReportRequested"] == "GenerateSalesReportFunction"
    notify = MODEL.functions["NotificationDispatcherFunction"].rules[0].pattern["detail-type"]
    assert set(notify) == {"OrderApproved", "OrderRejected", "TransactionUpdated", "ProcessingFailed", "SalesReportGenerated"}


def test_report_schedule_is_configurable():
    schedule = MODEL.functions["GenerateSalesReportFunction"].schedules[0]
    raw = RESOURCES["GenerateSalesReportFunction"]["Properties"]["Events"]["DailySalesReportSchedule"]
    assert raw["Type"] == "ScheduleV2"
    assert raw["Properties"]["ScheduleExpression"] == {"Ref": "ReportScheduleExpression"}
    assert schedule.expression == "cron(0 6 * * ? *)" and schedule.timezone == "America/Sao_Paulo"
    assert '"trigger": "schedule"' in schedule.input and "<aws.scheduler.scheduled-time>" in schedule.input
    assert raw["Properties"]["RetryPolicy"]["MaximumRetryAttempts"] >= 1
    assert "DeadLetterConfig" in raw["Properties"]


def test_async_functions_have_retries_and_dlq():
    for name in ASYNC_FUNCTIONS:
        props = RESOURCES[name]["Properties"]
        config = props["EventInvokeConfig"]
        assert config["MaximumRetryAttempts"] == 2
        assert config["DestinationConfig"]["OnFailure"]["Type"] == "SQS"
        for event in props["Events"].values():
            if event["Type"] == "EventBridgeRule":
                assert event["Properties"]["RetryPolicy"]["MaximumRetryAttempts"] >= 1
                assert event["Properties"]["DeadLetterConfig"]["Arn"] == {"Fn::GetAtt": ["EventsDeadLetterQueue", "Arn"]}


def test_iam_least_privilege_no_wildcards():
    for name, fn in MODEL.functions.items():
        policies = RESOURCES[name]["Properties"]["Policies"]
        for policy in policies:
            assert isinstance(policy, dict) and "Statement" in policy, f"{name} usa política gerenciada ampla"
            for statement in policy["Statement"]:
                actions = statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
                assert all("*" not in a for a in actions), f"{name}: ação curinga {actions}"
                assert statement["Resource"] != "*", f"{name}: recurso curinga"


def test_read_api_is_read_only():
    statements = RESOURCES["ReadApiFunction"]["Properties"]["Policies"][0]["Statement"]
    actions = {a for s in statements for a in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])}
    assert actions <= {"dynamodb:GetItem", "dynamodb:Query", "s3:ListBucket", "s3:GetObject"}


def test_storage_security():
    bucket = RESOURCES["ReportsBucket"]["Properties"]
    assert all(bucket["PublicAccessBlockConfiguration"].values())
    assert "BucketEncryption" in bucket
    for table in ("OrdersTable", "IdempotencyTable", "AutomationLogTable"):
        assert RESOURCES[table]["Properties"]["BillingMode"] == "PAY_PER_REQUEST"
    assert RESOURCES["IdempotencyTable"]["Properties"]["TimeToLiveSpecification"]["Enabled"] is True


def test_no_hardcoded_credentials_in_source():
    root = Path(TEMPLATE).parents[1]
    for path in list((root / "src").rglob("*.py")) + [TEMPLATE]:
        text = path.read_text(encoding="utf-8")
        assert "AKIA" not in text and "aws_secret_access_key" not in text.lower(), path


@pytest.mark.skipif(shutil.which("cfn-lint") is None and not (Path(sys.executable).parent / "cfn-lint.exe").exists(),
                    reason="cfn-lint não instalado")
def test_cfn_lint_passes():
    exe = shutil.which("cfn-lint") or str(Path(sys.executable).parent / "cfn-lint.exe")
    result = subprocess.run([exe, str(TEMPLATE), "--regions", "sa-east-1"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
