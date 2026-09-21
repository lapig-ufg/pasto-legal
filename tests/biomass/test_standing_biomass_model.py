"""
Testes do modelo de biomassa em pé (sem GEE — dados de campo sintéticos).

Cobre o requisito 11 (validação geográfica e temporal do modelo) e a regra de que
a métrica fica indisponível enquanto não houver modelo calibrado com massa seca
MEDIDA em campo.

Precisa de scikit-learn e joblib (grupo `dev`):

    PYTHONPATH=. .venv/bin/python -m pytest tests/biomass/test_standing_biomass_model.py -v
"""
import datetime
import json

import pytest

from app.schemas.biomass_schemas import BiomassEstimate
from app.services.geospatial.biomass.standing_biomass import (
    CalibratedModelUnavailableError,
    enforce_monotonic_quantiles,
    StandingBiomassModelManifest,
    available_models,
    feature_names,
    load_manifest,
    train_standing_biomass_model,
)


pytest.importorskip("sklearn", reason="treino de biomassa em pé exige o grupo dev")


_FEATURES = ["NDVI", "LSWI", "rain_30d", "VH_mean", "biome"]


def _synthetic_field_plots(n_farms: int = 6, per_farm: int = 24, seed: int = 7) -> list:
    """
    Parcelas de campo sintéticas com massa seca MEDIDA e sinal recuperável.

    A massa seca é gerada a partir das covariáveis com um efeito de fazenda e um
    efeito de safra, que são justamente o que as validações espacial e temporal
    precisam expor.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    rows = []

    for farm in range(n_farms):
        farm_effect = rng.normal(0.0, 0.35)
        biome = float(farm % 2)

        for index in range(per_farm):
            year = 2023 + index % 3
            season_effect = 0.4 * ((year - 2023) - 1)

            ndvi = float(rng.uniform(0.25, 0.85))
            lswi = float(rng.uniform(-0.1, 0.4))
            rain = float(rng.uniform(0, 320))
            vh = float(rng.uniform(-22, -12))

            target = (
                0.6
                + 4.2 * ndvi
                + 1.4 * lswi
                + 0.004 * rain
                + 0.05 * (vh + 22)
                + 0.3 * biome
                + farm_effect
                + season_effect
                + float(rng.normal(0.0, 0.25))
            )

            rows.append({
                "NDVI": ndvi,
                "LSWI": lswi,
                "rain_30d": rain,
                "VH_mean": vh,
                "biome": biome,
                "target_standing_dm_t_ha": max(target, 0.1),
                "farm_id": f"fazenda-{farm:02d}",
                "sample_date": f"{year}-0{(index % 9) + 1}-15",
            })

    return rows


# -----------------------------------------------------------------------------
# Requisito 11: validação geográfica e temporal
# -----------------------------------------------------------------------------

def test_training_reports_spatial_and_temporal_validation(tmp_path):
    manifest = train_standing_biomass_model(
        samples=_synthetic_field_plots(),
        model_version="standing-biomass-test",
        registry_dir=tmp_path,
    )

    # Validação espacial: fazendas inteiras ficam fora de cada fold.
    assert manifest.spatial_cv["n"] == manifest.n_samples
    assert "GroupKFold por farm_id" in manifest.spatial_cv["scheme"]
    assert manifest.spatial_cv["rmse"] > 0
    assert manifest.spatial_cv["mae"] > 0
    assert "bias" in manifest.spatial_cv
    assert manifest.spatial_cv["r2"] > 0.3, "o modelo não recuperou o sinal sintético"

    # Validação temporal: treina no passado, testa na safra seguinte.
    assert manifest.temporal_cv["n"] > 0
    assert "safra" in manifest.temporal_cv["scheme"]
    assert manifest.temporal_cv["rmse"] > 0

    assert manifest.n_farms == 6
    assert manifest.trained_on == datetime.date.today().isoformat()


def test_training_refuses_too_few_farms_for_spatial_validation(tmp_path):
    """Com 2 fazendas o modelo mediria a si mesmo, não a capacidade de generalizar."""
    samples = [
        row for row in _synthetic_field_plots()
        if row["farm_id"] in ("fazenda-00", "fazenda-01")
    ]

    with pytest.raises(ValueError, match="pelo menos 3 fazendas"):
        train_standing_biomass_model(
            samples=samples, model_version="standing-biomass-test", registry_dir=tmp_path
        )


def test_training_refuses_empty_samples(tmp_path):
    with pytest.raises(ValueError, match="Nenhuma amostra"):
        train_standing_biomass_model(
            samples=[], model_version="standing-biomass-test", registry_dir=tmp_path
        )


def test_spatial_validation_is_stricter_than_random_validation(tmp_path):
    """
    A validação espacial precisa ser mais pessimista que uma aleatória.

    Com efeito de fazenda nos dados, um split aleatório vaza o efeito entre treino
    e teste e infla o R². É por isso que o agrupamento por fazenda é obrigatório.
    """
    import numpy as np
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.model_selection import KFold

    samples = _synthetic_field_plots()
    manifest = train_standing_biomass_model(
        samples=samples, model_version="standing-biomass-test", registry_dir=tmp_path
    )

    matrix = np.array([[row[name] for name in manifest.features] for row in samples])
    target = np.array([row["target_standing_dm_t_ha"] for row in samples])

    observed, predicted = [], []
    for train_index, test_index in KFold(n_splits=5, shuffle=True, random_state=42).split(matrix):
        model = GradientBoostingRegressor(
            loss="quantile", alpha=0.50, n_estimators=400,
            max_depth=4, learning_rate=0.05, subsample=0.8, random_state=42,
        )
        model.fit(matrix[train_index], target[train_index])
        observed.extend(target[test_index].tolist())
        predicted.extend(model.predict(matrix[test_index]).tolist())

    residual = np.array(predicted) - np.array(observed)
    random_rmse = float(np.sqrt(np.mean(residual ** 2)))

    assert manifest.spatial_cv["rmse"] >= random_rmse, (
        "a validação espacial deveria ser mais pessimista que a aleatória; "
        "se não for, o agrupamento por fazenda não está funcionando"
    )


# -----------------------------------------------------------------------------
# Registro e quantis
# -----------------------------------------------------------------------------

def test_training_registers_quantile_models_and_manifest(tmp_path):
    manifest = train_standing_biomass_model(
        samples=_synthetic_field_plots(),
        model_version="standing-biomass-test",
        registry_dir=tmp_path,
    )

    assert set(manifest.quantiles) == {"p10", "p50", "p90"}
    for filename in manifest.quantiles.values():
        assert (tmp_path / filename).exists()

    assert (tmp_path / "standing-biomass-test.json").exists()
    assert available_models(tmp_path) == ["standing-biomass-test"]

    reloaded = load_manifest(registry_dir=tmp_path)
    assert reloaded.model_version == manifest.model_version
    assert reloaded.features == manifest.features
    assert reloaded.target_unit == "t_DM_ha"


def test_quantile_models_mostly_bracket_the_median(tmp_path):
    """Os quantis treinados separadamente se cruzam numa minoria das amostras."""
    import joblib
    import numpy as np

    samples = _synthetic_field_plots()
    manifest = train_standing_biomass_model(
        samples=samples, model_version="standing-biomass-test", registry_dir=tmp_path
    )

    matrix = np.array([[row[name] for name in manifest.features] for row in samples])
    predictions = {
        label: joblib.load(tmp_path / filename).predict(matrix)
        for label, filename in manifest.quantiles.items()
    }

    ordered = (predictions["p10"] <= predictions["p50"]) & (predictions["p50"] <= predictions["p90"])
    assert ordered.mean() > 0.80, "os quantis estão cruzando com frequência alta demais"


def test_inference_always_returns_ordered_quantiles():
    """
    O cruzamento dos quantis é corrigido antes de virar intervalo de incerteza.

    Sem isso o `BiomassEstimate` seria rejeitado na validação (lower > upper).
    """
    assert enforce_monotonic_quantiles(2.1, 2.8, 3.6) == (2.1, 2.8, 3.6)

    # P90 abaixo do P50: os três são reordenados.
    assert enforce_monotonic_quantiles(2.1, 3.6, 2.8) == (2.1, 2.8, 3.6)

    # P10 acima do P50.
    assert enforce_monotonic_quantiles(3.0, 2.2, 3.6) == (2.2, 3.0, 3.6)

    # Quantil ausente: nada é reordenado.
    assert enforce_monotonic_quantiles(None, 2.8, 3.6) == (None, 2.8, 3.6)


def test_ordered_quantiles_satisfy_the_schema_validator():
    """A correção existe justamente para o schema aceitar o resultado."""
    lower, median, upper = enforce_monotonic_quantiles(2.1, 3.6, 2.8)

    estimate = BiomassEstimate(
        metric_type="standing_dry_matter_biomass",
        source="Modelo supervisionado calibrado em campo",
        period_start=datetime.date(2026, 8, 22),
        period_end=datetime.date(2026, 9, 21),
        temporal_support="instantaneous",
        value_per_ha=median,
        unit_per_ha="t_DM_ha",
        total_unit="t_DM",
        raster_resolution_m=10.0,
        pasture_mask_source="Global Pasture Watch",
        lower_bound_per_ha=lower,
        upper_bound_per_ha=upper,
        uncertainty_method="quantis P10/P90 do modelo quantílico",
        model_version="standing-biomass-test",
    )

    assert estimate.lower_bound_per_ha <= estimate.value_per_ha <= estimate.upper_bound_per_ha


def test_manifest_records_that_the_target_is_measured_in_the_field(tmp_path):
    """A regra central: o alvo é massa seca MEDIDA, nunca GPP."""
    manifest = train_standing_biomass_model(
        samples=_synthetic_field_plots(),
        model_version="standing-biomass-test",
        registry_dir=tmp_path,
    )

    notes = " ".join(manifest.notes)
    assert "MEDIDA em campo" in notes
    assert "GPP" in notes
    assert manifest.target_unit == "t_DM_ha"


# -----------------------------------------------------------------------------
# Sem modelo calibrado não há métrica
# -----------------------------------------------------------------------------

def test_without_a_registered_model_the_metric_is_unavailable(tmp_path):
    """
    A métrica não é inventada a partir de GPP: ela simplesmente não existe ainda.
    """
    with pytest.raises(CalibratedModelUnavailableError, match="MEDIDA em campo"):
        load_manifest(registry_dir=tmp_path / "vazio")


def test_requesting_an_unregistered_version_is_refused(tmp_path):
    train_standing_biomass_model(
        samples=_synthetic_field_plots(),
        model_version="standing-biomass-test",
        registry_dir=tmp_path,
    )

    with pytest.raises(CalibratedModelUnavailableError, match="não registrado"):
        load_manifest(model_version="standing-biomass-v99", registry_dir=tmp_path)


def test_manifest_round_trips_through_disk(tmp_path):
    manifest = StandingBiomassModelManifest(
        model_version="standing-biomass-v1",
        backend="lightgbm",
        features=_FEATURES,
        quantiles={"p10": "a.joblib", "p50": "b.joblib", "p90": "c.joblib"},
        n_samples=144,
        n_farms=6,
        spatial_cv={"rmse": 0.62, "r2": 0.71},
    )
    path = tmp_path / "standing-biomass-v1.json"
    manifest.to_path(path)

    reloaded = StandingBiomassModelManifest.from_path(path)

    assert reloaded.model_version == manifest.model_version
    assert reloaded.features == _FEATURES
    assert reloaded.spatial_cv["rmse"] == 0.62
    assert json.loads(path.read_text())["n_farms"] == 6


def test_feature_names_cover_every_required_covariate_family():
    """As famílias de covariáveis exigidas pela especificação estão todas presentes."""
    names = feature_names()

    for band in ("B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B11", "B12"):
        assert band in names, f"banda Sentinel-2 {band} ausente"

    for index in ("NDVI", "EVI2", "NDRE", "LSWI"):
        assert index in names, f"índice {index} ausente"

    for radar in ("VV_mean", "VH_mean", "VV_VH_mean"):
        assert radar in names, f"covariável Sentinel-1 {radar} ausente"

    for window in (15, 30, 60, 90):
        assert f"rain_{window}d" in names, f"chuva acumulada em {window} dias ausente"

    for climate in ("temp_mean_c", "radiation_mj_m2", "water_deficit_mm"):
        assert climate in names, f"covariável climática {climate} ausente"

    for context in ("elevation", "slope", "clay_0_30", "sand_0_30", "biome"):
        assert context in names, f"covariável de relevo/solo/bioma {context} ausente"

    assert "pasture_mask" in names
    assert "day_of_year" in names, "sazonalidade ausente"

    assert "annual_productivity_t_ha" in feature_names(include_annual_productivity=True)
