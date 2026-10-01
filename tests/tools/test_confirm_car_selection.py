"""
Testes da tool `confirm_car_selection`, incluindo o caminho com `name` opcional
(confirmação + nome na mesma mensagem) — regressão do bug em que
`registration_state` ficava travado em "final" pra sempre quando o usuário
respondia confirmação e nome juntos, porque `complete_registration` só fica
disponível pro agente DEPOIS que esse estado já foi setado (nunca no mesmo
turno da confirmação).

`domain/tools/property_tools.py` importa `gee.py`, que inicializa o Earth
Engine na importação do módulo — então este teste precisa de um `.env` real na
raiz do projeto (GEE_PROJECT, GEE_SERVICE_ACCOUNT, GEE_KEY_FILE), mesma
ressalva de tests/tools/test_start_registration_by_geojson.py.

    .venv/bin/python -m pytest tests/tools/test_confirm_car_selection.py -v
"""
from semente.backends.toolkit import StateContext

from domain.tools import property_tools


def _context(**session_state) -> StateContext:
    return StateContext(session_state=session_state)


def _candidate_property() -> dict:
    return {
        "feature_id": "GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0",
        "coords": [[[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]]]],
        "metadata": [],
        "total_area": 23.4674,
        "region": "Corrego do Ouro",
        "feature_type": "rural_property",
    }


def test_confirm_car_selection_without_name_leaves_registration_pending_for_naming():
    run_context = _context(candidate_properties=[_candidate_property()])

    property_tools.confirm_car_selection(run_context=run_context)

    assert run_context.session_state["registration_state"] == "final"
    assert run_context.session_state.get("all_properties") is None


def test_confirm_car_selection_with_name_completes_registration_immediately():
    run_context = _context(candidate_properties=[_candidate_property()])

    result = property_tools.confirm_car_selection(run_context=run_context, name="Fazenda Jaraguá")

    # A causa raiz do bug: sem isto, `registration_state` ficava em "final" e o
    # agente perdia acesso às tools de análise até outro turno responder o nome.
    assert run_context.session_state["registration_state"] is None
    assert run_context.session_state["candidate_properties"] is None

    registered = run_context.session_state["all_properties"]["features"]
    # feature_id stays stable (CAR); the name lives in metadata.
    assert [feature["feature_id"] for feature in registered] == [
        "GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0"
    ]
    assert [next(e["value"] for e in feature["metadata"] if e["key"] == "name") for feature in registered] == [
        "Fazenda Jaraguá"
    ]
    assert "Fazenda Jaraguá" in result.content


def test_confirm_car_selection_without_pending_property_reports_friendly_message():
    run_context = _context()

    result = property_tools.confirm_car_selection(run_context=run_context, name="Fazenda Jaraguá")

    assert run_context.session_state.get("all_properties") is None
    assert result.content