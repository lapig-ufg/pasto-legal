from datetime import date
from typing import List, Optional

from reportlab.platypus import Flowable

from app.utils.interfaces.property_record import RuralProperty
from app.utils.interfaces.property_stats import (
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
from app.utils.scripts import pdf_scripts as pdf


def build_placeholder_property_stats(car_code: str) -> PropertyStats:
    """Monta um PropertyStats com dados de exemplo (placeholder), no formato real esperado pela issue #126."""
    current_year = date.today().year
    biomass_series = [(current_year - 2, 12.4), (current_year - 1, 15.1), (current_year, 14.8)]

    pasture_stats_list = [
        PastureStats(biomass_stats=BiomassStats(observation_year=year, amount=Value(value=value, unity="t/ha")))
        for year, value in biomass_series
    ]

    pasture_stats_list[-1].age_stats = AgeStats(
        observation_year=current_year,
        data=[
            AgeData(age="0-2 anos", amount=Value(value=120.0, unity="ha")),
            AgeData(age="2-5 anos", amount=Value(value=80.0, unity="ha")),
            AgeData(age="5+ anos", amount=Value(value=45.0, unity="ha")),
        ],
    )
    pasture_stats_list[-1].vigor_stats = VigorStats(
        observation_year=current_year,
        data=[
            VigorData(vigor="Alto", amount=Value(value=90.0, unity="ha")),
            VigorData(vigor="Médio", amount=Value(value=100.0, unity="ha")),
            VigorData(vigor="Baixo", amount=Value(value=55.0, unity="ha")),
        ],
    )
    pasture_stats_list[-1].lulc_stats = LULCStats(
        observation_year=current_year,
        data=[
            LULCData(lulc_class="Pastagem", amount=Value(value=210.0, unity="ha")),
            LULCData(lulc_class="Vegetação Nativa", amount=Value(value=35.0, unity="ha")),
            LULCData(lulc_class="Área Antrópica", amount=Value(value=10.0, unity="ha")),
        ],
    )

    return PropertyStats(car_code=car_code, list_pasture_stats=pasture_stats_list)


def _build_biomass_section(pasture_stats_list: List[PastureStats]) -> List[Flowable]:
    blocks: List[Flowable] = [pdf.section_title("1. Análise de Biomassa")]

    series = [
        (str(stats.biomass_stats.observation_year), stats.biomass_stats.amount.value, stats.biomass_stats.amount.unity)
        for stats in pasture_stats_list
        if stats.biomass_stats
    ]
    if not series:
        blocks.append(pdf.placeholder_note("Dados de biomassa indisponíveis para esta propriedade."))
        return blocks

    unit = series[0][2]
    blocks.append(pdf.placeholder_note(
        "Estimativa de massa biológica acumulada na vegetação, por ano de referência."
    ))
    blocks.append(pdf.simulated_bar_table([(year, value) for year, value, _ in series], unit=unit))
    return blocks


def _build_pasture_section(pasture_stats: Optional[PastureStats]) -> List[Flowable]:
    blocks: List[Flowable] = [pdf.section_title("2. Análise de Pastagem")]

    if pasture_stats is None:
        blocks.append(pdf.placeholder_note("Dados de pastagem indisponíveis para esta propriedade."))
        return blocks

    blocks.append(pdf.subsection_title("Idade da Pastagem"))
    if pasture_stats.age_stats:
        blocks.append(pdf.placeholder_note(f"Ano de referência: {pasture_stats.age_stats.observation_year}."))
        blocks.append(pdf.data_table(
            ["Faixa de Idade", "Área"],
            [[item.age, str(item.amount)] for item in pasture_stats.age_stats.data],
        ))
    else:
        blocks.append(pdf.placeholder_note("Dados de idade indisponíveis."))

    blocks.append(pdf.subsection_title("Vigor da Pastagem"))
    if pasture_stats.vigor_stats:
        blocks.append(pdf.placeholder_note(f"Ano de referência: {pasture_stats.vigor_stats.observation_year}."))
        blocks.append(pdf.data_table(
            ["Nível de Vigor", "Área"],
            [[item.vigor, str(item.amount)] for item in pasture_stats.vigor_stats.data],
        ))
    else:
        blocks.append(pdf.placeholder_note("Dados de vigor indisponíveis."))

    blocks.append(pdf.subsection_title("Uso e Cobertura do Solo (LULC)"))
    if pasture_stats.lulc_stats:
        blocks.append(pdf.placeholder_note(f"Ano de referência: {pasture_stats.lulc_stats.observation_year}."))
        blocks.append(pdf.data_table(
            ["Classe", "Área"],
            [[item.lulc_class, str(item.amount)] for item in pasture_stats.lulc_stats.data],
        ))
    else:
        blocks.append(pdf.placeholder_note("Dados de LULC indisponíveis."))

    return blocks


def build_boletim_story(
    rural_property: RuralProperty, property_stats: PropertyStats, emission_date: Optional[date] = None
) -> List[Flowable]:
    """Monta a lista de flowables do boletim: cabeçalho + Seção 1 (biomassa) + Seção 2 (pastagem)."""
    emission_date = emission_date or date.today()
    farm_name = rural_property.nickname or rural_property.car_code
    pasture_stats_list = property_stats.list_pasture_stats or []
    latest_pasture_stats = pasture_stats_list[-1] if pasture_stats_list else None

    story: List[Flowable] = [
        pdf.brand_header(),
        pdf.document_title(farm_name),
        pdf.document_subtitle(f"Data de Emissão: {emission_date.strftime('%d/%m/%Y')} · CAR: {rural_property.car_code}"),
        pdf.warning_box(
            "A biomassa é calculada para o mês/ano atual. Idade, vigor e uso do solo (LULC) "
            "refletem o ano mais recente disponível no MapBiomas, podendo estar até um ano defasados."
        ),
        pdf.spacer(4),
    ]

    story.extend(_build_biomass_section(pasture_stats_list))
    story.append(pdf.spacer(4))
    story.extend(_build_pasture_section(latest_pasture_stats))

    return story
