"""
Benchmark de exportação via Xee — NDVI Gapfilled (issue #112).

Exporta a série temporal Sentinel-2 NDVI gapfilled (1 variável × ~100 datas) via Xee
para os novos CARs (Silvânia-GO ~2073 ha e Córrego do Ouro-GO ~23 ha), em Int16 e Float32,
e reporta o tempo e tamanho em disco.

Por que um arquivo separado do run.py?
  O NDVI não é usado como feature de classificação — é um produto de análise temporal
  (vigor/fenologia da pastagem). O run.py foca nos 3 métodos de classificação. Este
  runner responde à pergunta original da issue: "quanto tempo leva exportar o NDVI via Xee?"

Resultados esperados (Jaraguá-GO, referência da Rodada 1):
  car_1 (3 ha):  int16 ~8 s / 0,27 MB  |  float32 ~12 s / 0,51 MB
  car_2 (55 ha): int16 ~13 s / 2,91 MB |  float32 ~11 s / 5,79 MB

Uso:
    .venv/bin/python -m tests.xee_export.run_ndvi
    .venv/bin/python -m tests.xee_export.run_ndvi --int16-only   # pula float32 (~metade do tempo)
"""
import argparse
import json
import time

from datetime import datetime
from typing import Dict, List

from tests.xee_export.export import _OUTPUT_DIR, _ROOT, load_test_properties, export_ndvi_gapfilled

_MOCK_PATH = _ROOT / "app/utils/mocks/new_property_mock.json"
_W = 16


# ---------------------------------------------------------------------------
# Formatação
# ---------------------------------------------------------------------------

def _cell(v, w: int = _W) -> str:
    return str(v).ljust(w)


def _hdr(*cols) -> str:
    return " | ".join(_cell(c) for c in cols)


def _row(d: Dict, *keys) -> str:
    return " | ".join(_cell(d.get(k, "-")) for k in keys)


def _sep(n: int) -> str:
    return "-" * (n * (_W + 3) - 3)


def _title(text: str, n: int) -> str:
    w = n * (_W + 3) - 3
    return f"\n{'━' * w}\n{text.center(w)}\n{'━' * w}"


def _print_tables(rows: List[Dict]) -> None:
    int16_rows  = [r for r in rows if r.get("dtype") == "int16"]
    float32_rows = [r for r in rows if r.get("dtype") == "float32"]

    cols = ["imovel", "dtype", "n_datas", "shape (t×y×x)",
            "t_open_s", "t_export_s", "t_persist_s", "t_total_s", "zarr_mb"]

    print(_title("NDVI Gapfilled via Xee — Int16 (transferência mais leve)", len(cols)))
    print(_hdr(*cols))
    print(_sep(len(cols)))
    for r in int16_rows:
        s = r.get("shape", {})
        d = {**r, "shape (t×y×x)": f"{s.get('time','?')}×{s.get('y','?')}×{s.get('x','?')}",
             "n_datas": s.get("time", "?")}
        print(_row(d, *cols))

    if float32_rows:
        print(_title("NDVI Gapfilled via Xee — Float32 (referência de comparação)", len(cols)))
        print(_hdr(*cols))
        print(_sep(len(cols)))
        for r in float32_rows:
            s = r.get("shape", {})
            d = {**r, "shape (t×y×x)": f"{s.get('time','?')}×{s.get('y','?')}×{s.get('x','?')}",
                 "n_datas": s.get("time", "?")}
            print(_row(d, *cols))

    # Tabela comparativa Int16 vs Float32 por imóvel
    if int16_rows and float32_rows:
        imoveis_int   = {r["imovel"]: r for r in int16_rows}
        imoveis_float = {r["imovel"]: r for r in float32_rows}
        cols_c = ["imovel", "int16_total_s", "float32_total_s",
                  "int16_zarr_mb", "float32_zarr_mb", "n_datas"]
        print(_title("Comparação Int16 vs Float32 — tempo e tamanho", len(cols_c)))
        print(_hdr(*cols_c))
        print(_sep(len(cols_c)))
        for im in [r["imovel"] for r in int16_rows]:
            ri = imoveis_int.get(im, {})
            rf = imoveis_float.get(im, {})
            s  = ri.get("shape", {})
            row = {
                "imovel":           im,
                "int16_total_s":    ri.get("t_total_s", "-"),
                "float32_total_s":  rf.get("t_total_s", "-"),
                "int16_zarr_mb":    ri.get("zarr_mb", "-"),
                "float32_zarr_mb":  rf.get("zarr_mb", "-"),
                "n_datas":          s.get("time", "?"),
            }
            print(_row(row, *cols_c))

    print()
    print("  Gargalo do NDVI: número de datas (t_export cresce com a série).")
    print("  Int16 ocupa metade do disco. Para o cache do LAPIG, sempre use Int16.")
    print()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(int16_only: bool = False) -> None:
    global_start = time.perf_counter()
    properties   = load_test_properties(mock_path=_MOCK_PATH)
    rows: List[Dict] = []

    dtypes = [("Int16", True)] if int16_only else [("Int16", True), ("Float32", False)]

    for prop in properties:
        name = f"new_{prop['name']}"
        roi  = prop["roi"]

        print(f"\n{'═' * 70}")
        print(f"  {name}  |  {prop['codigo']}  |  ~{prop['area_ha']:.1f} ha")
        print(f"{'═' * 70}")

        for label, to_int16 in dtypes:
            print(f"\n  → NDVI Gapfilled {label} ...")
            rows.append(export_ndvi_gapfilled(name=name, roi=roi, year=2025, to_int16=to_int16))

    print(f"\n\n{'█' * 70}")
    print("  RESULTADO FINAL — NDVI Gapfilled via Xee (issue #112)")
    print(f"{'█' * 70}")
    _print_tables(rows)

    report_path = _OUTPUT_DIR / "run_ndvi_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(
        {"generated_at": datetime.now().isoformat(timespec="seconds"),
         "int16_only": int16_only, "results": rows},
        indent=2, ensure_ascii=False))
    print(f"Relatório salvo em {report_path.relative_to(_ROOT)}")
    print(f"Total: {time.perf_counter() - global_start:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Issue #112 — benchmark NDVI Gapfilled via Xee")
    parser.add_argument("--int16-only", action="store_true",
                        help="Pula o teste Float32 (~metade do tempo total)")
    args = parser.parse_args()
    run(int16_only=args.int16_only)
