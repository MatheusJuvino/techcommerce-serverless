"""Endpoints somente-leitura usados pela interface de demonstração.

GET /health                  -> ambiente e recursos configurados
GET /orders                  -> pedidos recentes (filtro opcional ?status=)
GET /orders/{orderId}        -> pedido com histórico de status
GET /reports                 -> relatórios gerados no S3
GET /reports/download?key=   -> conteúdo CSV de um relatório
GET /automations             -> histórico das execuções automáticas
"""
from __future__ import annotations

from repositories.orders_repository import OrdersRepository
from repositories.reports_repository import ReportsRepository
from services.automation_log import AutomationLog
from utils.config import get_settings
from utils.errors import NotFoundError
from utils.http import error_response, response, text_response
from utils.logger import bind_context, get_logger

logger = get_logger(__name__)


def _limit(params: dict, default: int = 50) -> int:
    try:
        return max(1, min(int(params.get("limit", default)), 200))
    except (TypeError, ValueError):
        return default


def lambda_handler(event, context):
    bind_context(function_name="read_api")
    route = f"{event.get('httpMethod')} {event.get('resource')}"
    params = event.get("queryStringParameters") or {}
    path_params = event.get("pathParameters") or {}
    try:
        if route == "GET /health":
            settings = get_settings()
            return response(200, {
                "status": "ok",
                "environment": settings.app_env,
                "mode": "local-simulation" if settings.is_local else "aws",
                "region": settings.region,
                "eventBus": settings.event_bus_name,
                "faultInjectionEnabled": settings.enable_fault_injection,
                "maxOrderValue": settings.max_order_value,
            })
        if route == "GET /orders":
            orders = OrdersRepository().list_recent(limit=_limit(params), status=params.get("status"))
            return response(200, {"orders": orders, "count": len(orders)})
        if route == "GET /orders/{orderId}":
            order = OrdersRepository().get(path_params.get("orderId", ""))
            if not order:
                return error_response(404, "Pedido não encontrado.")
            return response(200, order)
        if route == "GET /reports":
            return response(200, {"reports": ReportsRepository().list_reports(_limit(params, 20))})
        if route == "GET /reports/download":
            key = params.get("key", "")
            content = ReportsRepository().read(key)
            filename = key.rsplit("/", 1)[-1]
            return text_response(200, content, "text/csv; charset=utf-8",
                                 {"Content-Disposition": f'attachment; filename="{filename}"'})
        if route == "GET /automations":
            return response(200, {"automations": AutomationLog().recent(_limit(params))})
    except NotFoundError as exc:
        return error_response(404, str(exc))
    return error_response(404, f"Rota não encontrada: {route}")
