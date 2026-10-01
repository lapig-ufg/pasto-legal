"""
Teste unitário e hermético do report builder do boletim (sem GEE, sem credenciais).

`Feature`/`FeatureMetadata` são puros Pydantic, sem dependência de GEE. As
imagens usadas são PNGs sintéticos (sem depender do satélite) só para exercitar
o layout lado a lado.

    .venv/bin/python -m pytest tests/pdf/test_boletim_scripts.py -v
"""
import os
from io import BytesIO

import datetime

from semente.configs.prompts import set_prompts_dir

# The domain package eagerly imports the GEE-bound agent; mock Earth Engine and
# point the prompts loader at domain/prompts so this stays hermetic.
set_prompts_dir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../domain/prompts"))

import ee  # noqa: E402

ee.ServiceAccountCredentials = lambda *a, **k: object()
ee.Initialize = lambda *a, **k: None

from PIL import Image as PILImage  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from domain.schemas.feature import Feature, FeatureMetadata  # noqa: E402
from domain.schemas.property_stats import (  # noqa: E402
    AgeData,
    AgeStats,
    PastureStats,
    SoilData,
    SoilStats,
    TopographicStats,
    Value,
    VigorData,
    VigorStats,
)
from domain.services.boletim_scripts import (  # noqa: E402
    _format_season_onset,
    _rows_with_percentage,
    build_boletim_story,
    build_placeholder_property_stats,
    compute_property_score,
)
from domain.services.pdf_scripts import render_document  # noqa: E402


def _sample_image_bytes(color=(80, 150, 90)) -> bytes:
    buffer = BytesIO()
    PILImage.new("RGB", (200, 150), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _build_sample_property() -> Feature:
    return Feature(
        feature_id="GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0",
        coords=[[[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]]]],
        metadata=[
            FeatureMetadata(key="car_code", value="GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0"),
            FeatureMetadata(key="name", value="Fazenda Blue"),
        ],
        total_area=23.4674,
        region="Corrego do Ouro",
        feature_type="rural_property",
    )


def _build_full_story(rural_property: Feature, stats, **overrides):
    kwargs = dict(
        location_image_bytes=_sample_image_bytes((150, 130, 100)),
        pasture_map_image_bytes=_sample_image_bytes((40, 120, 60)),
        vigor_map_image_bytes=_sample_image_bytes((215, 25, 28)),
        biomass_map_image_bytes=_sample_image_bytes((120, 60, 40)),
        soil_map_image_bytes=_sample_image_bytes((168, 56, 0)),
    )
    kwargs.update(overrides)
    return build_boletim_story(rural_property, stats, **kwargs)


def test_build_placeholder_property_stats_has_all_sections():
    stats = build_placeholder_property_stats("GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0")

    assert stats.list_pasture_stats
    assert stats.list_pasture_stats[0].biomass_stats

    latest = stats.list_pasture_stats[-1]
    assert latest.age_stats and latest.age_stats.data
    assert latest.vigor_stats and latest.vigor_stats.data
    assert latest.lulc_stats and latest.lulc_stats.data


def test_build_boletim_story_renders_valid_pdf_with_expected_content():
    rural_property = _build_sample_property()
    stats = build_placeholder_property_stats(rural_property.get_metadata("car_code"))

    story = _build_full_story(rural_property, stats)
    pdf_bytes = render_document(story)

    assert pdf_bytes.startswith(b"%PDF-")

    reader = PdfReader(BytesIO(pdf_bytes))
    text = "".join(page.extract_text() for page in reader.pages)

    assert "Fazenda Blue" in text
    assert "Data de Emissão" in text
    # O código CAR aparece no cabeçalho (ID) e pode quebrar em linhas no layout.
    assert "GO-5205703-5B18B6DF441C4B7FA9444DDC127CF" in text
    assert "6C0" in text
    # A imagem de satélite vive na seção numerada 1 ("Localização da
    # Propriedade"), independente do diagnóstico LLM estar vazio.
    assert "1. Localização da Propriedade" in text
    assert "Imagem de satélite com o limite do CAR" in text
    assert "2. Dados de Pastagem" in text
    assert "Análise de Biomassa" in text
    assert "Idade da Pastagem" in text
    assert "Vigor da Pastagem" in text
    assert "Uso e Cobertura do Solo" in text
    assert "Tipos de Solo" in text


