from io import BytesIO
from typing import List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


_PAGE_SIZE = A4

_TOP_MARGIN = 20 * mm
_BOTTOM_MARGIN = 18 * mm
_LEFT_MARGIN = 18 * mm
_RIGHT_MARGIN = 18 * mm

_CONTENT_WIDTH = _PAGE_SIZE[0] - _LEFT_MARGIN - _RIGHT_MARGIN

# Paleta extraída de pasto.legal (modo claro): verde escuro da marca (títulos,
# CTAs), verde vibrante (destaques) e o "ink" navy usado no corpo de texto do site.
_HEX_PRIMARY = "#206107"
_HEX_ACCENT = "#2DAD56"
_HEX_INK = "#1A252F"

_COLOR_PRIMARY = colors.HexColor(_HEX_PRIMARY)
_COLOR_ACCENT = colors.HexColor(_HEX_ACCENT)
_COLOR_INK = colors.HexColor(_HEX_INK)
_COLOR_ZEBRA = colors.HexColor("#F1F5F1")
_COLOR_GRID = colors.HexColor("#DCE3DC")
_COLOR_WARNING_BG = colors.HexColor("#FFF3CD")
_COLOR_WARNING_BORDER = colors.HexColor("#FFECB5")
_COLOR_PLACEHOLDER_TEXT = colors.HexColor("#5B6B63")
_COLOR_FOOTER_TEXT = colors.HexColor("#5B6B63")

_BAR_MAX_WIDTH = 70 * mm


def _build_styles() -> dict:
    base = getSampleStyleSheet()
    styles = {
        "BrandHeader": ParagraphStyle(
            "BrandHeader", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=11,
            spaceAfter=4 * mm, characterSpace=0.5,
        ),
        "DocumentTitle": ParagraphStyle(
            "DocumentTitle", parent=base["Title"], fontSize=18, spaceAfter=2 * mm, textColor=_COLOR_INK
        ),
        "DocumentSubtitle": ParagraphStyle(
            "DocumentSubtitle", parent=base["Normal"], fontSize=10, textColor=_COLOR_PLACEHOLDER_TEXT, spaceAfter=4 * mm
        ),
        "SectionTitle": ParagraphStyle(
            "SectionTitle", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=12, textColor=colors.white
        ),
        "SubSectionTitle": ParagraphStyle(
            "SubSectionTitle", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=10.5,
            textColor=_COLOR_PRIMARY, spaceBefore=3 * mm, spaceAfter=1.5 * mm,
        ),
        "Body": ParagraphStyle("Body", parent=base["Normal"], fontSize=9.5, leading=13, textColor=_COLOR_INK),
        "TableHeader": ParagraphStyle("TableHeader", parent=base["Normal"], fontSize=9.5, textColor=colors.white, fontName="Helvetica-Bold"),
        "Placeholder": ParagraphStyle(
            "Placeholder", parent=base["Normal"], fontSize=9, leading=12, fontName="Helvetica-Oblique", textColor=_COLOR_PLACEHOLDER_TEXT
        ),
        "Warning": ParagraphStyle("Warning", parent=base["Normal"], fontSize=9, leading=12, textColor=colors.HexColor("#664D03")),
        "Caption": ParagraphStyle("Caption", parent=base["Normal"], fontSize=8, textColor=_COLOR_FOOTER_TEXT),
    }
    return styles


_styles = _build_styles()


def _normalize_widths(weights: Optional[List[float]], count: int) -> List[float]:
    """Escala larguras relativas (ou distribui igualmente) até somar a largura útil da página."""
    if not weights:
        return [_CONTENT_WIDTH / count] * count

    total = sum(weights)
    return [(weight / total) * _CONTENT_WIDTH for weight in weights]


def brand_header() -> Paragraph:
    """Wordmark 'Pasto' (verde) + 'Legal' (navy), igual ao logo do site."""
    markup = f'<font color="{_HEX_PRIMARY}">Pasto</font><font color="{_HEX_INK}">Legal</font>'
    return Paragraph(markup, _styles["BrandHeader"])


def document_title(text: str) -> Paragraph:
    return Paragraph(text, _styles["DocumentTitle"])


def document_subtitle(text: str) -> Paragraph:
    return Paragraph(text, _styles["DocumentSubtitle"])


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
    """Texto em itálico/cinza — marca visualmente um trecho como dado de exemplo."""
    return Paragraph(text.replace("\n", "<br/>"), _styles["Placeholder"])


def warning_box(text: str) -> Table:
    """Caixa de aviso em destaque (usada para o alerta de dados de exemplo)."""
    table = Table([[Paragraph(f"<b>AVISO:</b> {text}", _styles["Warning"])]], colWidths=[_CONTENT_WIDTH])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _COLOR_WARNING_BG),
        ("BOX", (0, 0), (-1, -1), 0.75, _COLOR_WARNING_BORDER),
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


def simulated_bar_table(items: List[Tuple[str, float]], unit: str = "", max_value: Optional[float] = None) -> Flowable:
    """Tabela com barras de progresso simuladas (placeholder de gráfico), sem depender de matplotlib."""
    if not items:
        return placeholder_note("Sem dados disponíveis.")

    reference = max_value or max((value for _, value in items), default=0) or 1

    rows = []
    for label, value in items:
        bar_width = max((value / reference) * _BAR_MAX_WIDTH, 1 * mm)
        bar = Table([[""]], colWidths=[bar_width], rowHeights=[5 * mm])
        bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _COLOR_ACCENT)]))

        value_text = f"{value:g} {unit}".strip()
        rows.append([Paragraph(label, _styles["Body"]), bar, Paragraph(value_text, _styles["Caption"])])

    widths = _normalize_widths([0.3, 0.45, 0.25], 3)
    table = Table(rows, colWidths=widths)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def page_break() -> PageBreak:
    return PageBreak()


def spacer(height_mm: float = 4) -> Spacer:
    return Spacer(1, height_mm * mm)


def _draw_footer(canvas_obj, doc_obj) -> None:
    canvas_obj.saveState()
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(_COLOR_FOOTER_TEXT)
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
