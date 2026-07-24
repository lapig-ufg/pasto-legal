"""
Gerador de mock para iterar no layout do boletim sem depender do agente/GEE/Streamlit.

    .venv/bin/python -m tests.pdf.manual_mock_boletim

Grava tmp/boletim_mock.pdf (pasta já gitignorada) — abra o arquivo pra conferir
espaçamento, quebras de página e word-wrap visualmente.
"""
from pathlib import Path

from app.utils.interfaces.property_record import RuralProperty, SpatialFeatures
from app.utils.scripts.boletim_scripts import build_boletim_story, build_placeholder_property_stats
from app.utils.scripts.pdf_scripts import render_document


def main() -> None:
    rural_property = RuralProperty(
        nickname="Fazenda Blue (mock)",
        car_code="GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0",
        spatial_features=SpatialFeatures(
            total_area=23.4674,
            municipality="Corrego do Ouro",
            coordinates=[[[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]]]],
        ),
    )
    stats = build_placeholder_property_stats(rural_property.car_code)
    story = build_boletim_story(rural_property, stats)
    pdf_bytes = render_document(story)

    output_dir = Path("tmp")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "boletim_mock.pdf"
    output_path.write_bytes(pdf_bytes)

    print(f"Gerado: {output_path} ({len(pdf_bytes)} bytes)")


if __name__ == "__main__":
    main()
