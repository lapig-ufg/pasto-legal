"""
Benchmark de exportação via Xee (issue #112 - suporte a mapeamento on-the-fly).

Roda a matriz completa de testes para os dois imóveis (car_1 e car_2):
  - Satellite Embedding V1 (64 features) em Int16 e Float32
  - NDVI gapfilled Sentinel-2 (~101 datas) em Int16 e Float32

Gera tabela no console e persiste relatório JSON em tmp/xee_export/.

Uso (a partir da raiz do projeto):
    .venv/bin/python -m tests.xee_export.run_benchmark
"""
import json
import time

from datetime import datetime
from typing import Dict, List

from tests.xee_export.export import (
    _OUTPUT_DIR,
    _ROOT,
    export_ndvi_gapfilled,
    export_satellite_embedding,
    load_test_properties,
)


_YEAR = 2025


def _print_table(rows: List[Dict]) -> None:
    columns = ["imovel", "teste", "dtype", "n_features", "shape",
               "t_open_s", "t_export_s", "t_persist_s", "t_total_s", "zarr_mb"]
    widths = {c: max(len(c), *(len(str(row.get(c, ""))) for row in rows)) for c in columns}

    header = " | ".join(c.ljust(widths[c]) for c in columns)
    separator = "-" * len(header)
    print("\n" + header)
    print(separator)
    for row in rows:
        print(" | ".join(str(row.get(c, "")).ljust(widths[c]) for c in columns))
    print()


def run() -> List[Dict]:
    """Executa o benchmark completo (2 imóveis × 2 dados × 2 dtypes = 8 combinações)."""
    properties = load_test_properties()
    rows: List[Dict] = []

    for prop in properties:
        name = prop["name"]
        roi = prop["roi"]
        area = prop["area_ha"]
        print(f"\n>>> {name} ({prop['codigo']}) ~ {area} ha")

        for dtype_label, to_int16 in [("int16", True), ("float32", False)]:
            print(f"  embedding  [{dtype_label}]...")
            rows.append(export_satellite_embedding(
                name=name, roi=roi, year=_YEAR, to_int16=to_int16))

            print(f"  ndvi       [{dtype_label}]...")
            rows.append(export_ndvi_gapfilled(
                name=name, roi=roi, year=_YEAR, to_int16=to_int16))

    _print_table(rows)

    report_path = _OUTPUT_DIR / "benchmark_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(
        {"generated_at": datetime.now().isoformat(timespec="seconds"), "results": rows},
        indent=2, ensure_ascii=False))
    print(f"Relatório salvo em {report_path.relative_to(_ROOT)}")

    return rows


if __name__ == "__main__":
    start = time.perf_counter()
    run()
    print(f"\nBenchmark concluído em {time.perf_counter() - start:.1f}s")
