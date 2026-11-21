"""Renderiza os diagramas Mermaid de diagrams/*.md em PNG (diagrams/png/), usados no relatório PDF.

Requisitos: Node.js. Usa o @mermaid-js/mermaid-cli via npx e um navegador Chrome/Edge já instalado
(variável CHROME_PATH opcional). Uso:
    python scripts/render_diagrams.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIAGRAMS = ROOT / "diagrams"
OUT = DIAGRAMS / "png"
SRC = DIAGRAMS / "src"
BROWSERS = [
    os.environ.get("CHROME_PATH", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def mmdc_command() -> list[str]:
    if os.environ.get("MMDC"):
        return [os.environ["MMDC"]]
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        sys.exit("Node.js/npx não encontrado.")
    return [npx, "-y", "@mermaid-js/mermaid-cli@11"]


def render(source: Path, target: Path, puppeteer_cfg: Path, config: Path, icons: bool = False) -> None:
    cmd = mmdc_command() + ["-i", str(source), "-o", str(target), "-p", str(puppeteer_cfg), "-c", str(config),
                            "-b", "white", "-s", "2", "-w", "1400"]
    if icons:
        cmd += ["--iconPacks", "@iconify-json/logos"]
    print("render", target.name, flush=True)
    subprocess.run(cmd, check=True, env={**os.environ, "PUPPETEER_SKIP_DOWNLOAD": "1"})


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    SRC.mkdir(parents=True, exist_ok=True)
    browser = next((b for b in BROWSERS if b and Path(b).exists()), None)
    if not browser:
        sys.exit("Chrome/Edge não encontrado; defina CHROME_PATH.")
    tmp = Path(tempfile.mkdtemp())
    puppeteer_cfg = tmp / "puppeteer.json"
    puppeteer_cfg.write_text(json.dumps({"executablePath": browser, "args": ["--no-sandbox"]}))
    config = tmp / "mermaid.json"
    config.write_text(json.dumps({"theme": "default", "themeVariables": {"fontFamily": "Segoe UI, Arial, sans-serif"},
                                  "flowchart": {"htmlLabels": True, "curve": "basis"}}))

    for md in sorted(DIAGRAMS.glob("*.md")):
        blocks = re.findall(r"```mermaid\n(.*?)```", md.read_text(encoding="utf-8"), flags=re.S)
        for index, block in enumerate(blocks, start=1):
            source = SRC / f"{md.stem}_{index}.mmd"
            source.write_text(block, encoding="utf-8")
            render(source, OUT / f"{md.stem}_{index}.png", puppeteer_cfg, config)
    icons_src = SRC / "arquitetura_icones.mmd"
    if icons_src.exists():
        render(icons_src, OUT / "arquitetura_icones.png", puppeteer_cfg, config, icons=True)


if __name__ == "__main__":
    main()
