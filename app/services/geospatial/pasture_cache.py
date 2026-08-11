import io
from pathlib import Path
from typing import Tuple, Union

import PIL.Image
import s3fs
import xarray as xr

from app.configs.config import config


_LOCAL_CACHE_ROOT = Path("tmp")

_S3_ENVS = {"production", "stagging"}


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


def _cache_paths(car_code: str, key: Union[str, int], kind: str = "pasture") -> Tuple[str, str]:
    """Caminhos do zarr (dado) e do png (imagem) em cache para o imóvel/chave, dentro do namespace `kind`."""
    safe_code = car_code.replace(",", "_").replace(" ", "")
    stem = f"{safe_code}_{key}"

    if config.APP_ENV in _S3_ENVS:
        base = f"{config.S3_BUCKET}/{config.APP_ENV}/{kind}_cache"
        return f"s3://{base}/{stem}.zarr", f"{base}/{stem}.png"

    local_dir = _LOCAL_CACHE_ROOT / f"{kind}_cache"
    return str(local_dir / f"{stem}.zarr"), str(local_dir / f"{stem}.png")


def cache_exists(car_code: str, key: Union[str, int], kind: str = "pasture") -> bool:
    """Se já existe zarr + png em cache para o imóvel/chave."""
    zarr_path, png_path = _cache_paths(car_code, key, kind)

    if config.APP_ENV in _S3_ENVS:
        fs = _s3_filesystem()
        return fs.exists(zarr_path.removeprefix("s3://")) and fs.exists(png_path)

    return Path(zarr_path).exists() and Path(png_path).exists()


def load_cache(car_code: str, key: Union[str, int], kind: str = "pasture") -> Tuple[xr.Dataset, "PIL.Image.Image"]:
    """Lê o dataset (zarr) e a imagem (png) do cache."""
    zarr_path, png_path = _cache_paths(car_code, key, kind)

    if config.APP_ENV in _S3_ENVS:
        dataset = xr.open_zarr(zarr_path, storage_options=_s3_storage_options())
        with _s3_filesystem().open(png_path, "rb") as file:
            image = PIL.Image.open(io.BytesIO(file.read()))
        return dataset, image

    return xr.open_zarr(zarr_path), PIL.Image.open(png_path)


def save_cache(car_code: str, key: Union[str, int], dataset: xr.Dataset, image: "PIL.Image.Image", kind: str = "pasture") -> None:
    """Persiste o dataset (zarr) e a imagem (png) no cache."""
    zarr_path, png_path = _cache_paths(car_code, key, kind)

    if config.APP_ENV in _S3_ENVS:
        dataset.to_zarr(zarr_path, mode="w", storage_options=_s3_storage_options())
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        with _s3_filesystem().open(png_path, "wb") as file:
            file.write(buffer.getvalue())
        return

    Path(zarr_path).parent.mkdir(parents=True, exist_ok=True)
    dataset.to_zarr(zarr_path, mode="w")
    image.save(png_path)
