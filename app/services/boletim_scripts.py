from datetime import date
from typing import TYPE_CHECKING, List, Optional

from reportlab.platypus import Flowable

from app.schemas.biomass_schemas import METRIC_LABELS
from app.schemas.feature import Feature
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
from app.services.geospatial.biomass.biomass_reporting import metadata_rows

if TYPE_CHECKING:
    from app.services.geospatial.biomass.biomass_assessment import BiomassAssessment


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
        pdf.single_image(location_image_bytes, caption="Imagem de satélite com o limite do CAR", image_height_mm=100),
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
    pasture_stats: Optional[PastureStats], vigor_map_image_bytes: Optional[bytes]
) -> List[Flowable]:
    blocks: List[Flowable] = [pdf.subsection_title("Vigor da Pastagem")]

    if vigor_map_image_bytes:
        blocks.append(pdf.single_image(
            vigor_map_image_bytes, caption="Mapa de vigor", image_height_mm=100,
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


def _build_biomass_blocks(
    pasture_stats: Optional[PastureStats],
    assessment: Optional["BiomassAssessment"] = None,
) -> List[Flowable]:
    """Blocos da seção de biomassa: uma subseção por métrica, cada uma com o bloco
    de metadados obrigatório (fonte, período, unidade, resoluções, cobertura válida,
    incerteza, versão e limitações). Métricas ausentes são declaradas ausentes."""
    if assessment is None:
        if pasture_stats is None or pasture_stats.biomass_stats is None:
            return [pdf.placeholder_note("Dados de biomassa indisponíveis para esta propriedade.")]

        biomass = pasture_stats.biomass_stats
        return [pdf.key_value_table([
            ("Ano de referência", str(biomass.observation_year)),
            ("Estimativa", str(biomass.amount)),
        ])]

    blocks: List[Flowable] = []

    metrics = [
        ("2.1. Produtividade mensal de matéria seca", assessment.monthly_productivity),
        ("2.2. Produtividade anual de matéria seca", assessment.annual_productivity),
        ("2.3. Biomassa em pé", assessment.standing_biomass),
        ("2.4. Forragem disponível para pastejo", assessment.available_forage),
    ]

    for title, estimate in metrics:
        blocks.append(pdf.subsection_title(title))
        if estimate is None:
            blocks.append(pdf.placeholder_note("Métrica indisponível para esta propriedade."))
        else:
            blocks.append(pdf.key_value_table(metadata_rows(estimate)))
        blocks.append(pdf.spacer(2))

    blocks.append(pdf.subsection_title("2.5. Capacidade de suporte"))
    if assessment.stocking_capacity is None:
        blocks.append(pdf.placeholder_note(
            "Capacidade de suporte indisponível: exige produtividade anual (ou 12 meses "
            "acumulados), ou forragem disponível com manejo informado."
        ))
    else:
        blocks.append(pdf.key_value_table(_capacity_rows(assessment.stocking_capacity)))

    if assessment.unavailable:
        blocks.append(pdf.spacer(2))
        blocks.append(pdf.placeholder_note(
            "Métricas indisponíveis: " + " ".join(assessment.unavailable)
        ))

    return blocks


def _capacity_rows(capacity) -> List[tuple]:
    """Linhas (rótulo, valor) da capacidade de suporte, com as grandezas separadas."""
    rows = [
        ("Base de cálculo", METRIC_LABELS[capacity.basis_metric_type]),
        (
            "Período da base",
            f"{capacity.basis_period_start.strftime('%d/%m/%Y')} a "
            f"{capacity.basis_period_end.strftime('%d/%m/%Y')}",
        ),
        ("Área de pastagem considerada", f"{capacity.pasture_area_ha:.2f} ha"),
    ]

    if capacity.annual_potential_capacity_ua is not None:
        rows.append((
            "Capacidade anual potencial",
            f"{capacity.annual_potential_capacity_ua:.2f} UA "
            f"({capacity.annual_potential_capacity_ua_ha:.2f} UA/ha)",
        ))
    if capacity.period_capacity_ua is not None:
        rows.append((
            f"Capacidade no período ({capacity.period_days} dias)",
            f"{capacity.period_capacity_ua:.2f} UA "
            f"({capacity.period_capacity_ua_ha:.2f} UA/ha)",
        ))
    if capacity.reported_stocking_ua is not None:
        rows.append((
            "Lotação atual informada",
            f"{capacity.reported_stocking_ua:.2f} UA "
            f"({capacity.reported_stocking_ua_ha:.2f} UA/ha)",
        ))
    if capacity.forage_balance_t_dm is not None:
        rows.append(("Saldo forrageiro estimado", f"{capacity.forage_balance_t_dm:.2f} t MS"))

    rows.append(("Demanda adotada", f"{capacity.annual_demand_t_dm_per_ua:.2f} t MS/UA/ano"))
    rows.append(("Versão", capacity.model_version))

    if capacity.limitations:
        rows.append(("Limitações", " ".join(capacity.limitations)))

    return rows


def build_boletim_story(
    rural_property: Feature,
    property_stats: PropertyStats,
    location_image_bytes: bytes,
    pasture_map_image_bytes: bytes,
    vigor_map_image_bytes: Optional[bytes] = None,
    biomass_map_image_bytes: Optional[bytes] = None,
    soil_map_image_bytes: Optional[bytes] = None,
    emission_date: Optional[date] = None,
    biomass_assessment: Optional["BiomassAssessment"] = None,
    biomass_map_caption: str = "Mapa de produtividade de matéria seca",
) -> List[Flowable]:
    """Monta a lista de flowables do boletim: localização, pastagem (idade/vigor/LULC),
    biomassa e tipos de solo — cada seção com o mapa temático principal e os dados
    numéricos logo abaixo.

    Quando `biomass_assessment` é informado, a seção de biomassa traz uma subseção
    por métrica (produtividade mensal, produtividade anual, biomassa em pé, forragem
    disponível e capacidade de suporte), cada uma com o seu bloco de metadados.
    """
    emission_date = emission_date or date.today()
    farm_name = rural_property.id or rural_property.get_metadata("car_code") or "Propriedade"
    pasture_stats_list = property_stats.list_pasture_stats or []
    latest_pasture_stats = pasture_stats_list[-1] if pasture_stats_list else None

    story: List[Flowable] = [
        pdf.masthead(farm_name, f"Data de Emissão: {emission_date.strftime('%d/%m/%Y')} · ID: {rural_property.id}"),
        pdf.spacer(4),
        pdf.warning_box(
            "Produtividade, biomassa em pé e forragem disponível são métricas distintas: "
            "cada seção abaixo traz a sua fonte, período, unidade e resolução. Idade, vigor "
            "e uso do solo (LULC) refletem o ano mais recente disponível no MapBiomas, "
            "podendo estar até um ano defasados."
        ),
        pdf.spacer(4),
    ]

    story.extend(_build_location_blocks(location_image_bytes))

    story.append(pdf.section_title("1. Dados de Pastagem"))
    story.append(pdf.single_image(
        pasture_map_image_bytes, caption="Classificação de pastagem", image_height_mm=100,
    ))
    story.append(pdf.spacer(3))
    story.extend(_build_age_blocks(latest_pasture_stats))
    story.extend(_build_vigor_blocks(latest_pasture_stats, vigor_map_image_bytes))
    story.extend(_build_lulc_blocks(latest_pasture_stats))

    story.append(pdf.spacer(4))

    story.append(pdf.section_title("2. Produtividade, Biomassa e Forragem"))
    if biomass_map_image_bytes:
        story.append(pdf.single_image(
            biomass_map_image_bytes, caption=biomass_map_caption, image_height_mm=100,
        ))
        story.append(pdf.spacer(3))
    story.extend(_build_biomass_blocks(latest_pasture_stats, assessment=biomass_assessment))

    if soil_map_image_bytes:
        story.append(pdf.spacer(4))
        story.append(pdf.section_title("3. Tipos de Solo"))
        story.append(pdf.single_image(
            soil_map_image_bytes, caption="Textura do solo", image_height_mm=100,
        ))

    return story


def build_boletim_chat_summary(
    rural_property: Feature,
    pasture_stats: PastureStats,
    biomass_assessment: Optional["BiomassAssessment"] = None,
) -> str:
    """Monta a mensagem de chat que acompanha o PDF, pronta em Python (sem depender da LLM
    compor um resumo criativo) — reduz o boletim a uma única chamada de tool cujo resultado
    a LLM só precisa repassar ao usuário.
    """
    farm_name = rural_property.id or rural_property.get_metadata("car_code") or "Propriedade"

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

    biomass_text = _chat_biomass_sentence(pasture_stats, biomass_assessment)

    return (
        f"O boletim em PDF da *{farm_name}* foi gerado com sucesso!{year_text} A propriedade tem "
        f"{area_text}.{biomass_text} O documento traz os mapas de localização, pastagem, vigor, "
        "produtividade e solo, pronto para compartilhar com seu agrônomo ou parceiros."
    )


def _chat_biomass_sentence(
    pasture_stats: PastureStats,
    assessment: Optional["BiomassAssessment"],
) -> str:
    """Frase de biomassa do resumo de chat, sempre nomeando a métrica e o período.

    A métrica mais recente vence (produtividade mensal antes da anual), mas nunca
    sem dizer qual é e a que período se refere.
    """
    if assessment is not None:
        estimate = assessment.monthly_productivity or assessment.annual_productivity
        if estimate is not None:
            return (
                f" A *{estimate.metric_label.lower()}* no período de "
                f"*{estimate.period_label()}* é de *{estimate.value_per_ha:.2f} "
                f"{estimate.unit_label}*."
            )
        return (
            " Não há estimativa de produtividade disponível para esta propriedade "
            "no período consultado."
        )

    if pasture_stats.biomass_stats:
        biomass = pasture_stats.biomass_stats
        return (
            f" A estimativa para *{biomass.observation_year}* é de "
            f"*{biomass.amount.value:.2f} {biomass.amount.unity}*."
        )

    return ""
