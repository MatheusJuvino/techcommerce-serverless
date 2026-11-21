"""Gera o vídeo pitch (sem narração) a partir de video/roteiro.json.

Cenas "slide" são páginas HTML animadas (video/scenes/); cenas "app" são gravações reais da interface
web rodando no ambiente local simulado (scripts/run_local.py). A captura usa o Chrome instalado via
Playwright (screencast do DevTools) e a montagem usa o ffmpeg do pacote imageio-ffmpeg.

Saídas em entrega/video/:
    video_pitch_sem_narracao.mp4   vídeo final sem áudio de voz (1920x1080, 30 fps)
    legendas_narracao.srt          falas com tempos (teleprompter / legendas no YouTube)
    video_guia_com_falas.mp4       mesmo vídeo com as falas na tela, para ensaiar

Uso:
    pip install -r video/requirements.txt
    python video/build_video.py                 # todas as cenas
    python video/build_video.py --cenas s3 s5   # regrava só algumas cenas (reaproveita as demais)
"""
from __future__ import annotations

import argparse
import base64
import functools
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "video"
SCENES = VIDEO / "scenes"
GENERATED = SCENES / "generated"
ICONS = VIDEO / "assets" / "icons"
OUT = ROOT / "entrega" / "video"
CLIPS = OUT / "_clips"
ICON_NAMES = ["aws-lambda", "aws-eventbridge", "aws-api-gateway", "aws-dynamodb", "aws-s3", "aws-sns", "aws-sqs",
              "aws-cloudwatch", "html-5", "github-icon"]
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
APP_ZOOM = 1.3


def log(msg: str) -> None:
    print(msg, flush=True)


def run_ffmpeg(args: list[str], cwd: Path | None = None) -> None:
    result = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], cwd=cwd,
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou: {result.stderr[-2000:]}")


