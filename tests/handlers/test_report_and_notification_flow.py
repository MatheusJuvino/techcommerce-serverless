"""Fluxos 3 e 4: relatório agendado/sob demanda e notificações SNS."""
import json

import boto3

from handlers import create_order, demo_events, generate_sales_report, notification_dispatcher, process_order, read_api
from models.events import EventType, Source
from repositories.reports_repository import ReportsRepository
from tests.conftest import VALID_ORDER, api_event, eventbridge_event, to_eventbridge

SCHEDULE_PAYLOAD = {"trigger": "schedule", "period": "last_24h", "scheduledTime": "2026-11-20T09:00:00Z",
                    "executionId": "exec-1"}


def _seed(published, n=2):
    for _ in range(n):
        create_order.lambda_handler(api_event(VALID_ORDER), None)
        process_order.lambda_handler(to_eventbridge(published[-1]), None)


def test_scheduled_report_saves_csv_to_s3(published):
    _seed(published)
    result = generate_sales_report.lambda_handler(SCHEDULE_PAYLOAD, None)
    assert result["status"] == "GENERATED" and result["trigger"] == "EventBridge Scheduler"
    assert result["totalOrders"] == 2
    content = ReportsRepository().read(result["reportKey"])
    assert content.splitlines()[0].startswith("orderId,createdAt")
    assert len(content.splitlines()) == 3
    summary = ReportsRepository().read(result["summaryKey"])
    assert "receita_bruta_aprovada,8159.40" in summary
    assert published[-1]["DetailType"] == EventType.SALES_REPORT_GENERATED


def test_schedule_redelivery_is_idempotent(published):
    first = generate_sales_report.lambda_handler(SCHEDULE_PAYLOAD, None)
    second = generate_sales_report.lambda_handler(SCHEDULE_PAYLOAD, None)
    assert second["duplicate"] is True and second["reportKey"] == first["reportKey"]
    assert len(ReportsRepository().list_reports()) == 2  # relatório + resumo, sem duplicar


def test_on_demand_report_via_event(published):
    response = demo_events.lambda_handler(api_event({"period": "today"}, resource="/reports"), None)
    assert response["statusCode"] == 202
    assert published[-1]["DetailType"] == EventType.SALES_REPORT_REQUESTED
    result = generate_sales_report.lambda_handler(to_eventbridge(published[-1]), None)
    assert result["trigger"] == "EventBridge Rule" and result["period"] == "today"


def test_invalid_report_period(published):
    response = demo_events.lambda_handler(api_event({"period": "sempre"}, resource="/reports"), None)
    assert response["statusCode"] == 400
    event = eventbridge_event(EventType.SALES_REPORT_REQUESTED, Source.REPORTS, {"period": "sempre"})
    assert generate_sales_report.lambda_handler(event, None)["status"] == "FAILED"
    assert published[-1]["DetailType"] == EventType.PROCESSING_FAILED


def _subscribe_queue(topic_arn: str) -> str:
    sqs = boto3.client("sqs", region_name="sa-east-1")
    sns = boto3.client("sns", region_name="sa-east-1")
    url = sqs.create_queue(QueueName="notifications-test")["QueueUrl"]
    arn = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    sns.subscribe(TopicArn=topic_arn, Protocol="sqs", Endpoint=arn)
    return url


def test_notification_is_published_to_sns_with_team_attribute(aws, published):
    queue_url = _subscribe_queue(aws["NotificationsTopic"])
    event = eventbridge_event(EventType.ORDER_APPROVED, Source.ORDERS,
                              {"orderId": "ORD-1", "total": 100, "customerName": "Maria", "itemsCount": 1})
    result = notification_dispatcher.lambda_handler(event, None)
    assert result["team"] == "logistics" and result["messageId"]
    messages = boto3.client("sqs", region_name="sa-east-1").receive_message(QueueUrl=queue_url).get("Messages", [])
    body = json.loads(messages[0]["Body"])
    assert "Pedido aprovado ORD-1" in body["Subject"]
    assert body["MessageAttributes"]["team"]["Value"] == "logistics"
    duplicate = notification_dispatcher.lambda_handler(event, None)
    assert duplicate["duplicate"] is True


def test_read_api_endpoints(published):
    _seed(published, 1)
    generate_sales_report.lambda_handler(SCHEDULE_PAYLOAD, None)
    orders = json.loads(read_api.lambda_handler(api_event(method="GET", resource="/orders"), None)["body"])
    assert orders["count"] == 1
    order_id = orders["orders"][0]["orderId"]
    detail = read_api.lambda_handler(api_event(method="GET", resource="/orders/{orderId}", path_params={"orderId": order_id}), None)
    assert json.loads(detail["body"])["status"] == "APPROVED"
    missing = read_api.lambda_handler(api_event(method="GET", resource="/orders/{orderId}", path_params={"orderId": "X"}), None)
    assert missing["statusCode"] == 404
    reports = json.loads(read_api.lambda_handler(api_event(method="GET", resource="/reports"), None)["body"])["reports"]
    download = read_api.lambda_handler(
        api_event(method="GET", resource="/reports/download", query={"key": reports[0]["key"]}), None)
    assert download["headers"]["Content-Type"].startswith("text/csv")
    traversal = read_api.lambda_handler(
        api_event(method="GET", resource="/reports/download", query={"key": "../secret"}), None)
    assert traversal["statusCode"] == 404
    automations = json.loads(read_api.lambda_handler(api_event(method="GET", resource="/automations"), None)["body"])
    assert {"create_order", "process_order", "generate_sales_report"} <= {a["function"] for a in automations["automations"]}
    health = json.loads(read_api.lambda_handler(api_event(method="GET", resource="/health"), None)["body"])
    assert health["mode"] == "local-simulation"
