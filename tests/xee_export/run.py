"""
Benchmark completo — issue #112 (novos CARs: Silvânia-GO ~2073 ha, Córrego do Ouro-GO ~23 ha).

Responde as três perguntas da issue:

    [0] export_embedding    → quanto tempo leva exportar os 64 features brutos via Xee?
    [1] classify_gee        → GEE classifica e retorna área + PNG (server-side puro)
    [2] classify_gee_xee    → GEE classifica, Xee baixa o raster resultado → zarr  (<20 s?)
    [3] classify_xee        → Xee baixa os 64 features, sklearn classifica local
    [4] biomass_map         → biomassa MapBiomas 2024

Para o benchmark de NDVI gapfilled (série temporal), use:
    .venv/bin/python -m tests.xee_export.run_ndvi

Uso:
    .venv/bin/python -m tests.xee_export.run                          # completo (~8 min)
    .venv/bin/python -m tests.xee_export.run --skip-xee               # sem classify_xee (~4 min)
    .venv/bin/python -m tests.xee_export.run --skip-embed             # sem export_embedding (~3 min)
    .venv/bin/python -m tests.xee_export.run --skip-xee --skip-embed  # só classificação (~75 s)
"""
import argparse
import json
import time

from datetime import datetime
from typing import Dict, List

from tests.xee_export.export import (
    _OUTPUT_DIR, _ROOT, load_test_properties, export_satellite_embedding,
)
from tests.xee_export.classification import (
    biomass_map, classify_gee, classify_gee_xee, classify_xee,
)

_MOCK_PATH = _ROOT / "app/utils/mocks/new_property_mock.json"
_W = 16  # largura de célula nas tabelas


# ---------------------------------------------------------------------------
# Formatação das tabelas
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


def _print_all(results: Dict[str, List[Dict]], props_by_name: Dict, skip_xee: bool,
               skip_embed: bool) -> None:
    embed = results.get("export_embedding", [])
    gee   = results.get("classify_gee", [])
    gxee  = results.get("classify_gee_xee", [])
    xee_r = results.get("classify_xee", [])
    bio   = results.get("biomass_map", [])
    imoveis = [r["imovel"] for r in gee] or [r["imovel"] for r in gxee]

    # --- Tabela 1: export_embedding ---
    if embed:
        cols = ["imovel", "t_open_s", "t_export_s", "t_persist_s", "t_total_s",
                "zarr_mb", "shape (t×y×x)"]
        print(_title("Tabela 1 — export_embedding: Satellite Embedding 64 features brutos via Xee (Int16)", len(cols)))
        print(_hdr(*cols))
        print(_sep(len(cols)))
        for r in embed:
            s = r.get("shape", {})
            d = {**r, "shape (t×y×x)": f"{s.get('time','?')}×{s.get('y','?')}×{s.get('x','?')}"}
            print(_row(d, *cols))

    # --- Tabela 2: classify_gee ---
    if gee:
        cols = ["imovel", "area_pasto_ha", "t_classify_s", "t_total_s"]
        print(_title("Tabela 2 — classify_gee: tudo no GEE server-side (resultado = área + PNG)", len(cols)))
        print(_hdr(*cols))
        print(_sep(len(cols)))
        for r in gee:
            print(_row(r, *cols))
        print()
        print("  Nota: t_classify_s = só GEE (RF + reduceRegion); t_total_s inclui download do PNG.")

    # --- Tabela 3: classify_gee_xee ---
    if gxee:
        cols = ["imovel", "area_pasto_ha", "t_xee_open_s", "t_xee_export_s",
                "t_xee_persist_s", "t_total_s", "zarr_mb"]
        print(_title("Tabela 3 — classify_gee_xee: GEE classifica → Xee baixa raster binário (1 var, < 20 s?)", len(cols)))
        print(_hdr(*cols))
        print(_sep(len(cols)))
        for r in gxee:
            print(_row(r, *cols))
        print()
        for r in gxee:
            ok = r["t_total_s"] < 20
            sinal = "✅ < 20 s" if ok else "⚠️ > 20 s"
            print(f"  {r['imovel']}: {r['t_total_s']} s — {sinal}")

    # --- Tabela 4: classify_xee ---
    if xee_r:
        cols = ["imovel", "area_pasto_ha", "t_export_s", "t_predict_s", "t_total_s"]
        print(_title("Tabela 4 — classify_xee: Xee baixa 64 features → sklearn classifica local", len(cols)))
        print(_hdr(*cols))
        print(_sep(len(cols)))
        for r in xee_r:
            print(_row(r, *cols))
        print()
        print("  Nota: t_export_s = download 64 bandas via Xee (gargalo principal).")

    # --- Tabela 5: biomass_map ---
    if bio:
        cols = ["imovel", "biomassa_total_ton_ms", "t_total_s"]
        print(_title("Tabela 5 — biomass_map: biomassa de pastagem MapBiomas 2024", len(cols)))
        print(_hdr(*cols))
        print(_sep(len(cols)))
        for r in bio:
            print(_row(r, *cols))

    # --- Tabela 6: comparação de tempo ---
    embed_idx = {r["imovel"]: r for r in embed}
    gee_idx   = {r["imovel"]: r for r in gee}
    gxee_idx  = {r["imovel"]: r for r in gxee}
    xee_idx   = {r["imovel"]: r for r in xee_r}

    cols_t = ["imovel", "area_total_ha"]
    if not skip_embed:
        cols_t.append("embed_export_s")
    cols_t += ["classif_gee_s", "classif_gee_xee_s"]
    if not skip_xee:
        cols_t.append("classif_xee_s")

    print(_title("Tabela 6 — COMPARAÇÃO DE TEMPO t_total_s por método (segundos)", len(cols_t)))
    print(_hdr(*cols_t))
    print(_sep(len(cols_t)))
    for im in imoveis:
        row: Dict = {
            "imovel": im,
            "area_total_ha": props_by_name.get(im, {}).get("area_ha", "-"),
        }
        if not skip_embed:
            row["embed_export_s"] = embed_idx.get(im, {}).get("t_total_s", "-")
        row["classif_gee_s"]     = gee_idx.get(im, {}).get("t_total_s", "-")
        row["classif_gee_xee_s"] = gxee_idx.get(im, {}).get("t_total_s", "-")
        if not skip_xee:
            row["classif_xee_s"] = xee_idx.get(im, {}).get("t_total_s", "-")
        print(_row(row, *cols_t))

    # --- Tabela 7: comparação de área ---
    if gee and gxee:
        cols_a = ["imovel", "area_total_ha", "classify_gee", "classify_gee_xee"]
        if xee_r:
            cols_a.append("classify_xee")

        print(_title("Tabela 7 — COMPARAÇÃO DE ÁREA DE PASTO (ha) por método", len(cols_a)))
        print(_hdr(*cols_a))
        print(_sep(len(cols_a)))
        for im in imoveis:
            row = {
                "imovel": im,
                "area_total_ha": props_by_name.get(im, {}).get("area_ha", "-"),
                "classify_gee":      gee_idx.get(im, {}).get("area_pasto_ha", "-"),
                "classify_gee_xee":  gxee_idx.get(im, {}).get("area_pasto_ha", "-"),
            }
            if xee_r:
                row["classify_xee"] = xee_idx.get(im, {}).get("area_pasto_ha", "-")
            print(_row(row, *cols_a))

    print()