# ------------------------------------------------------------------ preparação
def ensure_icons() -> None:
    if all((ICONS / f"{n}.svg").exists() for n in ICON_NAMES):
        return
    log("Baixando ícones (@iconify-json/logos)...")
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        sys.exit("npm não encontrado: necessário para baixar os ícones uma única vez.")
    tmp = Path(tempfile.mkdtemp())
    subprocess.run([npm, "pack", "@iconify-json/logos", "--silent"], cwd=tmp, check=True, capture_output=True)
    with tarfile.open(next(tmp.glob("*.tgz"))) as tgz:
        data = json.load(tgz.extractfile("package/icons.json"))
    ICONS.mkdir(parents=True, exist_ok=True)
    for name in ICON_NAMES:
        icon = data["icons"][name]
        w, h = icon.get("width", data.get("width", 256)), icon.get("height", data.get("height", 256))
        (ICONS / f"{name}.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">{icon["body"]}</svg>', encoding="utf-8")


def _block(lines: list[str], start: int, end: int, keys: dict[str, str]) -> list[tuple[int, str, str]]:
    out = []
    for no in range(start, end + 1):
        text = lines[no - 1]
        tags = " ".join(k for k, pattern in keys.items() if re.search(pattern, text))
        out.append((no, text, tags))
    return out


def _find(lines: list[str], pattern: str, after: int = 0) -> int:
    for idx in range(after, len(lines)):
        if re.search(pattern, lines[idx]):
            return idx + 1
    raise ValueError(f"trecho não encontrado no template: {pattern}")


def _render_code(blocks: list[list[tuple[int, str, str]]]) -> str:
    from pygments import highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import YamlLexer

    parts = []
    for i, block in enumerate(blocks):
        if i:
            parts.append('<div class="ln gap"><span class="no">⋮</span><span class="code"></span></div>')
        source = "\n".join(text for _, text, _ in block)
        highlighted = highlight(source, YamlLexer(), HtmlFormatter(nowrap=True)).rstrip("\n").split("\n")
        for (no, _, tags), code in zip(block, highlighted):
            parts.append(f'<div class="ln" data-k="{tags}"><span class="no">{no}</span><span class="code">{code}</span></div>')
    return "".join(parts)


def generate_assets() -> None:
    GENERATED.mkdir(parents=True, exist_ok=True)
    lines = (ROOT / "infrastructure" / "template.yaml").read_text(encoding="utf-8").splitlines()

    fn = _find(lines, r"^  ProcessOrderFunction:")
    events = _find(lines, r"^      Events:", fn)
    rule_end = _find(lines, r"Arn: !GetAtt EventsDeadLetterQueue.Arn", events)
    rule = [
        _block(lines, fn, fn + 5, {"fn": r"ProcessOrderFunction|AWS::Serverless::Function|Handler"}),
        _block(lines, events, rule_end, {"pattern": r"Pattern:|source:|detail-type:", "retry": r"RetryPolicy|Maximum",
                                         "dlq": r"DeadLetterConfig|Arn: !GetAtt EventsDeadLetterQueue"}),
    ]
    p_expr = _find(lines, r"^  ReportScheduleExpression:")
    p_tz = _find(lines, r"^  ReportScheduleTimezone:")
    sched = _find(lines, r"^        DailySalesReportSchedule:")
    sched_end = _find(lines, r"Arn: !GetAtt EventsDeadLetterQueue.Arn", sched)
    keys = {"cron": r"ScheduleExpression:|Default: cron", "tz": r"Timezone|America/Sao_Paulo", "input": r"Input:"}
    schedule = [_block(lines, p_expr, p_expr + 2, keys), _block(lines, p_tz, p_tz + 2, keys),
                _block(lines, sched, sched_end, keys)]
    code = {"rule": _render_code(rule), "schedule": _render_code(schedule)}
    (GENERATED / "code.js").write_text("window.CODE = " + json.dumps(code, ensure_ascii=False) + ";", encoding="utf-8")

    evidence = (ROOT / "entrega" / "evidencias" / "pytest_resultado.txt").read_text(encoding="utf-8-sig").splitlines()
    tests = [re.sub(r"\s+\[\s*\d+%\]$", "", l.strip()) for l in evidence if re.search(r"::\S+ (PASSED|SKIPPED)", l)]
    chosen, seen = [], set()
    for line in tests:
        module = line.split("::")[0]
        if module not in seen and len(line) <= 118:
            seen.add(module)
            chosen.append(line)
    summary = next(l.strip() for l in reversed(evidence) if re.search(r"\d+ passed", l))
    summary = re.sub(r"^=+\s*|\s*=+$", "", summary)
    pytest_js = {"lines": chosen[:7], "summary": f"======== {summary} ========"}
    (GENERATED / "pytest.js").write_text("window.PYTEST = " + json.dumps(pytest_js, ensure_ascii=False) + ";",
                                         encoding="utf-8")


# ------------------------------------------------------------------ servidores
class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def start_static_server() -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(VIDEO)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_local_app() -> tuple[subprocess.Popen, str]:
    port = free_port()
    proc = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "run_local.py"), "--port", str(port),
                             "--schedule-interval", "0"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    url = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1) as res:
                if res.status == 200:
                    return proc, url
        except OSError:
            time.sleep(0.25)
    proc.kill()
    raise RuntimeError("ambiente local não respondeu")