def test_build_boletim_story_falls_back_gracefully_without_optional_maps():
    rural_property = _build_sample_property()
    stats = build_placeholder_property_stats(rural_property.get_metadata("car_code"))

    story = _build_full_story(
        rural_property, stats,
        vigor_map_image_bytes=None, biomass_map_image_bytes=None, soil_map_image_bytes=None,
    )
    pdf_bytes = render_document(story)

    assert pdf_bytes.startswith(b"%PDF-")


def test_build_boletim_story_falls_back_to_id_without_name():
    rural_property = _build_sample_property()
    rural_property.metadata = [m for m in rural_property.metadata if m.key != "name"]
    stats = build_placeholder_property_stats(rural_property.get_metadata("car_code"))

    story = _build_full_story(rural_property, stats)
    pdf_bytes = render_document(story)

    reader = PdfReader(BytesIO(pdf_bytes))
    text = reader.pages[0].extract_text()

    # Sem nome, o título do boletim cai para o id (código CAR).
    assert "Fazenda Blue" not in text
    assert "GO-5205703-5B18B6DF441C4B7FA9444DDC127CF" in text
    assert "6C0" in text


def test_build_boletim_story_shows_location_image_without_diagnostic_text():
    """Regressão: a imagem de localização tem seção numerada própria (a 1.),
    então precisa renderizar mesmo com o texto do diagnóstico LLM ausente —
    sem isso, ela sumia do boletim enquanto o agente está desabilitado."""
    rural_property = _build_sample_property()
    stats = build_placeholder_property_stats(rural_property.get_metadata("car_code"))

    story = _build_full_story(rural_property, stats, diagnostic_text=None)
    pdf_bytes = render_document(story)

    reader = PdfReader(BytesIO(pdf_bytes))
    text = "".join(page.extract_text() for page in reader.pages)

    assert "1. Localização da Propriedade" in text
    assert "Imagem de satélite com o limite do CAR" in text
    assert len(reader.pages[0].images) >= 1
    assert "2. Dados de Pastagem" in text
    # Diagnóstico ausente: a seção (e as estrelas) some inteira.
    assert "Diagnóstico do Pasto Legal" not in text


def test_build_boletim_story_includes_diagnostic_section_when_provided():
    rural_property = _build_sample_property()
    stats = build_placeholder_property_stats(rural_property.get_metadata("car_code"))

    story = _build_full_story(
        rural_property, stats, diagnostic_text="Esta propriedade apresenta bom vigor geral.",
    )
    pdf_bytes = render_document(story)

    reader = PdfReader(BytesIO(pdf_bytes))
    text = "".join(page.extract_text() for page in reader.pages)

    assert "Diagnóstico do Pasto Legal" in text
    assert "Esta propriedade apresenta bom vigor geral." in text
    assert "Nota Geral da Propriedade" in text
    # A localização continua na seção 1 mesmo com o diagnóstico presente.
    assert "1. Localização da Propriedade" in text


def test_build_boletim_story_omits_municipio_uf_when_region_is_missing():
    rural_property = _build_sample_property()
    rural_property.region = None
    stats = build_placeholder_property_stats(rural_property.get_metadata("car_code"))

    story = _build_full_story(rural_property, stats)
    pdf_bytes = render_document(story)

    reader = PdfReader(BytesIO(pdf_bytes))
    text = reader.pages[0].extract_text()

    assert "/GO" not in text


def test_build_boletim_story_renders_soil_table_with_percentage():
    rural_property = _build_sample_property()
    stats = build_placeholder_property_stats(rural_property.get_metadata("car_code"))
    soil_stats = SoilStats(
        observation_year=2026,
        data=[
            SoilData(soil_class="Argila", amount=Value(value=15.0, unity="hectares")),
            SoilData(soil_class="Arenoso", amount=Value(value=5.0, unity="hectares")),
        ],
    )

    story = _build_full_story(rural_property, stats, soil_stats=soil_stats)
    pdf_bytes = render_document(story)

    reader = PdfReader(BytesIO(pdf_bytes))
    text = "".join(page.extract_text() for page in reader.pages)

    assert "Argila" in text
    assert "75%" in text  # 15 / (15 + 5)
    assert "25%" in text  # 5 / (15 + 5)


