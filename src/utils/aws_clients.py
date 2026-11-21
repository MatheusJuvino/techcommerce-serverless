"""Fábrica de clientes boto3 reutilizados entre invocações (reduz latência de cold start)."""
from __future__ import annotations

from functools import lru_cache

import boto3
from botocore.config import Config

from utils.config import get_settings

_BOTO_CONFIG = Config(retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=3, read_timeout=10)


@lru_cache(maxsize=None)
def client(service: str):
    return boto3.client(service, region_name=get_settings().region, config=_BOTO_CONFIG)


@lru_cache(maxsize=None)
def resource(service: str):
    return boto3.resource(service, region_name=get_settings().region, config=_BOTO_CONFIG)


def reset_clients() -> None:
    """Usado pelos testes e pelo simulador local ao iniciar um novo ambiente moto."""
    client.cache_clear()
    resource.cache_clear()
