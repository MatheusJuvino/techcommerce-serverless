"""Gera entrega/relatorio_tecnico.pdf a partir de docs/relatorio_tecnico.md e docs/capa.json.

Suporta um subconjunto de Markdown: títulos (#, ##, ###), parágrafos, listas, tabelas, blocos de
código, citações (>), imagens e marcadores especiais [[TOC]] e [[PAGEBREAK]].

Convenções:
    Tabela: Título da tabela        (linha antes da tabela -> legenda numerada acima)
    ![Título da figura](caminho)    (legenda numerada acima da figura)
    Fonte: texto                    (linha logo após tabela/figura -> fonte abaixo)

Uso:
    python scripts/build_report.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, CondPageBreak, Frame, Image, KeepTogether, NextPageTemplate, PageBreak, PageTemplate,
    Paragraph, Preformatted, Spacer, Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "relatorio_tecnico.md"
COVER = ROOT / "docs" / "capa.json"
OUTPUT = ROOT / "entrega" / "relatorio_tecnico.pdf"

NAVY = colors.HexColor("#1f2d3d")
ACCENT = colors.HexColor("#e7740c")
LIGHT = colors.HexColor("#f3f5f8")
GRID = colors.HexColor("#c9d1db")


# ---------------------------------------------------------------- fontes
def register_fonts() -> tuple[str, str]:
    candidates = [
        ("Body", {"normal": "times.ttf", "bold": "timesbd.ttf", "italic": "timesi.ttf", "boldItalic": "timesbi.ttf"}),
    ]
    font_dirs = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/msttcorefonts"), Path("/Library/Fonts")]
    body, mono = "Times-Roman", "Courier"
    for family, files in candidates:
        for directory in font_dirs:
            if all((directory / f).exists() for f in files.values()):
                for variant, f in files.items():
                    name = family if variant == "normal" else f"{family}-{variant}"
                    pdfmetrics.registerFont(TTFont(name, str(directory / f)))
                pdfmetrics.registerFontFamily(family, normal=family, bold=f"{family}-bold",
                                              italic=f"{family}-italic", boldItalic=f"{family}-boldItalic")
                body = family
                break
    for directory in font_dirs:
        if (directory / "consola.ttf").exists():
            pdfmetrics.registerFont(TTFont("Mono", str(directory / "consola.ttf")))
            pdfmetrics.registerFont(TTFont("Mono-bold", str(directory / "consolab.ttf")))
            pdfmetrics.registerFontFamily("Mono", normal="Mono", bold="Mono-bold", italic="Mono", boldItalic="Mono-bold")
            mono = "Mono"
            break
    return body, mono


BODY, MONO = register_fonts()


def bold_font() -> str:
    return f"{BODY}-bold" if BODY == "Body" else "Times-Bold"


# ---------------------------------------------------------------- estilos
STYLES = {
    "body": ParagraphStyle("body", fontName=BODY, fontSize=12, leading=18, alignment=TA_JUSTIFY,
                           firstLineIndent=1.25 * cm, spaceAfter=6),
    "h1": ParagraphStyle("h1", fontName=bold_font(), fontSize=13, leading=18, spaceBefore=6, spaceAfter=14,
                         textColor=NAVY),
    "h2": ParagraphStyle("h2", fontName=bold_font(), fontSize=12, leading=17, spaceBefore=12, spaceAfter=8,
                         textColor=NAVY),
    "h3": ParagraphStyle("h3", fontName=f"{BODY}-boldItalic" if BODY == "Body" else "Times-BoldItalic",
                         fontSize=12, leading=17, spaceBefore=10, spaceAfter=6, textColor=NAVY),
    "unnumbered": ParagraphStyle("unnumbered", fontName=bold_font(), fontSize=13, leading=18, alignment=TA_CENTER,
                                 spaceAfter=18, textColor=NAVY),
    "bullet": ParagraphStyle("bullet", fontName=BODY, fontSize=12, leading=17, alignment=TA_JUSTIFY,
                             leftIndent=1.0 * cm, bulletIndent=0.4 * cm, spaceAfter=3),
    "caption": ParagraphStyle("caption", fontName=bold_font(), fontSize=10, leading=13, alignment=TA_CENTER,
                              spaceBefore=8, spaceAfter=4),
    "source": ParagraphStyle("source", fontName=BODY, fontSize=10, leading=12, alignment=TA_CENTER, spaceAfter=10),
    "cell": ParagraphStyle("cell", fontName=BODY, fontSize=9.5, leading=12, alignment=TA_LEFT),
    "cellhead": ParagraphStyle("cellhead", fontName=bold_font(), fontSize=9.5, leading=12, textColor=colors.white),
    "code": ParagraphStyle("code", fontName=MONO, fontSize=8, leading=10.2, backColor=LIGHT, borderPadding=6,
                           spaceBefore=4, spaceAfter=10, leftIndent=4, rightIndent=4),
    "quote": ParagraphStyle("quote", fontName=BODY, fontSize=11, leading=15.5, alignment=TA_JUSTIFY,
                            backColor=colors.HexColor("#fff6ea"), borderColor=ACCENT, borderWidth=0,
                            borderPadding=8, leftIndent=6, rightIndent=6, spaceBefore=6, spaceAfter=12),
    "ref": ParagraphStyle("ref", fontName=BODY, fontSize=12, leading=14, alignment=TA_LEFT, spaceAfter=10),
    "toc_title": ParagraphStyle("toc_title", fontName=bold_font(), fontSize=13, alignment=TA_CENTER, spaceAfter=18,
                                textColor=NAVY),
}
TOC_LEVELS = [
    ParagraphStyle("toc1", fontName=bold_font(), fontSize=11.5, leading=16, leftIndent=0, firstLineIndent=0),
    ParagraphStyle("toc2", fontName=BODY, fontSize=11.5, leading=15, leftIndent=0.8 * cm, firstLineIndent=0),
    ParagraphStyle("toc3", fontName=BODY, fontSize=11, leading=14, leftIndent=1.6 * cm, firstLineIndent=0),
]


# ---------------------------------------------------------------- inline markdown
def inline(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    codes: list[str] = []

    def stash(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<link href="\2" color="#1f5fa8">\1</link>', text)
    return re.sub(r"\x00(\d+)\x00", lambda m: f'<font name="{MONO}" size="9.5">{codes[int(m.group(1))]}</font>', text)


# ---------------------------------------------------------------- documento
class ReportDoc(BaseDocTemplate):
    def __init__(self, filename, cover: dict):
        super().__init__(filename, pagesize=A4, leftMargin=3 * cm, rightMargin=2 * cm, topMargin=3 * cm,
                         bottomMargin=2 * cm, title=cover["titulo"].title(), author=", ".join(cover["autores"]),
                         subject=cover["disciplina"], creator="scripts/build_report.py")
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="main")
        self.cover = cover
        self.addPageTemplates([
            PageTemplate("cover", [frame], onPage=self._cover_page),
            PageTemplate("pre", [frame], onPage=self._pre_page),
            PageTemplate("body", [frame], onPage=self._body_page),
        ])
        self._heading_seq = 0

    def _cover_page(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, A4[1] - 1.1 * cm, A4[0], 1.1 * cm, stroke=0, fill=1)
        canvas.setFillColor(ACCENT)
        canvas.rect(0, A4[1] - 1.25 * cm, A4[0], 0.15 * cm, stroke=0, fill=1)
        canvas.restoreState()

    def _pre_page(self, canvas, doc):
        pass

    def _body_page(self, canvas, doc):
        canvas.saveState()
        canvas.setFont(BODY, 10)
        canvas.setFillColor(colors.HexColor("#5b6675"))
        canvas.drawRightString(A4[0] - 2 * cm, A4[1] - 2 * cm, str(doc.page))
        canvas.drawString(3 * cm, A4[1] - 2 * cm, "TechCommerce Serverless — Relatório Técnico")
        canvas.setStrokeColor(GRID)
        canvas.line(3 * cm, A4[1] - 2.15 * cm, A4[0] - 2 * cm, A4[1] - 2.15 * cm)
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and getattr(flowable, "toc_level", None) is not None:
            level = flowable.toc_level
            text = flowable.getPlainText()
            key = f"h{self._heading_seq}"
            self._heading_seq += 1
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=level, closed=level > 0)
            self.notify("TOCEntry", (level, text, self.page, key))

    def handle_documentBegin(self):
        self._heading_seq = 0
        super().handle_documentBegin()


def heading(text: str, level: int) -> Paragraph:
    style = {0: STYLES["h1"], 1: STYLES["h2"], 2: STYLES["h3"]}[level]
    p = Paragraph(inline(text), style)
    p.toc_level = level
    return p


def cover_story(cover: dict) -> list:
    center = ParagraphStyle("c", fontName=bold_font(), fontSize=13, leading=18, alignment=TA_CENTER)
    center_normal = ParagraphStyle("cn", fontName=BODY, fontSize=12, leading=17, alignment=TA_CENTER)
    title = ParagraphStyle("t", fontName=bold_font(), fontSize=17, leading=24, alignment=TA_CENTER, textColor=NAVY)
    subtitle = ParagraphStyle("st", fontName=BODY, fontSize=13, leading=18, alignment=TA_CENTER, textColor=ACCENT)
    nature = ParagraphStyle("n", fontName=BODY, fontSize=11, leading=15, alignment=TA_JUSTIFY, leftIndent=8 * cm)
    authors = "<br/>".join(inline(a) for a in cover["autores"])
    story = [
        NextPageTemplate("pre"),
        Paragraph(cover["instituicao"], center), Spacer(1, 4),
        Paragraph(inline(cover["curso"]), center_normal),
        Paragraph(inline(cover["disciplina"]), center_normal),
        Spacer(1, 2.2 * cm),
        Paragraph(authors, center_normal),
        Spacer(1, 4.2 * cm),
        Paragraph(cover["titulo"], title), Spacer(1, 8),
        Paragraph(inline(cover["subtitulo"]), subtitle),
        Spacer(1, 7.2 * cm),
        Paragraph(f"{inline(cover['cidade'])}<br/>{cover['ano']}", center_normal),
        PageBreak(),
        # folha de rosto
        Paragraph(authors, center_normal), Spacer(1, 6 * cm),
        Paragraph(cover["titulo"], title), Spacer(1, 8),
        Paragraph(inline(cover["subtitulo"]), subtitle), Spacer(1, 2.5 * cm),
        Paragraph(inline(cover["natureza"]), nature), Spacer(1, 10),
        Paragraph(f"Professor(a): {inline(cover['professor'])}", nature),
        Spacer(1, 5.5 * cm),
        Paragraph(f"{inline(cover['cidade'])}<br/>{cover['ano']}", center_normal),
        PageBreak(),
    ]
    return story


def _longest_word_width(cell: str) -> float:
    widest = 0.0
    for idx, segment in enumerate(cell.split("`")):
        font = MONO if idx % 2 else BODY
        for word in re.sub(r"\*", "", segment).split():
            widest = max(widest, pdfmetrics.stringWidth(word, font, 9.5))
    return widest + 13


def column_widths(rows: list[list[str]], total: float) -> list[float]:
    cols = range(len(rows[0]))
    weights = [min(max(max(len(re.sub(r"[`*]", "", r[c])) for r in rows if c < len(r)), 6), 55) for c in cols]
    minimums = [min(max(_longest_word_width(r[c]) for r in rows if c < len(r)), total * 0.45) for c in cols]
    widths = [w * total / sum(weights) for w in weights]
    for _ in range(len(widths)):
        short = [c for c in cols if widths[c] < minimums[c] - 0.01]
        if not short:
            break
        for c in short:
            widths[c] = minimums[c]
        flexible = [c for c in cols if c not in short and widths[c] > minimums[c]]
        excess = sum(widths) - total
        pool = sum(widths[c] for c in flexible)
        for c in flexible:
            widths[c] -= excess * widths[c] / pool
    return widths


def build_table(rows: list[list[str]], width: float) -> Table:
    data = [[Paragraph(inline(c), STYLES["cellhead"]) for c in rows[0]]]
    data += [[Paragraph(inline(c), STYLES["cell"]) for c in r] for r in rows[1:]]
    table = Table(data, colWidths=column_widths(rows, width), repeatRows=1, hAlign="CENTER")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def build_image(path: str, width: float, max_height: float = 21 * cm, scale: float = 1.0) -> Image:
    full = (ROOT / path).resolve()
    reader = ImageReader(str(full))
    iw, ih = reader.getSize()
    w = width * scale
    h = w * ih / iw
    if h > max_height:
        h = max_height
        w = h * iw / ih
    return Image(str(full), width=w, height=h)


def parse_markdown(md: str, width: float) -> list:
    lines = md.splitlines()
    story: list = []
    paragraph: list[str] = []
    figure_no = table_no = 0
    pending_table_caption = None
    i = 0

    def flush():
        if paragraph:
            story.append(Paragraph(inline(" ".join(paragraph)), STYLES["body"]))
            paragraph.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            story.append(Preformatted("\n".join(block), STYLES["code"]))
        elif stripped == "[[TOC]]":
            flush()
            toc = TableOfContents()
            toc.levelStyles = TOC_LEVELS
            toc.dotsMinLevel = 0
            story += [Paragraph("SUMÁRIO", STYLES["toc_title"]), toc]
        elif stripped == "[[PAGEBREAK]]":
            flush()
            story.append(PageBreak())
        elif stripped == "[[BODY]]":
            flush()
            story.append(NextPageTemplate("body"))
        elif stripped.startswith("#"):
            flush()
            level = len(stripped) - len(stripped.lstrip("#"))
            text = stripped[level:].strip()
            if text.startswith("!"):
                story.append(Paragraph(inline(text[1:].strip()), STYLES["unnumbered"]))
            else:
                if level == 1:
                    story.append(PageBreak())
                else:
                    story.append(CondPageBreak(3 * cm))
                story.append(heading(text, level - 1))
        elif stripped.startswith("Tabela:"):
            flush()
            pending_table_caption = stripped[len("Tabela:"):].strip()
        elif stripped.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            i -= 1
            parts = []
            if pending_table_caption:
                table_no += 1
                parts.append(Paragraph(f"Tabela {table_no} – {inline(pending_table_caption)}", STYLES["caption"]))
                pending_table_caption = None
            parts.append(build_table(rows, width))
            if i + 1 < len(lines) and lines[i + 1].strip().startswith("Fonte:"):
                i += 1
                parts.append(Paragraph(inline(lines[i].strip()), STYLES["source"]))
            else:
                parts.append(Spacer(1, 10))
            story.append(KeepTogether(parts))
        elif re.match(r"!\[", stripped):
            flush()
            m = re.match(r"!\[(.*?)\]\((.*?)\)(\{scale=([\d.]+)\})?", stripped)
            figure_no += 1
            parts = [Paragraph(f"Figura {figure_no} – {inline(m.group(1))}", STYLES["caption"]),
                     build_image(m.group(2), width, scale=float(m.group(4) or 1.0))]
            if i + 1 < len(lines) and lines[i + 1].strip().startswith("Fonte:"):
                i += 1
                parts.append(Paragraph(inline(lines[i].strip()), STYLES["source"]))
            story.append(KeepTogether(parts))
        elif re.match(r"^(\s*)([-*]|\d+\.)\s+", line):
            flush()
            m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)", line)
            indent = len(m.group(1)) // 2
            text = m.group(3)
            while i + 1 < len(lines) and lines[i + 1].startswith("  " * (indent + 1)) and not re.match(
                    r"^\s*([-*]|\d+\.)\s+", lines[i + 1]):
                i += 1
                text += " " + lines[i].strip()
            bullet = "•" if m.group(2) in "-*" else m.group(2)
            style = ParagraphStyle(f"b{indent}", parent=STYLES["bullet"], leftIndent=(1.0 + 0.7 * indent) * cm,
                                   bulletIndent=(0.4 + 0.7 * indent) * cm)
            story.append(Paragraph(inline(text), style, bulletText=bullet))
        elif stripped.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            i -= 1
            story.append(Paragraph(inline(" ".join(quote)), STYLES["quote"]))
        elif stripped.startswith("REF:"):
            flush()
            story.append(Paragraph(inline(stripped[4:].strip()), STYLES["ref"]))
        elif not stripped:
            flush()
        else:
            paragraph.append(stripped)
        i += 1
    flush()
    return story


def video_section(cover: dict) -> list:
    url = cover.get("video_url") or ""
    box = ParagraphStyle("vb", parent=STYLES["body"], firstLineIndent=0, alignment=TA_LEFT, backColor=LIGHT,
                         borderPadding=10, spaceBefore=10)
    text = (f'<b>Link do vídeo pitch:</b> <link href="{url}" color="#1f5fa8">{url}</link>' if url else
            "<b>Link do vídeo pitch (YouTube – não listado):</b> ____________________________________________<br/>"
            "<i>[Inserir o link após a gravação e a publicação; preencher o campo \"video_url\" em docs/capa.json "
            "e executar novamente scripts/build_report.py.]</i>")
    p = heading("APÊNDICE B – LINK DO VÍDEO PITCH", 0)
    return [PageBreak(), p, Paragraph(text, box)]


def main() -> None:
    cover = json.loads(COVER.read_text(encoding="utf-8"))
    doc = ReportDoc(str(OUTPUT), cover)
    repo = cover.get("repositorio_url") or ""
    md = SOURCE.read_text(encoding="utf-8").replace(
        "{{REPOSITORIO}}", f"[{repo}]({repo})" if repo else "[inserir o link do repositório, se publicado]")
    story = cover_story(cover) + parse_markdown(md, doc.width) + video_section(cover)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc.multiBuild(story)
    print(f"PDF gerado: {OUTPUT} ({doc.page} páginas)")


if __name__ == "__main__":
    main()
