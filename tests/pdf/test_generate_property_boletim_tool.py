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
from app.schemas.rural_property import RuralProperty, SpatialFeatures


def _build_context_with_property(rural_property: RuralProperty) -> RunContext:
    return RunContext(
        run_id="test-run",
        session_id="test-session",
        session_state={"all_properties": [rural_property.model_dump()]},
    )


def test_generate_property_boletim_returns_valid_pdf_file():
    rural_property = RuralProperty(
        nickname="Fazenda Blue",
        car_code="GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0",
        spatial_features=SpatialFeatures(
            total_area=23.4674,
            municipality="Corrego do Ouro",
            # Coordenadas reais da propriedade (não um quadrado fake em 0,0/Golfo da Guiné):
            # o car_code abaixo é o mesmo usado nos testes reais de GEE (test_pasture_*.py),
            # e o cache de classificação é chaveado só por car_code+ano — com uma
            # geometria fake mas o car_code real, esse teste só "passava" antes por
            # colidir com o cache de uma chamada real anterior pra essa propriedade,
            # nunca testando de fato a classificação para o ROI que ele próprio define.
            coordinates=[[[
                [-50.607162816111114, -16.36135684638889], [-50.606766614444446, -16.361637087222224],
                [-50.60604125638889, -16.36089283], [-50.60606698583334, -16.361042615555558],
                [-50.606026783333334, -16.361386239166666], [-50.60578304222222, -16.362651907777778],
                [-50.60566738083333, -16.363175863055556], [-50.605573845555554, -16.363960815],
                [-50.60597653, -16.366481251666666], [-50.60554517027778, -16.366731067777778],
                [-50.605643925833334, -16.36748177388889], [-50.60567877194445, -16.368350606944446],
                [-50.60571016138889, -16.368449547222223], [-50.6058855625, -16.36900242138889],
                [-50.60597792888889, -16.36929356222222], [-50.609982485833335, -16.367532129166666],
                [-50.609450539166666, -16.366629992500002], [-50.6091756175, -16.366369141666667],
                [-50.60874803722222, -16.365129216666666], [-50.60862953694445, -16.364863420833334],
                [-50.607873635833336, -16.363978108333335], [-50.6075727225, -16.36330761638889],
                [-50.607162816111114, -16.36135684638889],
            ]]],
        ),
    )
    run_context = _build_context_with_property(rural_property)

    result = generate_property_boletim.entrypoint(run_context=run_context, car_codes=[rural_property.car_code])

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

    result = generate_property_boletim.entrypoint(run_context=run_context, car_codes=["GO-0000000-00000000000000000000000000000000"])

    assert not getattr(result, "files", None) or result.files is None
