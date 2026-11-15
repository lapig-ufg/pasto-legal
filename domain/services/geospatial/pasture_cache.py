"""Zarr/PNG cache for the geospatial layers.

Two rules guard a cache hit:

* **Version namespace** — entries live under ``cache/<app-version>/``, so a
  deployment never reads rasters written by a different version of the project.
  Caches from other versions (and from the older, non-namespaced layout) are
  removed in a background thread on first use.
* **TTL** — layers whose data changes over time are only reused for
  ``CACHE_TTL``; each entry carries a small ``.json`` sidecar with its creation
  timestamp.

Both must pass, and an expired entry is treated exactly like a missing one: the
caller regenerates it and overwrites the same path.
"""

import datetime
import io
import json
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Optional, Tuple, Union

import PIL.Image
import s3fs
import xarray as xr

from semente.configs.config import config
from semente.logging import log_warning


_LOCAL_CACHE_ROOT = Path("tmp")

_S3_ENVS = {"production", "stagging"}

# Layers whose data ages out. Static assets (soil, age, vigor) and the biomass
# history chart (keyed by the GPW year) are deliberately left out.
CACHE_TTL = datetime.timedelta(days=7)
CACHE_TTL_KINDS = frozenset(
    {"pasture", "pasture_mask", "biomass_t2g", "biomass_gpw", "satellite"}
)

_NAMESPACE_FALLBACK = "dev"
_NAMESPACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

_cleanup_lock = threading.Lock()
_cleanup_started = False


