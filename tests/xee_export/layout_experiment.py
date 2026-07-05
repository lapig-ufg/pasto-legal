"""
Experimento controlado: bandas (N variáveis) x série temporal (1 variável × N).

Exporta a MESMA base (embedding e NDVI) nos dois layouts para isolar o que domina o tempo
do Xee: o número de VARIÁVEIS (bandas) ou o número de datas. Roda no car_1.

Uso (a partir da raiz do projeto):
    .venv/bin/python -m tests.xee_export.layout_experiment
"""
import time

from typing import Dict, List

import ee

from tests.xee_export.export import (
    _EMBEDDING_ASSET,
    _INT16_FACTOR,
    _S2_ASSET,
    _build_ndvi_gapfilled,
    _export_via_xee,
    _native_crs,
    load_test_properties,
)


_YEAR = 2025


def _embedding_int16(roi: ee.Geometry) -> ee.Image:
    """Imagem anual do embedding (64 bandas) do ano, em Int16."""
    image = (ee.ImageCollection(_EMBEDDING_ASSET)
        .filterBounds(roi).filterDate(f"{_YEAR}-01-01", f"{_YEAR + 1}-01-01").first())
    return image.multiply(_INT16_FACTOR).toInt16()


def _bands_as_timeseries(image: ee.Image) -> ee.ImageCollection:
    """Transforma um Image de N bandas em N imagens de 1 banda num eixo temporal sintético."""
    indices = ee.List.sequence(0, image.bandNames().size().subtract(1))

    def to_image(i):
        i = ee.Number(i).toInt()
        return (image.select([i]).rename("valor")
            .set("system:time_start", ee.Date(f"{_YEAR}-01-01").advance(i, "day").millis()))

    return ee.ImageCollection(indices.map(to_image))


def _ndvi_int16(roi: ee.Geometry) -> ee.ImageCollection:
    """Série NDVI gapfilled já convertida para Int16 (1 banda por data)."""
    collection = _build_ndvi_gapfilled(roi=roi, year=_YEAR)
    return collection.map(lambda img: img.clamp(-1, 1).multiply(_INT16_FACTOR)
        .toInt16().copyProperties(img, ["system:time_start"]))


def run() -> List[Dict]:
    """Roda os 4 layouts no car_1 e imprime a comparação."""
    prop = load_test_properties()[0]
    roi = prop["roi"]
    print(f">>> {prop['name']} ({prop['area_ha']} ha) — experimento de layout\n")

    emb = _embedding_int16(roi)
    crs_emb = _native_crs(ee.ImageCollection([emb]))
    crs_s2 = _native_crs(ee.ImageCollection(_S2_ASSET)
        .filterBounds(roi).filterDate(f"{_YEAR}-01-01", f"{_YEAR + 1}-01-01").select("B8"))

    ndvi = _ndvi_int16(roi)

    jobs = [
        ("embedding_bandas", ee.ImageCollection([emb]), crs_emb),
        ("embedding_serie", _bands_as_timeseries(emb), crs_emb),
        ("ndvi_serie", ndvi, crs_s2),
        ("ndvi_bandas", ee.ImageCollection([ndvi.toBands()]), crs_s2),
    ]

    rows: List[Dict] = []
    for teste, collection, crs in jobs:
        result = _export_via_xee(name=prop["name"], teste=teste, collection=collection,
                                 roi=roi, stem=f"layout_{teste}", to_int16=True, crs=crs)
        result["n_datas"] = result["shape"].get("time", 1)
        rows.append(result)

    columns = ["teste", "n_features", "n_datas", "t_export_s", "t_total_s"]
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in columns}
    header = " | ".join(c.ljust(widths[c]) for c in columns)
    print("\n" + header)
    print("-" * len(header))
    for r in rows:
        print(" | ".join(str(r[c]).ljust(widths[c]) for c in columns))

    return rows


if __name__ == "__main__":
    start = time.perf_counter()
    run()
    print(f"\nExperimento concluído em {time.perf_counter() - start:.1f}s")
