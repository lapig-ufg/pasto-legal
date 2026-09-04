"""
Gerador de mock para iterar no layout do boletim sem depender do agente/GEE/Streamlit.

    .venv/bin/python -m tests.pdf.manual_mock_boletim

Grava tmp/boletim_mock.pdf (pasta já gitignorada) — abra o arquivo pra conferir
espaçamento, quebras de página e word-wrap visualmente. As imagens são placeholders
sintéticos (retângulos coloridos); para ver com imagens reais do satélite, gere via
a tool `generate_property_boletim` (precisa de GEE).
"""
from io import BytesIO
from pathlib import Path

from PIL import Image as PILImage

from app.schemas.rural_property import RuralProperty, SpatialFeatures
from app.services.boletim_scripts import build_boletim_story, build_placeholder_property_stats
from app.services.pdf_scripts import render_document


def _mock_image_bytes(color) -> bytes:
    buffer = BytesIO()
    PILImage.new("RGB", (600, 450), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


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
    story = build_boletim_story(
        rural_property, stats,
        location_image_bytes=_mock_image_bytes((150, 130, 100)),
        pasture_map_image_bytes=_mock_image_bytes((60, 140, 70)),
        vigor_map_image_bytes=_mock_image_bytes((215, 25, 28)),
        biomass_map_image_bytes=_mock_image_bytes((150, 70, 130)),
        soil_map_image_bytes=_mock_image_bytes((168, 56, 0)),
    )
    pdf_bytes = render_document(story)

    output_dir = Path("tmp")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "boletim_mock.pdf"
    output_path.write_bytes(pdf_bytes)

    print(f"Gerado: {output_path} ({len(pdf_bytes)} bytes)")


if __name__ == "__main__":
    main()