def _read_version_file() -> Optional[str]:
    """Reads the commit id that CI writes to ``version.json``."""
    try:
        payload = json.loads(Path("version.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    commit = payload.get("commitId") if isinstance(payload, dict) else None
    return commit if isinstance(commit, str) else None


def _resolve_app_version() -> str:
    """Version whose caches this process may read.

    ``APP_VERSION`` (explicit override, also useful to pin a hotfix) wins over
    the ``version.json`` produced by CI, which wins over ``dev`` for checkouts.
    """
    candidate = (os.getenv("APP_VERSION") or _read_version_file() or _NAMESPACE_FALLBACK)
    candidate = candidate.strip()
    if not _NAMESPACE_PATTERN.match(candidate):
        log_warning(
            f"cache: ignoring unsafe app version {candidate!r}; using {_NAMESPACE_FALLBACK!r}"
        )
        return _NAMESPACE_FALLBACK
    return candidate


_APP_VERSION = _resolve_app_version()


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _cache_root() -> str:
    """Base path (local directory or S3 prefix) holding every version's caches."""
    if config.APP_ENV in _S3_ENVS:
        return f"{config.S3_BUCKET}/{config.APP_ENV}/cache"
    return str(_LOCAL_CACHE_ROOT / "cache")


def _cache_paths(
    car_code: str, key: Union[str, int], kind: str = "pasture"
) -> Tuple[str, str, str]:
    """Zarr, PNG and freshness-marker paths for one property/layer in this version."""
    safe_code = car_code.replace(",", "_").replace(" ", "")
    stem = f"{safe_code}_{key}"

    if config.APP_ENV in _S3_ENVS:
        base = f"{_cache_root()}/{_APP_VERSION}/{kind}_cache"
        return (
            f"s3://{base}/{stem}.zarr",
            f"{base}/{stem}.png",
            f"{base}/{stem}.json",
        )

    base = Path(_cache_root()) / _APP_VERSION / f"{kind}_cache"
    return (
        str(base / f"{stem}.zarr"),
        str(base / f"{stem}.png"),
        str(base / f"{stem}.json"),
    )


def _s3_storage_options() -> dict:
    """Credenciais/endpoint do S3 no formato aceito por fsspec/s3fs."""
    return {
        "key": config.S3_ACCESS_KEY,
        "secret": config.S3_SECRET_KEY,
        "endpoint_url": config.S3_ENDPOINT_URL,
        "client_kwargs": {"region_name": config.S3_REGION} if config.S3_REGION else {},
    }


def _s3_filesystem() -> s3fs.S3FileSystem:
    return s3fs.S3FileSystem(**_s3_storage_options())


def _write_marker(marker_path: str) -> None:
    """Records the creation time of a cache entry (best effort)."""
    payload = json.dumps({"created_at": _now().isoformat()}).encode("utf-8")
    try:
        if config.APP_ENV in _S3_ENVS:
            with _s3_filesystem().open(marker_path, "wb") as file:
                file.write(payload)
            return

        path = Path(marker_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    except Exception as error:
        log_warning(f"cache: could not write freshness marker {marker_path}: {error}")


def _marker_created_at(marker_path: str) -> Optional[datetime.datetime]:
    try:
        if config.APP_ENV in _S3_ENVS:
            with _s3_filesystem().open(marker_path, "rb") as file:
                payload = json.loads(file.read().decode("utf-8"))
        else:
            payload = json.loads(Path(marker_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    created = payload.get("created_at") if isinstance(payload, dict) else None
    if not isinstance(created, str):
        return None

    try:
        parsed = datetime.datetime.fromisoformat(created)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.timezone.utc)


def _zarr_modified_at(zarr_path: str) -> Optional[datetime.datetime]:
    """Best-effort write time for entries cached before the marker existed."""
    try:
        if config.APP_ENV in _S3_ENVS:
            entries = _s3_filesystem().ls(zarr_path.removeprefix("s3://"), detail=True)
            stamps = [
                entry.get("LastModified")
                for entry in entries
                if isinstance(entry, dict)
            ]
            stamps = [stamp for stamp in stamps if isinstance(stamp, datetime.datetime)]
            if not stamps:
                return None
            newest = max(stamps)
        else:
            newest = datetime.datetime.fromtimestamp(
                Path(zarr_path).stat().st_mtime, tz=datetime.timezone.utc
            )
    except Exception:
        return None

    return newest if newest.tzinfo else newest.replace(tzinfo=datetime.timezone.utc)


def _is_fresh(zarr_path: str, marker_path: str, kind: str) -> bool:
    """Whether an existing entry is still inside its TTL (always true for static kinds)."""
    if kind not in CACHE_TTL_KINDS:
        return True

    created = _marker_created_at(marker_path) or _zarr_modified_at(zarr_path)
    if created is None:
        # Age unknown: regenerate rather than serve something that may be stale.
        return False
    return (_now() - created) < CACHE_TTL


def _purge_stale_caches() -> None:
    """Removes caches written by other app versions and the legacy layout."""
    try:
        current = _APP_VERSION

        if config.APP_ENV in _S3_ENVS:
            filesystem = _s3_filesystem()
            root = _cache_root()
            if filesystem.exists(root):
                for entry in filesystem.ls(root, detail=True):
                    name = str(entry.get("name", "")).rstrip("/")
                    if name.rsplit("/", 1)[-1] != current:
                        filesystem.rm(name, recursive=True)

            # Legacy layout: <bucket>/<env>/<kind>_cache, outside the new root.
            legacy_root = f"{config.S3_BUCKET}/{config.APP_ENV}"
            if filesystem.exists(legacy_root):
                for entry in filesystem.ls(legacy_root, detail=True):
                    name = str(entry.get("name", "")).rstrip("/")
                    if name.rsplit("/", 1)[-1].endswith("_cache"):
                        filesystem.rm(name, recursive=True)
            return

        root = Path(_cache_root())
        if root.exists():
            for entry in root.iterdir():
                if entry.is_dir() and entry.name != current:
                    shutil.rmtree(entry, ignore_errors=True)

        # Legacy layout: tmp/<kind>_cache, outside the new root.
        if _LOCAL_CACHE_ROOT.exists():
            for entry in _LOCAL_CACHE_ROOT.iterdir():
                if entry.is_dir() and entry.name.endswith("_cache"):
                    shutil.rmtree(entry, ignore_errors=True)
    except Exception as error:
        log_warning(f"cache: stale cache cleanup failed: {error}")


def _start_cleanup_once() -> None:
    """Starts the one-shot stale-cache cleanup in the background."""
    global _cleanup_started
    if _cleanup_started:
        return

    with _cleanup_lock:
        if _cleanup_started:
            return
        _cleanup_started = True

    threading.Thread(
        target=_purge_stale_caches,
        name="cache-namespace-cleanup",
        daemon=True,
    ).start()


def dataset_exists(car_code: str, key: Union[str, int], kind: str = "pasture") -> bool:
    """Whether a fresh zarr dataset exists (PNG preview is not required)."""
    zarr_path, _png_path, marker_path = _cache_paths(car_code, key, kind)
    _start_cleanup_once()

    if config.APP_ENV in _S3_ENVS:
        exists = _s3_filesystem().exists(zarr_path.removeprefix("s3://"))
    else:
        exists = Path(zarr_path).exists()

    return exists and _is_fresh(zarr_path, marker_path, kind)


def cache_exists(car_code: str, key: Union[str, int], kind: str = "pasture") -> bool:
    """Whether fresh zarr + png exist in cache for the property/key."""
    zarr_path, png_path, marker_path = _cache_paths(car_code, key, kind)
    _start_cleanup_once()

    if config.APP_ENV in _S3_ENVS:
        filesystem = _s3_filesystem()
        exists = filesystem.exists(zarr_path.removeprefix("s3://")) and filesystem.exists(png_path)
    else:
        exists = Path(zarr_path).exists() and Path(png_path).exists()

    return exists and _is_fresh(zarr_path, marker_path, kind)


def load_dataset(car_code: str, key: Union[str, int], kind: str = "pasture") -> xr.Dataset:
    """Reads only the zarr dataset from the cache."""
    zarr_path, _png_path, _marker_path = _cache_paths(car_code, key, kind)

    if config.APP_ENV in _S3_ENVS:
        return xr.open_zarr(zarr_path, storage_options=_s3_storage_options())

    return xr.open_zarr(zarr_path)


def load_cache(car_code: str, key: Union[str, int], kind: str = "pasture") -> Tuple[xr.Dataset, "PIL.Image.Image"]:
    """Lê o dataset (zarr) e a imagem (png) do cache."""
    zarr_path, png_path, _marker_path = _cache_paths(car_code, key, kind)

    if config.APP_ENV in _S3_ENVS:
        dataset = xr.open_zarr(zarr_path, storage_options=_s3_storage_options())
        with _s3_filesystem().open(png_path, "rb") as file:
            image = PIL.Image.open(io.BytesIO(file.read()))
        return dataset, image

    return xr.open_zarr(zarr_path), PIL.Image.open(png_path)


def save_dataset(car_code: str, key: Union[str, int], dataset: xr.Dataset, kind: str = "pasture") -> None:
    """Persists only the zarr dataset (no PNG preview)."""
    zarr_path, _png_path, marker_path = _cache_paths(car_code, key, kind)
    _start_cleanup_once()

    if config.APP_ENV in _S3_ENVS:
        dataset.to_zarr(zarr_path, mode="w", storage_options=_s3_storage_options())
    else:
        Path(zarr_path).parent.mkdir(parents=True, exist_ok=True)
        dataset.to_zarr(zarr_path, mode="w")

    _write_marker(marker_path)


def save_cache(car_code: str, key: Union[str, int], dataset: xr.Dataset, image: "PIL.Image.Image", kind: str = "pasture") -> None:
    """Persiste o dataset (zarr) e a imagem (png) no cache."""
    zarr_path, png_path, marker_path = _cache_paths(car_code, key, kind)
    _start_cleanup_once()

    if config.APP_ENV in _S3_ENVS:
        dataset.to_zarr(zarr_path, mode="w", storage_options=_s3_storage_options())
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        with _s3_filesystem().open(png_path, "wb") as file:
            file.write(buffer.getvalue())
    else:
        Path(zarr_path).parent.mkdir(parents=True, exist_ok=True)
        dataset.to_zarr(zarr_path, mode="w")
        image.save(png_path)

    _write_marker(marker_path)
