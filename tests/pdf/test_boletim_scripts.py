"""
Teste unitário e hermético do report builder do boletim (sem GEE, sem credenciais).

`RuralProperty`/`SpatialFeatures` são puros Pydantic, sem dependência de GEE.

    .venv/bin/python -m pytest tests/pdf/test_boletim_scripts.py -v
"""
from io import BytesIO

from pypdf import PdfReader

from app.utils.interfaces.property_record import RuralProperty, SpatialFeatures
from app.utils.scripts.boletim_scripts import build_boletim_story, build_placeholder_property_stats
from app.utils.scripts.pdf_scripts import render_document


def _build_sample_property() -> RuralProperty:
    return RuralProperty(
        nickname="Fazenda Blue",
        car_code="GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0",
        spatial_features=SpatialFeatures(
            total_area=23.4674,
            municipality="Corrego do Ouro",
            coordinates=[[[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]]]],
        ),
    )


def test_build_placeholder_property_stats_has_all_sections():
    stats = build_placeholder_property_stats("GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0")

    assert stats.list_pasture_stats
    assert all(item.biomass_stats for item in stats.list_pasture_stats)

    latest = stats.list_pasture_stats[-1]
    assert latest.age_stats and latest.age_stats.data
    assert latest.vigor_stats and latest.vigor_stats.data
    assert latest.lulc_stats and latest.lulc_stats.data


def test_build_boletim_story_renders_valid_pdf_with_expected_content():
    rural_property = _build_sample_property()
    stats = build_placeholder_property_stats(rural_property.car_code)

    story = build_boletim_story(rural_property, stats)
    pdf_bytes = render_document(story)

    assert pdf_bytes.startswith(b"%PDF-")

    reader = PdfReader(BytesIO(pdf_bytes))
    text = reader.pages[0].extract_text()

    assert "Fazenda Blue" in text
    assert "Data de Emissão" in text
    assert rural_property.car_code in text
    assert "Análise de Biomassa" in text
    assert "Análise de Pastagem" in text
    assert "Idade da Pastagem" in text
    assert "Vigor da Pastagem" in text
    assert "Uso e Cobertura do Solo" in text


def test_build_boletim_story_falls_back_gracefully_without_nickname():
    rural_property = _build_sample_property()
    rural_property.nickname = None
    stats = build_placeholder_property_stats(rural_property.car_code)

    story = build_boletim_story(rural_property, stats)
    pdf_bytes = render_document(story)

    reader = PdfReader(BytesIO(pdf_bytes))
    text = reader.pages[0].extract_text()

    assert rural_property.car_code in text
