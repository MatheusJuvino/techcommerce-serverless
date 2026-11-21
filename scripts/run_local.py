"""Inicia a demonstração local (sem conta AWS).

Uso:
    python scripts/run_local.py                      # http://127.0.0.1:8000
    python scripts/run_local.py --port 8080 --schedule-interval 60
    python scripts/run_local.py --schedule-interval 0   # desabilita o agendador local
"""
from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from local_runtime.runtime import LocalRuntime  # noqa: E402
from local_runtime.server import serve  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="TechCommerce Serverless - demonstração local")
    parser.add_argument("--host", default=os.environ.get("LOCAL_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LOCAL_PORT", "8000")))
    parser.add_argument("--schedule-interval", type=int, default=int(os.environ.get("LOCAL_SCHEDULE_INTERVAL_SECONDS", "120")),
                        help="Intervalo (s) do agendador local que simula o EventBridge Scheduler. 0 desabilita.")
    parser.add_argument("--open", action="store_true", help="Abre o navegador automaticamente.")
    args = parser.parse_args()

    runtime = LocalRuntime(schedule_interval_seconds=args.schedule_interval).start()
    server = serve(runtime, args.host, args.port)
    url = f"http://{args.host}:{args.port}"
    print("=" * 78)
    print(" TechCommerce Serverless - DEMONSTRAÇÃO LOCAL (SIMULADA)")
    print(" AWS emulada em memória pelo moto; regras/agendamentos lidos de infrastructure/template.yaml")
    print(f" Interface: {url}    API: {url}/api")
    print(f" Agendador local do relatório: a cada {args.schedule_interval}s" if args.schedule_interval else " Agendador local desabilitado")
    print(" Ctrl+C para encerrar. Os logs JSON abaixo equivalem ao que iria para o CloudWatch Logs.")
    print("=" * 78, flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        runtime.stop()


if __name__ == "__main__":
    main()