# ------------------------------------------------------------------ captura
class Recorder:
    """Captura quadros via Page.startScreencast e monta um clipe com duração exata."""

    def __init__(self, page: Page, folder: Path):
        self.page, self.folder = page, folder
        self.cdp = page.context.new_cdp_session(page)
        self.frames: list[tuple[float, Path]] = []
        self.cdp.on("Page.screencastFrame", self._on_frame)

    def _on_frame(self, ev: dict) -> None:
        received = time.time()
        stamp = ev["metadata"].get("timestamp") or received
        if abs(stamp - received) > 2:
            stamp = received
        path = self.folder / f"{len(self.frames):06d}.jpg"
        path.write_bytes(base64.b64decode(ev["data"]))
        self.frames.append((stamp, path))
        self.cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})

    def start(self) -> None:
        if self.folder.exists():
            shutil.rmtree(self.folder)
        self.folder.mkdir(parents=True)
        self.frames.clear()
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 93, "maxWidth": 1920, "maxHeight": 1080})
        self.page.evaluate("""() => { const t = document.createElement('div');
            t.style.cssText = 'position:fixed;right:0;bottom:0;width:2px;height:2px;background:rgba(0,0,0,.01);z-index:1';
            document.documentElement.appendChild(t); setTimeout(() => t.remove(), 120); }""")
        self.page.wait_for_timeout(250)

    def stop(self) -> None:
        self.page.wait_for_timeout(200)
        self.cdp.send("Page.stopScreencast")
        self.page.wait_for_timeout(200)

    def build_clip(self, t_start: float, duration: float, target: Path, fade_in: bool = False, fade_out: bool = False) -> None:
        frames = sorted(self.frames)
        if not frames:
            raise RuntimeError("nenhum quadro capturado")
        before = [f for f in frames if f[0] <= t_start]
        inside = [f for f in frames if t_start < f[0] < t_start + duration]
        timeline = ([(t_start, before[-1][1])] if before else [(t_start, frames[0][1])]) + inside
        listing = []
        for i, (stamp, path) in enumerate(timeline):
            end = timeline[i + 1][0] if i + 1 < len(timeline) else t_start + duration
            listing.append(f"file '{path.as_posix()}'\nduration {max(end - stamp, 0.001):.4f}")
        listing.append(f"file '{timeline[-1][1].as_posix()}'")
        concat = self.folder / "frames.txt"
        concat.write_text("\n".join(listing), encoding="utf-8")
        filters = ["fps=30", "scale=1920:1080:flags=lanczos:in_range=pc:out_range=tv:in_color_matrix=bt601"
                   ":out_color_matrix=bt709", "format=yuv420p",
                   "setparams=range=tv:colorspace=bt709:color_primaries=bt709:color_trc=bt709"]
        if fade_in:
            filters.append("fade=t=in:st=0:d=0.8")
        if fade_out:
            filters.append(f"fade=t=out:st={duration - 1.0:.2f}:d=1.0")
        run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(concat), "-vf", ",".join(filters), "-c:v", "libx264",
                    "-preset", "medium", "-crf", "18", "-r", "30", "-t", f"{duration:.3f}", "-an", str(target)])
        log(f"   clipe {target.name}: {len(timeline)} quadros únicos, {duration:.1f}s")


# ------------------------------------------------------------------ cenas da interface
class Demo:
    def __init__(self, page: Page, t0: float):
        self.page, self.t0 = page, t0

    def until(self, t: float) -> None:
        delay = self.t0 + t - time.time()
        if delay > 0:
            self.page.wait_for_timeout(delay * 1000)

    def box(self, selector: str, count: int = 1) -> dict:
        boxes = [b for b in (self.page.locator(selector).nth(i).bounding_box() for i in range(count)) if b]
        x0, y0 = min(b["x"] for b in boxes), min(b["y"] for b in boxes)
        x1 = max(b["x"] + b["width"] for b in boxes)
        y1 = max(b["y"] + b["height"] for b in boxes)
        return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}

    def move(self, selector: str, ms: int = 700) -> None:
        b = self.box(selector)
        self.page.evaluate("([x, y, ms]) => __demo.move(x, y, ms)", [b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, ms])
        self.page.wait_for_timeout(ms + 80)

    def click(self, selector: str, ms: int = 700) -> None:
        self.move(selector, ms)
        self.page.evaluate("() => __demo.click()")
        self.page.locator(selector).click()

    def spot(self, selector: str, label: str, where: str = "bottom", count: int = 1) -> None:
        self.page.evaluate("([r, t, w]) => __demo.spot(r, t, w)", [self.box(selector, count), label, where])

    def unspot(self) -> None:
        self.page.evaluate("() => __demo.unspot()")

    def scroll(self, selector: str, block: str = "center") -> None:
        self.page.evaluate("([s, b]) => document.querySelector(s).scrollIntoView({behavior: 'smooth', block: b})",
                           [selector, block])

    def wait_for(self, selector: str, timeout: float = 6.0) -> None:
        self.page.wait_for_selector(selector, timeout=timeout * 1000)


def prepare_app(page: Page, url: str) -> None:
    page.goto(url + "/")
    page.wait_for_function("document.querySelector('#envBadge').textContent.includes('LOCAL')", timeout=15000)
    page.add_style_tag(content=f"body {{ zoom: {APP_ZOOM}; }} .toast {{ display: none !important; }}")
    page.add_script_tag(path=str(SCENES / "overlay.js"))
    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(3000)


