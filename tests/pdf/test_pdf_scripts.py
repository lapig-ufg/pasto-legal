"""
Teste unitário e hermético do helper de PDF (sem GEE, sem credenciais, sem rede).

    .venv/bin/python -m pytest tests/pdf/test_pdf_scripts.py -v
"""
from io import BytesIO

from pypdf import PdfReader

from app.utils.scripts import pdf_scripts as pdf


def _build_sample_story():
    return [
        pdf.document_title("Fazenda Teste"),
        pdf.document_subtitle("Data de Emissão: 24/07/2026"),
        pdf.warning_box("Este boletim contém dados de exemplo (placeholder)."),
        pdf.spacer(4),
        pdf.section_title("1. Análise de Biomassa"),
        pdf.placeholder_note("Dados fictícios para validação de layout."),
        pdf.simulated_bar_table([("2024", 12.4), ("2025", 15.1)], unit="t/ha"),
        pdf.spacer(4),
        pdf.section_title("2. Análise de Pastagem"),
        pdf.subsection_title("Idade"),
        pdf.data_table(["Faixa", "Área"], [["0-2 anos", "120 ha"], ["2-5 anos", "80 ha"]]),
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

    for expected in ["Fazenda Teste", "Análise de Biomassa", "Análise de Pastagem", "Vegetação nativa"]:
        assert expected in text


def test_data_table_paginates_with_many_rows_without_raising():
    rows = [[f"Item {i}", f"{i} ha"] for i in range(200)]
    story = [pdf.section_title("Tabela longa"), pdf.data_table(["Item", "Área"], rows)]

    pdf_bytes = pdf.render_document(story)

    reader = PdfReader(BytesIO(pdf_bytes))
    assert len(reader.pages) > 1


def test_simulated_bar_table_handles_empty_items():
    story = [pdf.section_title("Vazio"), pdf.simulated_bar_table([], unit="t/ha")]

    pdf_bytes = pdf.render_document(story)

    assert pdf_bytes.startswith(b"%PDF-")
