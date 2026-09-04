from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Image as RLImage, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from svglib.svglib import svg2rlg


_PAGE_SIZE = A4

_TOP_MARGIN = 14 * mm
_BOTTOM_MARGIN = 18 * mm
_LEFT_MARGIN = 18 * mm
_RIGHT_MARGIN = 18 * mm

_CONTENT_WIDTH = _PAGE_SIZE[0] - _LEFT_MARGIN - _RIGHT_MARGIN

_LOGO_PATH = Path(__file__).resolve().parents[2] / "assets" / "logos" / "pasto_legal_logo.svg"

# Paleta institucional do LAPIG (Pasto Legal é um projeto do laboratório e segue
# a mesma identidade): https://lapig-ufg.github.io/identidade-visual/
_HEX_GREEN = "#429B4D"
_HEX_DARK_GREEN = "#1B3A2A"
_HEX_TEAL = "#2A9D8F"
_HEX_GOLD = "#C4933F"
_HEX_BROWN = "#6B4C3B"

_COLOR_PRIMARY = colors.HexColor(_HEX_GREEN)
_COLOR_DARK = colors.HexColor(_HEX_DARK_GREEN)
_COLOR_ACCENT = colors.HexColor(_HEX_TEAL)
_COLOR_GOLD = colors.HexColor(_HEX_GOLD)
_COLOR_MUTED_TEXT = colors.HexColor(_HEX_BROWN)
_COLOR_ZEBRA = colors.HexColor("#F1EDE3")
_COLOR_GRID = colors.HexColor("#DDD3C2")
_COLOR_WARNING_BG = colors.HexColor("#FBF0DC")


def _build_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "MastheadTitle": ParagraphStyle(
            "MastheadTitle", parent=base["Title"], fontSize=17, alignment=0, textColor=colors.white, spaceAfter=1 * mm
        ),
        "MastheadSubtitle": ParagraphStyle(
            "MastheadSubtitle", parent=base["Normal"], fontSize=9.5, textColor=_COLOR_GOLD
        ),
        "SectionTitle": ParagraphStyle(
            "SectionTitle", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=12, textColor=colors.white
        ),
        "SubSectionTitle": ParagraphStyle(
            "SubSectionTitle", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=10.5,
            textColor=_COLOR_ACCENT, spaceBefore=3 * mm, spaceAfter=1.5 * mm,
        ),
        "Body": ParagraphStyle("Body", parent=base["Normal"], fontSize=9.5, leading=13, textColor=_COLOR_DARK),
        "TableHeader": ParagraphStyle("TableHeader", parent=base["Normal"], fontSize=9.5, textColor=colors.white, fontName="Helvetica-Bold"),
        "Placeholder": ParagraphStyle(
            "Placeholder", parent=base["Normal"], fontSize=9, leading=12, fontName="Helvetica-Oblique", textColor=_COLOR_MUTED_TEXT
        ),
        "Warning": ParagraphStyle("Warning", parent=base["Normal"], fontSize=9, leading=12, textColor=_COLOR_DARK),
        "Caption": ParagraphStyle("Caption", parent=base["Normal"], fontSize=8, textColor=_COLOR_MUTED_TEXT, alignment=1),
    }


_styles = _build_styles()


def _normalize_widths(weights: Optional[List[float]], count: int) -> List[float]:
    """Escala larguras relativas (ou distribui igualmente) até somar a largura útil da página."""
    if not weights:
        return [_CONTENT_WIDTH / count] * count

    total = sum(weights)
    return [(weight / total) * _CONTENT_WIDTH for weight in weights]


def _fit_image(image_bytes: bytes, max_width: float, max_height: float) -> RLImage:
    """Redimensiona a imagem (preservando proporção) para caber na área disponível."""
    pil_image = PILImage.open(BytesIO(image_bytes))
    aspect = pil_image.width / pil_image.height

    # Pequena folga de segurança para a imagem nunca encostar exatamente na borda da célula.
    max_width *= 0.97
    max_height *= 0.97

    width, height = max_width, max_width / aspect
    if height > max_height:
        height = max_height
        width = max_height * aspect

    return RLImage(BytesIO(image_bytes), width=width, height=height)


def _logo_drawing(height_mm: float = 14):
    """Carrega o SVG oficial do Pasto Legal e escala para a altura desejada."""
    drawing = svg2rlg(str(_LOGO_PATH))
    scale = (height_mm * mm) / drawing.height
    drawing.width *= scale
    drawing.height *= scale
    drawing.scale(scale, scale)
    return drawing


def masthead(title: str, subtitle: str) -> Table:
    """Cabeçalho em faixa verde-escura com a logo oficial — abre o boletim."""
    text_cell = [Paragraph(title, _styles["MastheadTitle"]), Paragraph(subtitle, _styles["MastheadSubtitle"])]

    table = Table([[_logo_drawing(), text_cell]], colWidths=[22 * mm, _CONTENT_WIDTH - 22 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _COLOR_DARK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, 0), "CENTER"),
        ("LEFTPADDING", (0, 0), (0, 0), 6),
        ("LEFTPADDING", (1, 0), (1, 0), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def section_title(text: str) -> Table:
    """Barra de título de seção, colorida e com largura total da página."""
    table = Table([[Paragraph(text, _styles["SectionTitle"])]], colWidths=[_CONTENT_WIDTH])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _COLOR_PRIMARY),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def subsection_title(text: str) -> Paragraph:
    return Paragraph(text, _styles["SubSectionTitle"])


