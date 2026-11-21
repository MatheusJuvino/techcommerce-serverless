"""Cria, no moto (AWS em memória), os recursos declarados no template SAM."""
from __future__ import annotations

import os

import boto3

from local_runtime.template_loader import Resolver, TemplateModel

LOCAL_REGION = "sa-east-1"
FAKE_CREDENTIALS = {
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_DEFAULT_REGION": LOCAL_REGION,
    "AWS_REGION": LOCAL_REGION,
}


def use_fake_credentials() -> None:
    """Garante que nenhuma credencial real (perfil ~/.aws) seja usada na simulação."""
    os.environ.pop("AWS_PROFILE", None)
    os.environ.update(FAKE_CREDENTIALS)


def create_resources(model: TemplateModel) -> dict[str, str]:
    """Cria tabelas, bucket, tópico, fila e barramento. Retorna o mapa logicalId -> id físico."""
    resolver = Resolver(model.parameters, {})
    physical: dict[str, str] = {}
    dynamodb = boto3.client("dynamodb", region_name=LOCAL_REGION)
    s3 = boto3.client("s3", region_name=LOCAL_REGION)
    sns = boto3.client("sns", region_name=LOCAL_REGION)
    sqs = boto3.client("sqs", region_name=LOCAL_REGION)
    events = boto3.client("events", region_name=LOCAL_REGION)

    for logical_id, resource in model.resources.items():
        rtype = resource["Type"]
        props = resolver.resolve(resource.get("Properties", {}))
        if rtype == "AWS::DynamoDB::Table":
            args = {
                "TableName": props["TableName"],
                "AttributeDefinitions": props["AttributeDefinitions"],
                "KeySchema": props["KeySchema"],
                "BillingMode": props.get("BillingMode", "PAY_PER_REQUEST"),
            }
            if props.get("GlobalSecondaryIndexes"):
                args["GlobalSecondaryIndexes"] = props["GlobalSecondaryIndexes"]
            dynamodb.create_table(**args)
            if props.get("TimeToLiveSpecification"):
                dynamodb.update_time_to_live(TableName=props["TableName"], TimeToLiveSpecification=props["TimeToLiveSpecification"])
            physical[logical_id] = props["TableName"]
        elif rtype == "AWS::S3::Bucket":
            name = props.get("BucketName") or f"techcommerce-{model.parameters['Environment']}-reports"
            s3.create_bucket(Bucket=name, CreateBucketConfiguration={"LocationConstraint": LOCAL_REGION})
            physical[logical_id] = name
        elif rtype == "AWS::SNS::Topic":
            physical[logical_id] = sns.create_topic(Name=props["TopicName"])["TopicArn"]
        elif rtype == "AWS::SQS::Queue":
            url = sqs.create_queue(QueueName=props["QueueName"])["QueueUrl"]
            physical[logical_id] = url
            physical[f"{logical_id}.Arn"] = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
        elif rtype == "AWS::Events::EventBus":
            events.create_event_bus(Name=props["Name"])
            physical[logical_id] = props["Name"]
    return physical


def function_environment(model: TemplateModel, physical: dict[str, str], overrides: dict[str, str]) -> dict[str, str]:
    resolver = Resolver(model.parameters, physical)
    env = {key: str(resolver.resolve(value)) for key, value in model.global_env.items()}
    env.update(overrides)
    return env
