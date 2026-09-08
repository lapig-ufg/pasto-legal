"""
Teste de integração da tool `generate_property_boletim`.

`app/tools/property_analyst_tools.py` importa `gee_scripts.py`, que inicializa o
Earth Engine na importação do módulo — então este teste precisa de um `.env` real
na raiz do projeto (GEE_PROJECT, GEE_SERVICE_ACCOUNT, GEE_KEY_FILE, APP_ENV),
mesmo não chamando o GEE de fato. Mesma ressalva de tests/ee_scripts/test_pasture_classification.py.

    .venv/bin/python -m pytest tests/pdf/test_generate_property_boletim_tool.py -v
"""
from agno.run import RunContext

from app.tools.analysis_tools import generate_property_boletim
from app.schemas.property_feature import RuralProperty, SpatialFeatures


def _build_context_with_property(rural_property: RuralProperty) -> RunContext:
    return RunContext(
        run_id="test-run",
        session_id="test-session",
        session_state={"all_properties": [rural_property.model_dump()]},
    )


def test_generate_property_boletim_returns_valid_pdf_file():
    rural_property = RuralProperty(
        feature_id="Fazenda Blue",
        car_code="GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0",
        spatial_features=SpatialFeatures(
            total_area=23.4674,
            municipality="Corrego do Ouro",
            coordinates=[[[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]]]],
        ),
    )
    run_context = _build_context_with_property(rural_property)

    result = generate_property_boletim.entrypoint(run_context=run_context, feature_id=rural_property.id)

    assert result.files
    assert result.files[0].content[:5] == b"%PDF-"
    assert result.files[0].mime_type == "application/pdf"
    assert result.files[0].name == f"boletim_{rural_property.car_code}.pdf"

    # O content deve ser a mensagem pronta (determinística, montada em Python) — não um
    # texto genérico que dependeria da LLM reformular/resumir os dados.
    assert "Fazenda Blue" in result.content
    assert "boletim" in result.content.lower()


def test_generate_property_boletim_reports_friendly_error_without_property():
    run_context = RunContext(run_id="test-run", session_id="test-session", session_state={})

    result = generate_property_boletim.entrypoint(run_context=run_context, feature_id="Nenhuma Propriedade")

    assert not getattr(result, "files", None) or result.files is None
