from datetime import date
from typing import List, Optional

from reportlab.platypus import Flowable

from app.schemas.rural_property import RuralProperty
from app.schemas.property_stats import (
    AgeData,
    AgeStats,
    BiomassStats,
    LULCData,
    LULCStats,
    PastureStats,
    PropertyStats,
    Value,
    VigorData,
    VigorStats,
)
from app.services import pdf_scripts as pdf


def build_placeholder_property_stats(car_code: str) -> PropertyStats:
    """Monta um PropertyStats com dados de exemplo (placeholder), no formato real esperado pela issue #126."""
    current_year = date.today().year

    pasture_stats = PastureStats(
        biomass_stats=BiomassStats(observation_year=current_year, amount=Value(value=14.8, unity="t/ha")),
        age_stats=AgeStats(
            observation_year=current_year,
            data=[
                AgeData(age="0-2 anos", amount=Value(value=120.0, unity="ha")),
                AgeData(age="2-5 anos", amount=Value(value=80.0, unity="ha")),
                AgeData(age="5+ anos", amount=Value(value=45.0, unity="ha")),
            ],
        ),
        vigor_stats=VigorStats(
            observation_year=current_year,
            data=[
                VigorData(vigor="Alto", amount=Value(value=90.0, unity="ha")),
                VigorData(vigor="Médio", amount=Value(value=100.0, unity="ha")),
                VigorData(vigor="Baixo", amount=Value(value=55.0, unity="ha")),
            ],
        ),
        lulc_stats=LULCStats(
            observation_year=current_year,
            data=[
                LULCData(lulc_class="Pastagem", amount=Value(value=210.0, unity="ha")),
                LULCData(lulc_class="Vegetação Nativa", amount=Value(value=35.0, unity="ha")),
                LULCData(lulc_class="Área Antrópica", amount=Value(value=10.0, unity="ha")),
            ],
        ),
    )

    return PropertyStats(car_code=car_code, list_pasture_stats=[pasture_stats])


def _build_location_blocks(location_image_bytes: bytes) -> List[Flowable]:
    return [
        pdf.section_title("Localização da Propriedade"),
        pdf.single_image(location_image_bytes, caption="Imagem de satélite com o limite do CAR"),
        pdf.spacer(4),
    ]


def _build_age_blocks(pasture_stats: Optional[PastureStats]) -> List[Flowable]:
    blocks: List[Flowable] = [pdf.subsection_title("Idade da Pastagem")]
    if pasture_stats and pasture_stats.age_stats:
        blocks.append(pdf.placeholder_note(f"Ano de referência: {pasture_stats.age_stats.observation_year}."))
        blocks.append(pdf.data_table(
            ["Faixa de Idade", "Área"],
            [[item.age, str(item.amount)] for item in pasture_stats.age_stats.data],
        ))
    else:
        blocks.append(pdf.placeholder_note("Dados de idade indisponíveis."))
    return blocks


def _build_vigor_blocks(
    pasture_stats: Optional[PastureStats], satellite_image_bytes: bytes, vigor_map_image_bytes: Optional[bytes]
) -> List[Flowable]:
    blocks: List[Flowable] = [pdf.subsection_title("Vigor da Pastagem")]

    if vigor_map_image_bytes:
        blocks.append(pdf.side_by_side_images(
            satellite_image_bytes, vigor_map_image_bytes,
            left_caption="Imagem de satélite", right_caption="Mapa de vigor",
        ))
        blocks.append(pdf.spacer(2))

    if pasture_stats and pasture_stats.vigor_stats:
        blocks.append(pdf.placeholder_note(f"Ano de referência: {pasture_stats.vigor_stats.observation_year}."))
        blocks.append(pdf.data_table(
            ["Nível de Vigor", "Área"],
            [[item.vigor, str(item.amount)] for item in pasture_stats.vigor_stats.data],
        ))
    else:
        blocks.append(pdf.placeholder_note("Dados de vigor indisponíveis."))

    return blocks


def _build_lulc_blocks(pasture_stats: Optional[PastureStats]) -> List[Flowable]:
    blocks: List[Flowable] = [pdf.subsection_title("Uso e Cobertura do Solo (LULC)")]
    if pasture_stats and pasture_stats.lulc_stats:
        blocks.append(pdf.placeholder_note(f"Ano de referência: {pasture_stats.lulc_stats.observation_year}."))
        blocks.append(pdf.data_table(
            ["Classe", "Área"],
            [[item.lulc_class, str(item.amount)] for item in pasture_stats.lulc_stats.data],
        ))
    else:
        blocks.append(pdf.placeholder_note("Dados de LULC indisponíveis."))
    return blocks


