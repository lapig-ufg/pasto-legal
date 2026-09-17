"""Regression test: feature_id stays stable (CAR code) and the name lives in metadata.

The original bug: ``complete_registration`` overwrote ``feature_id`` with the
user-chosen name, so lookups by CAR code (what the model naturally uses) failed
and triggered re-registration. The contract under test:

- ``feature_id`` never changes after registration (CAR for rural properties,
  generated id for buffers).
- the user-chosen name is stored as ``metadata["name"]``.
- ``resolve_feature``/``RegisteredFeatures.find_by_any`` resolve by id, name,
  or any constituent CAR code.

Hermetic: mocks Earth Engine and points the prompts loader at ``domain/prompts``
because the domain package eagerly imports the GEE-bound agent.

    PYTHONPATH=. .venv/bin/python -m pytest tests/schemas/test_identity.py -v
"""
import os

from semente.configs.prompts import set_prompts_dir

set_prompts_dir(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../domain/prompts")
)

import ee  # noqa: E402

ee.ServiceAccountCredentials = lambda *a, **k: object()
ee.Initialize = lambda *a, **k: None

from semente.backends.toolkit import StateContext  # noqa: E402
from domain.schemas.feature import Feature, FeatureMetadata, RegisteredFeatures  # noqa: E402
from domain.utils.feature_utils import get_registered_features, resolve_feature  # noqa: E402
from domain.tools.property_tools import complete_registration, set_property_name  # noqa: E402

CAR = "PA-1507953-88FB87600C5144BA9FCB6FE07D23B39A"


def _rural_candidate() -> Feature:
    return Feature(
        feature_id=CAR,
        coords=[[[[-48.5, -2.7], [-48.4, -2.7], [-48.4, -2.6], [-48.5, -2.6], [-48.5, -2.7]]]],
        metadata=[FeatureMetadata(key="car_code", value=CAR)],
        total_area=2177.42,
        region="Tailândia",
        feature_type="rural_property",
    )


def _context_with_pending(feature: Feature) -> StateContext:
    return StateContext(
        {
            "terms_accepted": True,
            "registration_state": "pending",
            "candidate_properties": [feature.model_dump()],
        }
    )


def test_complete_registration_keeps_car_as_feature_id():
    ctx = _context_with_pending(_rural_candidate())
    complete_registration(run_context=ctx, name="Fazenda Chaparral")

    registered = get_registered_features(ctx.session_state).features[0]
    assert registered.feature_id == CAR                 # id is stable
    assert registered.name == "Fazenda Chaparral"       # name is metadata


def test_resolve_feature_by_car_and_by_name():
    ctx = _context_with_pending(_rural_candidate())
    complete_registration(run_context=ctx, name="Fazenda Chaparral")

    by_car = resolve_feature(ctx, CAR)
    by_name = resolve_feature(ctx, "Fazenda Chaparral")

    assert by_car is not None and by_car.feature_id == CAR
    assert by_name is not None and by_name.feature_id == CAR


def test_set_property_name_renames_without_changing_id():
    ctx = _context_with_pending(_rural_candidate())
    complete_registration(run_context=ctx, name="Fazenda Chaparral")

    set_property_name(run_context=ctx, feature_id="Fazenda Chaparral", name="Chaparral Nova")

    registered = get_registered_features(ctx.session_state).features[0]
    assert registered.feature_id == CAR
    assert registered.name == "Chaparral Nova"


def test_find_by_any_matches_constituent_car_codes():
    car2 = "GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0"
    feature = _rural_candidate()
    feature.metadata = [
        FeatureMetadata(key="car_code", value=f"{CAR}, {car2}"),
        FeatureMetadata(key="name", value="Fazenda Unificada"),
    ]
    registered = RegisteredFeatures(features=[feature])

    assert registered.find_by_any(car2) is feature              # constituent CAR
    assert registered.find_by_any("Fazenda Unificada") is feature  # name
    assert registered.find_by_any("missing") is None