def body_text(text: str) -> Paragraph:
    return Paragraph(text.replace("\n", "<br/>"), _styles["Body"])


def placeholder_note(text: str) -> Paragraph:
    """Texto em itálico/marrom — nota de apoio (ano de referência, ressalvas etc.)."""
    return Paragraph(text.replace("\n", "<br/>"), _styles["Placeholder"])


def warning_box(text: str) -> Table:
    """Caixa de aviso em destaque (tom dourado, dentro da paleta institucional)."""
    table = Table([[Paragraph(f"<b>AVISO:</b> {text}", _styles["Warning"])]], colWidths=[_CONTENT_WIDTH])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _COLOR_WARNING_BG),
        ("BOX", (0, 0), (-1, -1), 0.75, _COLOR_GOLD),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def key_value_table(rows: List[Tuple[str, str]]) -> Table:
    """Tabela de 2 colunas (rótulo -> valor), zebrada."""
    data = [[Paragraph(f"<b>{key}</b>", _styles["Body"]), Paragraph(str(value), _styles["Body"])] for key, value in rows]
    widths = _normalize_widths([0.35, 0.65], 2)

    style = [
        ("GRID", (0, 0), (-1, -1), 0.5, _COLOR_GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]
    for index in range(len(data)):
        if index % 2 == 1:
            style.append(("BACKGROUND", (0, index), (-1, index), _COLOR_ZEBRA))

    table = Table(data, colWidths=widths)
    table.setStyle(TableStyle(style))
    return table


def data_table(headers: List[str], rows: List[List[str]], col_widths: Optional[List[float]] = None) -> Table:
    """Tabela multi-coluna com cabeçalho fixo (repete em quebra de página) e word-wrap automático."""
    widths = _normalize_widths(col_widths, len(headers))

    header_row = [Paragraph(f"<b>{header}</b>", _styles["TableHeader"]) for header in headers]
    body_rows = [[Paragraph(str(cell), _styles["Body"]) for cell in row] for row in rows]
    data = [header_row] + body_rows

    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _COLOR_PRIMARY),
        ("GRID", (0, 0), (-1, -1), 0.5, _COLOR_GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]
    for index in range(1, len(data)):
        if index % 2 == 0:
            style.append(("BACKGROUND", (0, index), (-1, index), _COLOR_ZEBRA))

    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle(style))
    return table


def side_by_side_images(
    left_image_bytes: bytes, right_image_bytes: bytes,
    left_caption: str = "", right_caption: str = "", image_height_mm: float = 55,
) -> Table:
    """Duas imagens lado a lado (ex.: satélite x mapa temático), com legenda opcional embaixo de cada uma."""
    col_width = (_CONTENT_WIDTH - 4 * mm) / 2
    max_height = image_height_mm * mm

    def _cell(image_bytes: bytes, caption: str) -> List[Flowable]:
        content: List[Flowable] = [_fit_image(image_bytes, col_width, max_height)]
        if caption:
            content.append(Spacer(1, 1.5 * mm))
            content.append(Paragraph(caption, _styles["Caption"]))
        return content

    table = Table(
        [[_cell(left_image_bytes, left_caption), _cell(right_image_bytes, right_caption)]],
        colWidths=[col_width, col_width],
    )
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def single_image(image_bytes: bytes, caption: str = "", image_height_mm: float = 70) -> Table:
    """Uma imagem única, centralizada, ocupando a largura total do conteúdo (ex.: mapa de localização)."""
    content: List[Flowable] = [_fit_image(image_bytes, _CONTENT_WIDTH, image_height_mm * mm)]
    if caption:
        content.append(Spacer(1, 1.5 * mm))
        content.append(Paragraph(caption, _styles["Caption"]))

    table = Table([[content]], colWidths=[_CONTENT_WIDTH])
    table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def page_break() -> PageBreak:
    return PageBreak()


def spacer(height_mm: float = 4) -> Spacer:
    return Spacer(1, height_mm * mm)


def _draw_footer(canvas_obj, doc_obj) -> None:
    canvas_obj.saveState()
    canvas_obj.setStrokeColor(_COLOR_GOLD)
    canvas_obj.setLineWidth(0.5)
    canvas_obj.line(_LEFT_MARGIN, 14 * mm, _PAGE_SIZE[0] - _RIGHT_MARGIN, 14 * mm)
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(_COLOR_MUTED_TEXT)
    canvas_obj.drawCentredString(
        _PAGE_SIZE[0] / 2, 10 * mm, f"Pasto Legal · Página {canvas_obj.getPageNumber()}"
    )
    canvas_obj.restoreState()


def render_document(story: List[Flowable]) -> bytes:
    """Renderiza a lista de flowables em um PDF e devolve os bytes prontos para envio."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=_PAGE_SIZE,
        topMargin=_TOP_MARGIN,
        bottomMargin=_BOTTOM_MARGIN,
        leftMargin=_LEFT_MARGIN,
        rightMargin=_RIGHT_MARGIN,
        title="Boletim Pasto Legal",
    )
    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return buffer.getvalue()
