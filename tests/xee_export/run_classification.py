"""
Comparação de metodologias de classificação de pastagem (issue #112).

Roda, para cada imóvel de teste, a classificação pasto/não-pasto por duas vias e
compara o tempo total: (1) GEE-nativo (smileRandomForest server-side) e (2) Xee-local
(exporta o embedding e classifica com sklearn na máquina). Também gera o mapa
classificado e a imagem de biomassa para análise.

Uso (a partir da raiz do projeto):
    .venv/bin/python -m tests.xee_export.run_classification
"""
import json
import time

from datetime import datetime
from typing import Dict, List

from tests.xee_export.export import _OUTPUT_DIR, _ROOT, load_test_properties
from tests.xee_export.classification import (
    biomass_image,
    classify_gee_native,
    classify_xee_local,
)


def _print_comparison(rows: List[Dict]) -> None:
    """Imprime a comparação de tempo entre as metodologias."""
    columns = ["imovel", "metodologia", "area_pasto_ha", "t_total_s", "imagem"]
    widths = {c: max(len(c), *(len(str(row.get(c, ""))) for row in rows)) for c in columns}

    header = " | ".join(c.ljust(widths[c]) for c in columns)
    print("\n" + header)
    print("-" * len(header))
    for row in rows:
        print(" | ".join(str(row.get(c, "")).ljust(widths[c]) for c in columns))


def run() -> List[Dict]:
    """Executa a comparação completa e persiste o relatório."""
    properties = load_test_properties()
    rows: List[Dict] = []

    for prop in properties:
        print(f"\n>>> {prop['name']} ({prop['codigo']}) ~ {prop['area_ha']} ha")

        rows.append(classify_gee_native(name=prop["name"], roi=prop["roi"]))
        rows.append(classify_xee_local(name=prop["name"], roi=prop["roi"]))
        rows.append(biomass_image(name=prop["name"], roi=prop["roi"]))

    _print_comparison([r for r in rows if r["metodologia"] != "biomassa"])

    report_path = _OUTPUT_DIR / "classification_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(
        {"generated_at": datetime.now().isoformat(timespec="seconds"), "results": rows},
        indent=2, ensure_ascii=False))
    print(f"\nRelatório salvo em {report_path.relative_to(_ROOT)}")

    return rows


if __name__ == "__main__":
    start = time.perf_counter()
    run()
    print(f"\nComparação concluída em {time.perf_counter() - start:.1f}s")
