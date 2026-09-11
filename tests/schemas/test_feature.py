"""
Testes unitários e herméticos do schema geral de feições (sem GEE, sem credenciais).

    PYTHONPATH=. uv run pytest tests/schemas/test_feature.py -v
"""
from agno.run import RunContext

from app.schemas.feature import Feature, FeatureMetadata, RegisteredFeatures
from app.utils.feature_utils import find_feature_record, resolve_feature


_SQUARE_COORDS = [[[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]]]


def _build_rural_property(**overrides) -> Feature:
    kwargs = dict(
        feature_id="GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0",
        coords=_SQUARE_COORDS,
        metadata=[
            FeatureMetadata(key="car_code", value="GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0"),
            FeatureMetadata(key="status", value="AT"),
        ],
        total_area=23.4674,
        region="Corrego do Ouro",
        feature_type="rural_property",
    )
    kwargs.update(overrides)
    return Feature(**kwargs)


def _build_buffer_area(**overrides) -> Feature:
    kwargs = dict(
        feature_id="a1b2c3d4e5f6",
        coords=_SQUARE_COORDS,
        metadata=[
            FeatureMetadata(key="radius", value=200),
        ],
        total_area=12.57,
        region=None,
        feature_type="buffer_area",
    )
    kwargs.update(overrides)
    return Feature(**kwargs)


def test_feature_round_trips_through_model_dump_and_validate():
    feature = _build_rural_property()

    record = feature.model_dump()
    rebuilt = Feature.model_validate(record)

    assert rebuilt == feature
    assert rebuilt.get_metadata("car_code") == "GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0"
    assert rebuilt.get_metadata("status") == "AT"
    assert rebuilt.get_metadata("missing", default="x") == "x"


def test_id_is_feature_id():
    assert _build_rural_property().id == "GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0"

    unnamed = _build_rural_property(feature_id=None)
    assert unnamed.id is None


def test_describe_includes_id_type_area_region_and_metadata():
    description = _build_rural_property().describe()

    assert "Identificador: GO-5205703" in description
    assert "Tipo: rural_property" in description
    assert "Área: 23.4674 ha" in description
    assert "Região: Corrego do Ouro" in description
    assert "car_code: GO-5205703" in description


def test_get_centroid_returns_lat_lon_pair():
    lat, lon = _build_rural_property().get_centroid()

    assert lat == 0.5
    assert lon == 0.5


def test_unify_combines_features_of_same_type():
    first = _build_rural_property()
    second = _build_rural_property(
        feature_id="GO-9999999-5B18B6DF441C4B7FA9444DDC127CF6C0",
        metadata=[FeatureMetadata(key="car_code", value="GO-9999999-5B18B6DF441C4B7FA9444DDC127CF6C0")],
        total_area=10.0,
    )

    unified = Feature.unify([first, second])

    assert unified.total_area == 33.4674
    assert unified.feature_type == "rural_property"
    assert len(unified.coords) == 2
    assert unified.get_metadata("car_code") == (
        "GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0, GO-9999999-5B18B6DF441C4B7FA9444DDC127CF6C0"
    )
    assert unified.get_metadata("status") == "AT"


def test_unify_returns_none_for_empty_list():
    assert Feature.unify([]) is None


def test_generate_id_is_unique():
    assert Feature.generate_id() != Feature.generate_id()
    assert len(Feature.generate_id()) == 12


def test_build_prompt_clusters_features_by_type():
    registered = RegisteredFeatures(
        features=[
            _build_rural_property(),
            _build_buffer_area(),
            _build_rural_property(feature_id="Fazenda Blue"),
        ]
    )

    prompt = registered.build_prompt()

    assert "<rural_property>" in prompt
    assert "</rural_property>" in prompt
    assert "<buffer_area>" in prompt
    assert "</buffer_area>" in prompt

    rural_block = prompt.split("<rural_property>")[1].split("</rural_property>")[0]
    buffer_block = prompt.split("<buffer_area>")[1].split("</buffer_area>")[0]

    assert "GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0" in rural_block
    assert "Fazenda Blue" in rural_block
    assert "GO-5205703" not in buffer_block
    assert "a1b2c3d4e5f6" in buffer_block


def test_build_prompt_returns_empty_string_without_features():
    assert RegisteredFeatures(features=[]).build_prompt() == ""


def test_feature_utils_resolves_registered_features_by_id():
    feature = _build_rural_property(feature_id="Fazenda Blue")
    run_context = RunContext(
        run_id="test-run",
        session_id="test-session",
        session_state={"all_properties": [feature.model_dump()]},
    )

    resolved = resolve_feature(run_context, "Fazenda Blue")

    assert resolved is not None
    assert resolved.id == "Fazenda Blue"
    assert resolved.feature_type == "rural_property"
    assert find_feature_record(run_context, "Fazenda Blue") is not None
    assert resolve_feature(run_context, "missing") is None