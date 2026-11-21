"""Estúdio de narração: grava a sua voz sobre o vídeo e gera entrega/video/video_pitch_final.mp4.

Uso:
    python video/estudio_narracao.py                          abre o estúdio no navegador
    python video/estudio_narracao.py --audio voz.m4a          junta um áudio gravado em outro aplicativo
    python video/estudio_narracao.py --audio voz.m4a --offset 1.5
                                                              descarta 1,5 s do início do áudio (negativo atrasa a voz)
    python video/estudio_narracao.py --limpar                 apaga a narração gravada e recomeça

Pré-requisito: python video/build_video.py (gera o vídeo sem narração e as falas).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import wave
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "video"
OUT = ROOT / "entrega" / "video"
SILENT = OUT / "video_pitch_sem_narracao.mp4"
FINAL = OUT / "video_pitch_final.mp4"
WORK = OUT / "narracao"
TRACK = WORK / "trilha.wav"
TAKES = WORK / "trechos.json"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
RATE = 48000
LOCK = threading.Lock()


def state() -> dict:
    script = json.loads((VIDEO / "roteiro.json").read_text(encoding="utf-8"))
    cenas, t = [], 0.0
    for c in script["cenas"]:
        cenas.append({"id": c["id"], "titulo": c["titulo"], "inicio": t, "fim": t + c["duracao"]})
        t += c["duracao"]
    falas = json.loads((OUT / "falas.json").read_text(encoding="utf-8"))["falas"]
    takes = json.loads(TAKES.read_text(encoding="utf-8")) if TAKES.exists() else []
    return {"duracao": t, "cenas": cenas, "falas": falas, "trechos": takes,
            "final": FINAL.exists() and bool(takes), "final_path": str(FINAL)}


def decode(src: Path, offset: float, length: float) -> bytes:
    """PCM 16 bits mono com exatamente `length` segundos, a partir de `offset` segundos do arquivo."""
    lead = max(0.0, -offset)
    body = max(0.0, length - lead)
    fade = min(0.03, body / 4)
    cmd = [FFMPEG, "-v", "error", "-ss", f"{max(0.0, offset):.3f}", "-i", str(src), "-t", f"{body:.3f}",
           "-af", f"afade=t=in:d={fade:.3f},afade=t=out:st={max(0.0, body - fade):.3f}:d={fade:.3f}",
           "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"]
    pcm = bytes(round(lead * RATE) * 2) + subprocess.run(cmd, capture_output=True, check=True).stdout
    need = round(length * RATE) * 2
    return pcm[:need].ljust(need, b"\0")


def apply_to_track(pcm: bytes, at: float, total: float) -> None:
    size = round(total * RATE) * 2
    data = b""
    if TRACK.exists():
        with wave.open(str(TRACK), "rb") as w:
            data = w.readframes(w.getnframes())
    data = data[:size].ljust(size, b"\0")
    i = round(at * RATE) * 2
    data = (data[:i] + pcm + data[i + len(pcm):])[:size]
    with wave.open(str(TRACK), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data)


def loudness_filter() -> str:
    base = "highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11"
    probe = subprocess.run([FFMPEG, "-hide_banner", "-i", str(TRACK), "-af", base + ":print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        m = json.loads(probe.stderr[probe.stderr.rindex("{"):])
        float(m["input_i"])
    except (ValueError, KeyError):
        return base
    return (f"{base}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
            f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")


def mux() -> None:
    tmp = FINAL.with_suffix(".tmp.mp4")
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(SILENT), "-i", str(TRACK), "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-af", loudness_filter(), "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart", str(tmp)], capture_output=True, check=True)
    for _ in range(20):
        try:
            os.replace(tmp, FINAL)
            return
        except PermissionError:
            time.sleep(0.25)
    raise RuntimeError(f"feche {FINAL.name} em outros programas e tente de novo")


def save_take(data: bytes, offset: float, inicio: float, fim: float, kind: str) -> dict:
    total = state()["duracao"]
    inicio = max(0.0, min(inicio, total))
    fim = max(inicio, min(fim, total))
    if fim - inicio < 0.5:
        raise ValueError("trecho curto demais")
    with LOCK:
        WORK.mkdir(parents=True, exist_ok=True)
        takes = json.loads(TAKES.read_text(encoding="utf-8")) if TAKES.exists() else []
        ext = ".ogg" if "ogg" in kind else ".webm" if "webm" in kind else kind if kind.startswith(".") else ".audio"
        raw = WORK / f"trecho_{len(takes) + 1:03d}{ext}"
        raw.write_bytes(data)
        apply_to_track(decode(raw, offset, fim - inicio), inicio, total)
        takes.append({"arquivo": raw.name, "inicio": round(inicio, 3), "fim": round(fim, 3), "offset": round(offset, 3)})
        TAKES.write_text(json.dumps(takes, indent=1), encoding="utf-8")
        mux()
    return takes[-1]


class Studio(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self.send_file(VIDEO / "studio" / "index.html", "text/html; charset=utf-8")
        elif path == "/video":
            self.send_file(SILENT, "video/mp4")
        elif path == "/final":
            self.send_file(FINAL, "video/mp4")
        elif path == "/api/estado":
            self.send_json(state())
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        url = urlparse(self.path)
        if url.path != "/api/trecho":
            self.send_error(404)
            return
        try:
            q = {k: float(v[0]) for k, v in parse_qs(url.query).items()}
            body = self.rfile.read(int(self.headers["Content-Length"]))
            info = save_take(body, q["offset"], q["inicio"], q["fim"], self.headers.get("Content-Type", ""))
            print(f"  trecho {info['inicio']:.1f}s–{info['fim']:.1f}s aplicado → {FINAL}")
        except subprocess.CalledProcessError as exc:
            self.send_json({"erro": exc.stderr.decode("utf-8", "replace")[-400:]}, 500)
            return
        except Exception as exc:  # noqa: BLE001 - devolve qualquer falha para a página
            self.send_json({"erro": str(exc)}, 500)
            return
        self.send_json(state() | {"ultimo": info})

    def send_json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, ctype: str) -> None:
        if not path.exists():
            self.send_error(404)
            return
        size = path.stat().st_size
        start, end = 0, size - 1
        m = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
        if m:
            start = min(int(m[1]), size - 1)
            end = min(int(m[2]), size - 1) if m[2] else end
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with path.open("rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(1 << 20, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except OSError:
                    return
                remaining -= len(chunk)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audio", type=Path, help="áudio gravado em outro aplicativo, alinhado ao início do vídeo")
    parser.add_argument("--offset", type=float, default=0.0, help="segundos a descartar do início do áudio")
    parser.add_argument("--limpar", action="store_true", help="apaga a narração gravada")
    parser.add_argument("--porta", type=int, default=8765)
    args = parser.parse_args()

    if args.limpar:
        shutil.rmtree(WORK, ignore_errors=True)
        FINAL.unlink(missing_ok=True)
        print("Narração apagada.")
        return
    if not SILENT.exists() or not (OUT / "falas.json").exists():
        sys.exit("Gere antes o vídeo: python video/build_video.py")
    if args.audio:
        info = save_take(args.audio.read_bytes(), args.offset, 0.0, state()["duracao"], args.audio.suffix.lower())
        print(f"Narração aplicada ({info['fim'] - info['inicio']:.1f}s): {FINAL}")
        return

    server = ThreadingHTTPServer(("127.0.0.1", args.porta), Studio)
    url = f"http://127.0.0.1:{args.porta}/"
    print(f"Estúdio de narração em {url}  (Ctrl+C para sair)")
    print(f"O vídeo final será salvo em {FINAL}")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