# ---------------------------------------------------------------------------
# Runner principal
# ---------------------------------------------------------------------------

def run(skip_xee: bool = False, skip_embed: bool = False) -> None:
    global_start = time.perf_counter()
    properties   = load_test_properties(mock_path=_MOCK_PATH)
    props_by_name: Dict = {}

    results: Dict[str, List[Dict]] = {
        "export_embedding": [], "classify_gee": [],
        "classify_gee_xee": [], "classify_xee": [], "biomass_map": [],
    }

    for prop in properties:
        name = f"new_{prop['name']}"
        roi  = prop["roi"]
        props_by_name[name] = prop

        print(f"\n{'═' * 70}")
        print(f"  {name}  |  {prop['codigo']}  |  ~{prop['area_ha']:.1f} ha")
        print(f"{'═' * 70}")

        step = 0
        total_steps = 4 if (skip_xee or skip_embed) else 5
        if not skip_embed and not skip_xee:
            total_steps = 5
        elif skip_embed and skip_xee:
            total_steps = 3
        elif skip_embed or skip_xee:
            total_steps = 4

        if skip_embed:
            print(f"\n[–] export_embedding — ignorado (--skip-embed)")
        else:
            print(f"\n[{step}/{total_steps - 1}] export_embedding — exporta 64 features brutos via Xee → zarr ...")
            results["export_embedding"].append(
                export_satellite_embedding(name=name, roi=roi, year=2025, to_int16=True))
            step += 1

        print(f"\n[{step}/{total_steps - 1}] classify_gee — GEE server-side ...")
        results["classify_gee"].append(classify_gee(name=name, roi=roi))
        step += 1

        print(f"\n[{step}/{total_steps - 1}] classify_gee_xee — GEE classifica, Xee baixa raster resultado ...")
        results["classify_gee_xee"].append(classify_gee_xee(name=name, roi=roi))
        step += 1

        if skip_xee:
            print(f"\n[–] classify_xee — ignorado (--skip-xee)")
        else:
            print(f"\n[{step}/{total_steps - 1}] classify_xee — Xee baixa 64 features, sklearn classifica local ...")
            results["classify_xee"].append(classify_xee(name=name, roi=roi))
            step += 1

        print(f"\n[{step}/{total_steps - 1}] biomass_map — MapBiomas 2024 ...")
        results["biomass_map"].append(biomass_map(name=name, roi=roi))

    print(f"\n\n{'█' * 70}")
    print("  RESULTADO FINAL — issue #112")
    print(f"{'█' * 70}")
    _print_all(results, props_by_name, skip_xee, skip_embed)

    report_path = _OUTPUT_DIR / "run_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(
        {"generated_at": datetime.now().isoformat(timespec="seconds"),
         "skip_xee": skip_xee, "skip_embed": skip_embed, "results": results},
        indent=2, ensure_ascii=False))
    print(f"Relatório salvo em {report_path.relative_to(_ROOT)}")
    print(f"\nTotal: {time.perf_counter() - global_start:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Issue #112 — benchmark completo novos CARs")
    parser.add_argument("--skip-xee",   action="store_true",
                        help="Pula classify_xee (~2 min por imóvel, usa Xee p/ 64 features)")
    parser.add_argument("--skip-embed", action="store_true",
                        help="Pula export_embedding (~70–131 s por imóvel)")
    args = parser.parse_args()
    run(skip_xee=args.skip_xee, skip_embed=args.skip_embed)