def test_build_boletim_story_includes_new_sections_with_placeholders_when_absent():
    rural_property = _build_sample_property()
    stats = build_placeholder_property_stats(rural_property.get_metadata("car_code"))

    story = _build_full_story(rural_property, stats)
    pdf_bytes = render_document(story)

    reader = PdfReader(BytesIO(pdf_bytes))
    text = "".join(page.extract_text() for page in reader.pages)

    assert "5. Histórico de Biomassa" in text
    assert "Histórico de biomassa indisponível" in text
    assert "6. Dados Topográficos" in text
    assert "Dados topográficos indisponíveis" in text
    assert "7. Panorama Climático" in text
    assert "Panorama climático indisponível" in text


def test_build_boletim_story_renders_biomass_history_section():
    rural_property = _build_sample_property()
    stats = build_placeholder_property_stats(rural_property.get_metadata("car_code"))

    story = _build_full_story(
        rural_property, stats,
        biomass_history_image_bytes=_sample_image_bytes((30, 90, 30)),
        biomass_history_start_year=2000,
        biomass_history_end_year=2024,
        biomass_history_latest_avg_t_ha=3.456,
    )
    pdf_bytes = render_document(story)

    reader = PdfReader(BytesIO(pdf_bytes))
    text = "".join(page.extract_text() for page in reader.pages)

    assert "2000-2024" in text
    assert "3.46 t MS/ha/ano" in text


def test_build_boletim_story_renders_topographic_section():
    rural_property = _build_sample_property()
    stats = build_placeholder_property_stats(rural_property.get_metadata("car_code"))
    topographic_stats = TopographicStats(
        elevation=Value(value=540.2, unity="metros"),
        slope=Value(value=5.3, unity="graus"),
    )

    story = _build_full_story(rural_property, stats, topographic_stats=topographic_stats)
    pdf_bytes = render_document(story)

    reader = PdfReader(BytesIO(pdf_bytes))
    text = "".join(page.extract_text() for page in reader.pages)

    assert "540.2 metros" in text
    assert "5.3 graus" in text


def test_build_boletim_story_renders_climate_section():
    rural_property = _build_sample_property()
    stats = build_placeholder_property_stats(rural_property.get_metadata("car_code"))

    story = _build_full_story(
        rural_property, stats,
        rain_onset="2026-10-15",
        dry_onset="The dry season is currently underway.",
        temperature_outlook={"days": 7, "avg_max_c": 31.2, "avg_min_c": 19.8, "max_c": 34.0, "min_c": 17.5},
        precipitation_outlook=[(datetime.date(2026, 10, 1), 45.3), (datetime.date(2026, 11, 1), 120.7)],
    )
    pdf_bytes = render_document(story)

    reader = PdfReader(BytesIO(pdf_bytes))
    text = "".join(page.extract_text() for page in reader.pages)

    assert "15/10/2026" in text
    assert "A estação seca já está em curso." in text
    assert "19.8" in text and "31.2" in text
    assert "45.3 mm" in text
    assert "120.7 mm" in text


def test_build_boletim_story_shows_missing_forecast_instead_of_fake_zero():
    """Regressão: mês sem previsão (None) nunca vira '0.0 mm' — isso pareceria
    'previsão de zero chuva' quando é só 'sem dado disponível'."""
    rural_property = _build_sample_property()
    stats = build_placeholder_property_stats(rural_property.get_metadata("car_code"))

    story = _build_full_story(
        rural_property, stats,
        precipitation_outlook=[(datetime.date(2026, 10, 1), 45.3), (datetime.date(2026, 11, 1), None)],
    )
    pdf_bytes = render_document(story)

    reader = PdfReader(BytesIO(pdf_bytes))
    text = "".join(page.extract_text() for page in reader.pages)

    assert "45.3 mm" in text
    assert "sem previsão" in text
    assert "0.0 mm" not in text


