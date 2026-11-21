"""Armazenamento dos relatórios CSV no Amazon S3 (prefixo reports/AAAA/MM/DD/)."""
from __future__ import annotations

from botocore.exceptions import ClientError

from utils import aws_clients
from utils.config import get_settings
from utils.errors import NotFoundError, TransientError

REPORTS_PREFIX = "reports/"


class ReportsRepository:
    def __init__(self, bucket: str | None = None):
        self.bucket = bucket or get_settings().reports_bucket
        self.s3 = aws_clients.client("s3")

    def save_csv(self, key: str, content: str, metadata: dict[str, str] | None = None) -> dict:
        try:
            self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content.encode("utf-8-sig"),  # BOM para abrir corretamente no Excel (acentuação)
                ContentType="text/csv; charset=utf-8",
                ServerSideEncryption="AES256",
                Metadata=metadata or {},
            )
        except ClientError as exc:
            raise TransientError(f"Falha ao salvar relatório no S3: {exc}") from exc
        return {"bucket": self.bucket, "key": key, "uri": f"s3://{self.bucket}/{key}"}

    def list_reports(self, limit: int = 20) -> list[dict]:
        paginator = self.s3.get_paginator("list_objects_v2")
        objects = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=REPORTS_PREFIX):
            objects.extend(page.get("Contents", []))
        objects.sort(key=lambda o: o["LastModified"], reverse=True)
        return [
            {"key": o["Key"], "size": o["Size"], "lastModified": o["LastModified"].isoformat()}
            for o in objects[:limit]
        ]

    def read(self, key: str) -> str:
        if not key.startswith(REPORTS_PREFIX) or ".." in key:
            raise NotFoundError("Relatório não encontrado.")
        try:
            obj = self.s3.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise NotFoundError("Relatório não encontrado.") from exc
            raise
        return obj["Body"].read().decode("utf-8-sig")