def _build_biomass_blocks(pasture_stats: Optional[PastureStats]) -> List[Flowable]:
    if pasture_stats is None or pasture_stats.biomass_stats is None:
        return [pdf.placeholder_note("Dados de biomassa indisponíveis para esta propriedade.")]

    biomass = pasture_stats.biomass_stats
    return [pdf.key_value_table([
        ("Ano de referência", str(biomass.observation_year)),
        ("Estimativa de biomassa", str(biomass.amount)),
    ])]


def build_boletim_story(
    rural_property: RuralProperty,
    property_stats: PropertyStats,
    satellite_image_bytes: bytes,
    location_image_bytes: bytes,
    pasture_map_image_bytes: bytes,
    vigor_map_image_bytes: Optional[bytes] = None,
    biomass_map_image_bytes: Optional[bytes] = None,
    soil_map_image_bytes: Optional[bytes] = None,
    emission_date: Optional[date] = None,
) -> List[Flowable]:
    """Monta a lista de flowables do boletim: localização, pastagem (idade/vigor/LULC),
    biomassa e tipos de solo — cada seção com o mapa temático ao lado da imagem de
    satélite "crua" e os dados numéricos logo abaixo.
    """
    emission_date = emission_date or date.today()
    farm_name = rural_property.nickname or rural_property.car_code
    pasture_stats_list = property_stats.list_pasture_stats or []
    latest_pasture_stats = pasture_stats_list[-1] if pasture_stats_list else None

    story: List[Flowable] = [
        pdf.masthead(farm_name, f"Data de Emissão: {emission_date.strftime('%d/%m/%Y')} · CAR: {rural_property.car_code}"),
        pdf.spacer(4),
        pdf.warning_box(
            "A biomassa é calculada para o mês/ano atual. Idade, vigor e uso do solo (LULC) "
            "refletem o ano mais recente disponível no MapBiomas, podendo estar até um ano defasados."
        ),
        pdf.spacer(4),
    ]

    story.extend(_build_location_blocks(location_image_bytes))

    story.append(pdf.section_title("1. Dados de Pastagem"))
    story.append(pdf.side_by_side_images(
        satellite_image_bytes, pasture_map_image_bytes,
        left_caption="Imagem de satélite", right_caption="Classificação de pastagem",
    ))
    story.append(pdf.spacer(3))
    story.extend(_build_age_blocks(latest_pasture_stats))
    story.extend(_build_vigor_blocks(latest_pasture_stats, satellite_image_bytes, vigor_map_image_bytes))
    story.extend(_build_lulc_blocks(latest_pasture_stats))

    story.append(pdf.spacer(4))

    story.append(pdf.section_title("2. Análise de Biomassa"))
    if biomass_map_image_bytes:
        story.append(pdf.side_by_side_images(
            satellite_image_bytes, biomass_map_image_bytes,
            left_caption="Imagem de satélite", right_caption="Mapa de biomassa",
        ))
        story.append(pdf.spacer(3))
    story.extend(_build_biomass_blocks(latest_pasture_stats))

    if soil_map_image_bytes:
        story.append(pdf.spacer(4))
        story.append(pdf.section_title("3. Tipos de Solo"))
        story.append(pdf.side_by_side_images(
            satellite_image_bytes, soil_map_image_bytes,
            left_caption="Imagem de satélite", right_caption="Textura do solo",
        ))

    return story


def build_boletim_chat_summary(rural_property: RuralProperty, pasture_stats: PastureStats) -> str:
    """Monta a mensagem de chat que acompanha o PDF, pronta em Python (sem depender da LLM
    compor um resumo criativo) — reduz o boletim a uma única chamada de tool cujo resultado
    a LLM só precisa repassar ao usuário.
    """
    farm_name = rural_property.nickname or rural_property.car_code

    reference_year = None
    pasture_area_ha = None
    if pasture_stats.lulc_stats:
        reference_year = pasture_stats.lulc_stats.observation_year
        pasture_entry = next((item for item in pasture_stats.lulc_stats.data if item.lulc_class == "Pastagem"), None)
        if pasture_entry:
            pasture_area_ha = pasture_entry.amount.value
    elif pasture_stats.age_stats:
        reference_year = pasture_stats.age_stats.observation_year

    year_text = f" (ano de referência *{reference_year}*)" if reference_year else ""
    area_text = f"*{pasture_area_ha:g} ha* de pastagem" if pasture_area_ha is not None else "área de pastagem mapeada"

    biomass_text = ""
    if pasture_stats.biomass_stats:
        biomass = pasture_stats.biomass_stats
        biomass_text = (
            f" A estimativa de biomassa para *{biomass.observation_year}* é de "
            f"*{biomass.amount.value:.2f} {biomass.amount.unity}*."
        )

    return (
        f"O boletim em PDF da *{farm_name}* foi gerado com sucesso!{year_text} A propriedade tem "
        f"{area_text}.{biomass_text} O documento traz os mapas de localização, pastagem, vigor, "
        "biomassa e solo, pronto para compartilhar com seu agrônomo ou parceiros."
    )