def test_rows_with_percentage_sums_to_total():
    rows = _rows_with_percentage([
        ("A", Value(value=10.0, unity="ha")),
        ("B", Value(value=30.0, unity="ha")),
    ])

    assert rows[0] == ["A", "10.0 ha", "25%"]
    assert rows[1] == ["B", "30.0 ha", "75%"]


def test_rows_with_percentage_handles_zero_total():
    rows = _rows_with_percentage([("A", Value(value=0.0, unity="ha"))])

    assert rows[0] == ["A", "0.0 ha", "0%"]


def test_format_season_onset_formats_iso_date():
    assert _format_season_onset("2026-10-15") == "15/10/2026"


def test_format_season_onset_translates_known_messages():
    assert _format_season_onset("The rainy season has already begun for this location.") == \
        "A estação chuvosa já começou nesta localização."
    assert _format_season_onset("The dry season is currently underway.") == \
        "A estação seca já está em curso."


def test_format_season_onset_passes_through_none():
    assert _format_season_onset(None) is None


def _vigor_stats(alto_ha=0.0, medio_ha=0.0, baixo_ha=0.0) -> VigorStats:
    data = []
    if alto_ha:
        data.append(VigorData(vigor="Alto: pastagens com alto vigor vegetativo.", amount=Value(value=alto_ha, unity="ha")))
    if medio_ha:
        data.append(VigorData(vigor="Médio: pastagens com médio vigor vegativo.", amount=Value(value=medio_ha, unity="ha")))
    if baixo_ha:
        data.append(VigorData(vigor="Baixo: pastagens com baixo vigor vegetativo.", amount=Value(value=baixo_ha, unity="ha")))
    return VigorStats(observation_year=2024, data=data)


def _age_stats(**by_range) -> AgeStats:
    return AgeStats(observation_year=2024, data=[
        AgeData(age=age_range, amount=Value(value=ha, unity="ha")) for age_range, ha in by_range.items()
    ])


def _soil_stats(**by_class) -> SoilStats:
    return SoilStats(observation_year=2026, data=[
        SoilData(soil_class=soil_class, amount=Value(value=ha, unity="hectares")) for soil_class, ha in by_class.items()
    ])


def test_compute_property_score_defaults_to_floor_without_any_data():
    score = compute_property_score(None, None)

    assert score.stars == 3
    assert "insuficientes" in score.rationale


def test_compute_property_score_never_goes_below_3_even_in_worst_case():
    pasture_stats = PastureStats(vigor_stats=_vigor_stats(baixo_ha=20.0), age_stats=_age_stats(**{"≥40 (idade real indeterminada)": 20.0}))
    soil_stats = _soil_stats(Arenoso=20.0)

    score = compute_property_score(pasture_stats, soil_stats)

    assert score.stars == 3


def test_compute_property_score_rewards_high_vigor():
    pasture_stats = PastureStats(vigor_stats=_vigor_stats(alto_ha=20.0))

    score = compute_property_score(pasture_stats, None)

    assert score.stars == 5
    assert "100%" in score.rationale


def test_compute_property_score_caps_at_5_in_best_case():
    pasture_stats = PastureStats(vigor_stats=_vigor_stats(alto_ha=20.0), age_stats=_age_stats(**{"1-10": 20.0}))
    soil_stats = _soil_stats(Argila=20.0)

    score = compute_property_score(pasture_stats, soil_stats)

    assert score.stars == 5


def test_build_boletim_story_renders_score_alongside_diagnostic():
    rural_property = _build_sample_property()
    stats = build_placeholder_property_stats(rural_property.get_metadata("car_code"))

    story = _build_full_story(rural_property, stats, diagnostic_text="Esta propriedade apresenta bom vigor geral.")
    pdf_bytes = render_document(story)

    reader = PdfReader(BytesIO(pdf_bytes))
    text = reader.pages[0].extract_text()

    assert "Nota Geral da Propriedade" in text