def demo_pedidos(d: Demo) -> None:
    d.until(0.6); d.spot("#envBadge", "Ambiente LOCAL · SIMULADO — não é a conta AWS", "left")
    d.until(5.6); d.spot("#simBanner", "Serviços AWS emulados em memória; regras do EventBridge lidas do template.yaml")
    d.until(10.6); d.unspot()
    d.until(11.4); d.click('[data-preset="ok"]')
    d.until(12.6); d.click('#orderForm button[type="submit"]')
    d.wait_for("#orderResult:not(.hidden)")
    d.until(13.0); d.scroll(".grid", "start")
    d.until(14.0); d.spot("#orderResult", "Resposta imediata: HTTP 202 · status RECEIVED", "bottom")
    d.wait_for("#ordersBody .s-APPROVED")
    d.until(16.6); d.spot("#ordersBody tr:has(.s-APPROVED)", "Processado automaticamente → APPROVED", "bottom")
    d.until(20.6); d.spot("#automations > li", "AUTOMÁTICO: regra do EventBridge acionou λ process_order", "left", count=3)
    d.until(27.6); d.unspot(); d.scroll("#txForm")
    d.until(29.0); d.click('#txForm button[type="submit"]')
    d.until(30.4); d.spot("#txResult", "Evento TransactionStatusChanged (CAPTURED) publicado", "top")
    d.until(32.4); d.unspot(); d.scroll(".grid", "start")
    d.wait_for("#ordersBody .s-PAID")
    d.until(33.6); d.spot("#ordersBody tr:has(.s-PAID)", "λ update_transaction → pedido PAID", "bottom")
    d.until(36.4); d.unspot(); d.click('[data-preset="reject"]')
    d.until(37.6); d.click('#orderForm button[type="submit"]')
    d.wait_for("#ordersBody .s-REJECTED")
    d.until(40.4); d.spot("#ordersBody tr:has(.s-REJECTED)", "Acima do limite → REJECTED automaticamente", "bottom")
    d.until(44.6); d.spot("#automations > li:has(.msg)", "SNS → equipe de suporte notificada", "left")
    d.until(49.4); d.unspot()


def demo_relatorio(d: Demo) -> None:
    d.until(0.3); d.scroll("#runSchedule")
    d.until(2.6); d.click("#runSchedule", 900)
    d.page.wait_for_function("document.querySelectorAll('#reports a[data-key]').length >= 2", timeout=8000)
    d.until(7.2); d.spot("#reports", "2 arquivos CSV gravados no S3 (simulado)", "bottom")
    key = d.page.evaluate("() => [...document.querySelectorAll('#reports a[data-key]')].map(a => a.dataset.key)"
                          ".find(k => k.includes('sales-summary'))")
    csv = d.page.evaluate("async (k) => (await fetch('/api/reports/download?key=' + encodeURIComponent(k))).text()", key)
    d.until(10.6); d.unspot()
    d.page.evaluate("([t, s, c]) => __demo.csv(t, s, c)",
                    [key.split("/")[-1], "conteúdo real gerado pela λ generate_sales_report (ambiente local)", csv])
    d.until(14.6); d.page.evaluate("() => __demo.csvMark(['receita_bruta_aprovada', 'receita_confirmada_paga', "
                                   "'ticket_medio', 'top1_produto', 'top2_produto'])")
    d.until(18.8); d.page.evaluate("() => __demo.csvHide()")
    d.scroll("#automations", "center")
    d.until(20.0); d.spot("#automations > li", "Disparado pelo EventBridge Scheduler → gestão notificada pelo SNS",
                          "left", count=2)
    d.until(25.8); d.unspot()


DEMOS = {"demo_pedidos": demo_pedidos, "demo_relatorio": demo_relatorio}


# ------------------------------------------------------------------ legendas
def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def cues(script: dict) -> list[dict]:
    items, offset = [], 0.0
    for scene in script["cenas"]:
        falas = scene["falas"]
        for i, (start, text) in enumerate(falas):
            end = falas[i + 1][0] - 0.15 if i + 1 < len(falas) else scene["duracao"] - 0.2
            items.append({"cena": scene["id"], "inicio": round(offset + start, 2), "fim": round(offset + end, 2), "texto": text})
        offset += scene["duracao"]
    return items


