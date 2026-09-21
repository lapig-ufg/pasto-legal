"""Persistência da série histórica de produtividade em zarr (S3 ou local).

Mesma política do cache de classificação de pastagem
(`app.services.geospatial.pasture_cache`): em `production`/`stagging` o zarr vai
para o bucket S3; em `development` fica em `tmp/`. A diferença é que aqui o
artefato é a série anual pixel a pixel da propriedade, sem imagem PNG associada.
"""

from pathlib import Path

import s3fs
import xarray as xr

from app.configs.config import config


_LOCAL_CACHE_DIR = Path("tmp/historical_biomass")

_S3_ENVS = {"production", "stagging"}

_S3_PREFIX = "historical_biomass"


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


def uses_s3() -> bool:
    """Se o ambiente atual persiste no S3 em vez do disco local."""
    return config.APP_ENV in _S3_ENVS


def historical_cache_path(key: str) -> str:
    """
    Caminho do zarr da série histórica para a chave informada.

    Args:
        key (str): Chave de armazenamento (ver `historical_cache_key`).

    Returns:
        str: Caminho `s3://...` em produção/stagging, caminho local caso contrário.
    """
    if uses_s3():
        return f"s3://{config.S3_BUCKET}/{config.APP_ENV}/{_S3_PREFIX}/{key}.zarr"

    return str(_LOCAL_CACHE_DIR / f"{key}.zarr")


def historical_cache_exists(key: str) -> bool:
    """Se já existe uma exportação para a chave informada."""
    path = historical_cache_path(key)

    if uses_s3():
        return _s3_filesystem().exists(path.removeprefix("s3://"))

    return Path(path).exists()


def load_historical_cache(key: str) -> xr.Dataset:
    """Lê a série histórica exportada."""
    path = historical_cache_path(key)

    if uses_s3():
        return xr.open_zarr(path, storage_options=_s3_storage_options())

    return xr.open_zarr(path)


def save_historical_cache(key: str, dataset: xr.Dataset) -> str:
    """
    Persiste a série histórica pixel a pixel.

    Args:
        key (str): Chave de armazenamento.
        dataset (xr.Dataset): Série a persistir.

    Returns:
        str: Caminho onde o zarr foi gravado.
    """
    path = historical_cache_path(key)

    if uses_s3():
        dataset.to_zarr(path, mode="w", storage_options=_s3_storage_options())
        return path

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    dataset.to_zarr(path, mode="w")
    return path
