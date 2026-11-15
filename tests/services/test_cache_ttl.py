"""Unit tests for the cache TTL and version namespacing (no Earth Engine)."""

import datetime
import json
import os

import numpy as np
import pytest
import xarray as xr

from domain.services.geospatial import pasture_cache


@pytest.fixture
def local_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(pasture_cache, "_LOCAL_CACHE_ROOT", tmp_path)
    monkeypatch.setattr(pasture_cache, "_S3_ENVS", set())
    monkeypatch.setattr(pasture_cache, "_APP_VERSION", "testsha")
    # The background sweep would race with the fixtures; tests call it directly.
    monkeypatch.setattr(pasture_cache, "_start_cleanup_once", lambda: None)
    return tmp_path


def _now():
    return pasture_cache._now()


def _make_entry(root, key, kind, created_at=None, namespace="testsha"):
    zarr = root / "cache" / namespace / f"{kind}_cache" / f"F_{key}.zarr"
    zarr.mkdir(parents=True)
    if created_at is not None:
        zarr.with_suffix(".json").write_text(
            json.dumps({"created_at": created_at.isoformat()})
        )
    return zarr


def test_paths_are_namespaced_by_app_version(local_cache):
    zarr, png, marker = pasture_cache._cache_paths("F", "k", "satellite")

    assert os.sep + os.path.join("cache", "testsha") + os.sep in zarr
    assert zarr.endswith("satellite_cache" + os.sep + "F_k.zarr")
    assert png.endswith("F_k.png")
    assert marker.endswith("F_k.json")


def test_fresh_entry_is_a_cache_hit(local_cache):
    _make_entry(local_cache, 1, "satellite", _now() - datetime.timedelta(days=1))

    assert pasture_cache.dataset_exists("F", 1, kind="satellite")


def test_expired_entry_is_treated_as_missing(local_cache):
    _make_entry(local_cache, 2, "satellite", _now() - datetime.timedelta(days=8))

    assert not pasture_cache.dataset_exists("F", 2, kind="satellite")


def test_static_kinds_ignore_the_ttl(local_cache):
    _make_entry(local_cache, 3, "soil", _now() - datetime.timedelta(days=365))

    assert pasture_cache.dataset_exists("F", 3, kind="soil")


def test_missing_marker_falls_back_to_the_directory_mtime(local_cache):
    zarr = _make_entry(local_cache, 4, "satellite")
    old = (_now() - datetime.timedelta(days=8)).timestamp()
    os.utime(zarr, (old, old))

    assert not pasture_cache.dataset_exists("F", 4, kind="satellite")

    os.utime(zarr, None)
    assert pasture_cache.dataset_exists("F", 4, kind="satellite")


def test_save_dataset_writes_a_fresh_marker(local_cache):
    dataset = xr.Dataset(
        {"a": (("time", "y", "x"), np.ones((1, 2, 2), dtype="float32"))},
        coords={"time": [np.datetime64("2000-01-01")], "y": [0, 1], "x": [0, 1]},
    )

    pasture_cache.save_dataset("F", "k", dataset, kind="satellite")

    zarr = local_cache / "cache" / "testsha" / "satellite_cache" / "F_k.zarr"
    marker = zarr.with_suffix(".json")
    assert zarr.exists() and marker.exists()

    created = datetime.datetime.fromisoformat(
        json.loads(marker.read_text())["created_at"]
    )
    assert _now() - created < datetime.timedelta(minutes=1)
    assert pasture_cache.dataset_exists("F", "k", kind="satellite")


def test_purge_removes_other_versions_and_the_legacy_layout(local_cache):
    current = local_cache / "cache" / "testsha" / "satellite_cache"
    current.mkdir(parents=True)
    other_version = local_cache / "cache" / "oldsha" / "satellite_cache"
    other_version.mkdir(parents=True)
    legacy = local_cache / "satellite_cache"
    legacy.mkdir()

    untouched_file = local_cache / "agno.db"
    untouched_file.write_text("x")
    untouched_dir = local_cache / "chromadb_knowledge"
    untouched_dir.mkdir()

    pasture_cache._purge_stale_caches()

    assert current.exists()
    assert not other_version.exists()
    assert not legacy.exists()
    assert untouched_file.exists()
    assert untouched_dir.exists()


def test_app_version_prefers_the_explicit_override(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "abc1234")

    assert pasture_cache._resolve_app_version() == "abc1234"


def test_app_version_reads_the_ci_version_file(monkeypatch, tmp_path):
    monkeypatch.delenv("APP_VERSION", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "version.json").write_text(json.dumps({"commitId": "deadbee"}))

    assert pasture_cache._resolve_app_version() == "deadbee"


def test_app_version_falls_back_to_dev(monkeypatch, tmp_path):
    monkeypatch.delenv("APP_VERSION", raising=False)
    monkeypatch.chdir(tmp_path)

    assert pasture_cache._resolve_app_version() == "dev"


def test_unsafe_app_version_is_ignored(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "../../etc")

    assert pasture_cache._resolve_app_version() == "dev"