def write_srt(items: list[dict], target: Path) -> None:
    blocks = [f"{i}\n{srt_time(c['inicio'])} --> {srt_time(c['fim'])}\n{c['texto']}\n" for i, c in enumerate(items, 1)]
    target.write_text("\n".join(blocks), encoding="utf-8")


# ------------------------------------------------------------------ principal
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cenas", nargs="*", help="ids das cenas a regravar (padrão: todas)")
    parser.add_argument("--sem-guia", action="store_true", help="não gera a versão com as falas na tela")
    args = parser.parse_args()

    script = json.loads((VIDEO / "roteiro.json").read_text(encoding="utf-8"))
    scenes = script["cenas"]
    selected = set(args.cenas or [s["id"] for s in scenes])
    OUT.mkdir(parents=True, exist_ok=True)
    CLIPS.mkdir(parents=True, exist_ok=True)
    ensure_icons()
    generate_assets()

    static, static_port = start_static_server()
    app_proc, app_url = (None, None)
    frames_root = Path(tempfile.mkdtemp(prefix="techcommerce-frames-"))
    try:
        if any(s["tipo"] == "app" and s["id"] in selected for s in scenes):
            app_proc, app_url = start_local_app()
            log(f"Ambiente local simulado em {app_url}")
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
            recorder = Recorder(page, frames_root / "scene")
            app_ready = False
            for index, scene in enumerate(scenes):
                if scene["id"] not in selected:
                    continue
                log(f"Gravando {scene['id']} · {scene['titulo']} ({scene['duracao']}s)")
                if scene["tipo"] == "slide":
                    page.goto(f"http://127.0.0.1:{static_port}/{scene['pagina']}")
                    page.evaluate("() => __ready()")
                    page.wait_for_timeout(400)
                    recorder.start()
                    t_start = time.time()
                    page.evaluate("() => __start()")
                    page.wait_for_timeout(scene["duracao"] * 1000 + 300)
                else:
                    if not app_ready:
                        prepare_app(page, app_url)
                        app_ready = True
                    recorder.start()
                    t_start = time.time()
                    DEMOS[scene["acao"]](Demo(page, t_start))
                    Demo(page, t_start).until(scene["duracao"] + 0.3)
                recorder.stop()
                recorder.build_clip(t_start, scene["duracao"], CLIPS / f"{scene['id']}.mp4",
                                    fade_in=index == 0, fade_out=index == len(scenes) - 1)
            browser.close()
    finally:
        static.shutdown()
        if app_proc:
            app_proc.terminate()
        shutil.rmtree(frames_root, ignore_errors=True)

    missing = [s["id"] for s in scenes if not (CLIPS / f"{s['id']}.mp4").exists()]
    if missing:
        sys.exit(f"Clipes ausentes: {missing}. Rode sem --cenas para gerar tudo.")
    listing = CLIPS / "clips.txt"
    listing.write_text("\n".join(f"file '{(CLIPS / (s['id'] + '.mp4')).as_posix()}'" for s in scenes), encoding="utf-8")
    silent = OUT / "video_pitch_sem_narracao.mp4"
    total = sum(s["duracao"] for s in scenes)
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-f", "lavfi", "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000", "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "128k", "-t", f"{total:.3f}", "-movflags", "+faststart", str(silent)])
    items = cues(script)
    write_srt(items, OUT / "legendas_narracao.srt")
    (OUT / "falas.json").write_text(json.dumps({"duracao": total, "falas": items}, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    log(f"Vídeo sem narração: {silent} ({total // 60:.0f}min{total % 60:02.0f}s)")
    if not args.sem_guia:
        style = ("FontName=Segoe UI,FontSize=17,PrimaryColour=&H00FFFFFF,OutlineColour=&H00101010,BorderStyle=3,"
                 "Outline=1,Shadow=0,BackColour=&HA0101010,MarginV=40")
        run_ffmpeg(["-i", silent.name, "-vf", f"subtitles=legendas_narracao.srt:force_style='{style}'", "-c:v", "libx264",
                    "-preset", "medium", "-crf", "22", "-c:a", "copy", "video_guia_com_falas.mp4"], cwd=OUT)
        log(f"Versão guia (falas na tela): {OUT / 'video_guia_com_falas.mp4'}")


if __name__ == "__main__":
    main()
