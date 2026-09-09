"""
Teste unitário e hermético do helper de PDF (sem GEE, sem credenciais, sem rede).

    .venv/bin/python -m pytest tests/pdf/test_pdf_scripts.py -v
"""
from io import BytesIO

from PIL import Image as PILImage
from pypdf import PdfReader

from domain.services import pdf_scripts as pdf


def _sample_image_bytes(color=(80, 150, 90)) -> bytes:
    buffer = BytesIO()
    PILImage.new("RGB", (200, 150), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _build_sample_story():
    return [
        pdf.masthead("Fazenda Teste", "Data de Emissão: 24/07/2026"),
        pdf.warning_box("Este boletim contém dados de exemplo (placeholder)."),
        pdf.spacer(4),
        pdf.section_title("1. Dados de Pastagem"),
        pdf.side_by_side_images(_sample_image_bytes(), _sample_image_bytes((40, 90, 50)), "Satélite", "Pastagem"),
        pdf.placeholder_note("Dados fictícios para validação de layout."),
        pdf.subsection_title("Idade"),
        pdf.data_table(["Faixa", "Área"], [["0-2 anos", "120 ha"], ["2-5 anos", "80 ha"]]),
        pdf.spacer(4),
        pdf.section_title("2. Análise de Biomassa"),
        pdf.key_value_table([("Pastagem", "210 ha"), ("Vegetação nativa", "35 ha")]),
    ]


def test_render_document_returns_valid_pdf_bytes():
    pdf_bytes = pdf.render_document(_build_sample_story())

    assert pdf_bytes.startswith(b"%PDF-")

    reader = PdfReader(BytesIO(pdf_bytes))
    assert len(reader.pages) >= 1


def test_render_document_extracts_expected_text():
    pdf_bytes = pdf.render_document(_build_sample_story())
    reader = PdfReader(BytesIO(pdf_bytes))
    text = reader.pages[0].extract_text()

    for expected in ["Fazenda Teste", "Dados de Pastagem", "Análise de Biomassa", "Vegetação nativa"]:
        assert expected in text


def test_data_table_paginates_with_many_rows_without_raising():
    rows = [[f"Item {i}", f"{i} ha"] for i in range(200)]
    story = [pdf.section_title("Tabela longa"), pdf.data_table(["Item", "Área"], rows)]

    pdf_bytes = pdf.render_document(story)

    reader = PdfReader(BytesIO(pdf_bytes))
    assert len(reader.pages) > 1


def test_side_by_side_images_renders_valid_pdf():
    story = [
        pdf.section_title("Imagens"),
        pdf.side_by_side_images(_sample_image_bytes(), _sample_image_bytes((40, 90, 50)), "Esquerda", "Direita"),
    ]

    pdf_bytes = pdf.render_document(story)

    assert pdf_bytes.startswith(b"%PDF-")
