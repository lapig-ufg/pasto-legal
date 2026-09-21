"""Apresentação das estimativas: legendas de mapa, blocos de boletim e texto de chat.

Existe para que nenhum número apareça sem o seu contexto. Toda legenda de mapa
traz métrica, fonte, período e unidade; todo bloco de boletim traz, além disso,
resolução do raster, resolução efetiva da máscara, cobertura válida, incerteza,
versão e limitações.
"""

from typing import List, Optional

import PIL

from app.schemas.biomass_schemas import UNIT_LABELS, BiomassEstimate, StockingCapacityEstimate
from app.services.geospatial.image import append_continuous_colorbar


# Paleta contínua usada nos mapas de biomassa/produtividade.
BIOMASS_PALETTE = ["#000033", "#9400D3", "#FF00FF", "#00FFFF", "#FFFFFF"]


def colorbar_title(estimate: BiomassEstimate) -> str:
    """
    Título da barra de cores: métrica, fonte e período, em duas linhas.

    Args:
        estimate (BiomassEstimate): Estimativa retratada no mapa.

    Returns:
        str: Título pronto para `append_continuous_colorbar`.
    """
    source = estimate.source if not estimate.source_version else f"{estimate.source} {estimate.source_version}"
    return f"{estimate.metric_label}\n{source} | {estimate.period_label()}"


def annotate_map(
    image: "PIL.Image.Image",
    estimate: BiomassEstimate,
    vmin: float,
    vmax: float,
) -> "PIL.Image.Image":
    """
    Aplica ao mapa a barra de cores com métrica, fonte, período e unidade.

    Args:
        image (PIL.Image.Image): Mapa renderizado.
        estimate (BiomassEstimate): Estimativa retratada.
        vmin (float): Valor mínimo da escala de cores, na unidade da métrica.
        vmax (float): Valor máximo da escala de cores, na unidade da métrica.

    Returns:
        PIL.Image.Image: Mapa com a barra de cores anexada.
    """
    return append_continuous_colorbar(
        image,
        title=colorbar_title(estimate),
        vmin=round(vmin, 2),
        vmax=round(vmax, 2),
        unit=estimate.unit_label,
        palette=BIOMASS_PALETTE,
    )


def map_caption(estimate: BiomassEstimate) -> str:
    """
    Legenda textual que acompanha o mapa no chat.

    Args:
        estimate (BiomassEstimate): Estimativa retratada.

    Returns:
        str: Texto com o bloco de metadados obrigatório mais a leitura das cores.
    """
    return (
        f"{estimate.to_report_block()}\n"
        "Leitura das cores: tons claros (ciano/branco) indicam valores altos; "
        "tons escuros (roxo/azul-escuro) indicam valores baixos."
    )


def metadata_rows(estimate: BiomassEstimate) -> List[tuple]:
    """
    Linhas (rótulo, valor) do bloco de metadados, para tabelas do boletim em PDF.

    Args:
        estimate (BiomassEstimate): Estimativa a descrever.

    Returns:
        List[tuple]: Pares (rótulo, valor) na ordem obrigatória.
    """
    rows = [("Métrica", estimate.metric_label)]

    value = (
        "indisponível" if estimate.value_per_ha is None
        else f"{estimate.value_per_ha:.2f} {estimate.unit_label}"
    )
    rows.append(("Valor", value))

    if estimate.total_value is not None:
        rows.append((
            "Total na área válida",
            f"{estimate.total_value:.2f} {UNIT_LABELS.get(estimate.total_unit, estimate.total_unit)}",
        ))

    source = estimate.source if not estimate.source_version else f"{estimate.source} ({estimate.source_version})"
    rows.append(("Fonte", source))
    rows.append(("Período", estimate.period_label()))
    rows.append(("Unidade", estimate.unit_label))
    rows.append(("Resolução do produto", f"{estimate.raster_resolution_m:g} m"))

    mask = estimate.pasture_mask_source
    if estimate.effective_mask_resolution_m is not None:
        mask += f", {estimate.effective_mask_resolution_m:g} m"
    if estimate.pasture_mask_reference_year is not None:
        mask += f", referência {estimate.pasture_mask_reference_year}"
    rows.append(("Máscara de pastagem", mask))

    if estimate.pasture_mask is not None and estimate.pasture_mask.pasture_fraction is not None:
        rows.append((
            "Pastagem na propriedade",
            f"{estimate.pasture_mask.pasture_fraction * 100:.0f}% "
            f"({estimate.pasture_mask.pasture_area_ha:.1f} ha)",
        ))

    rows.append((
        "Cobertura válida",
        "não informada" if estimate.valid_observation_fraction is None
        else f"{estimate.valid_observation_fraction * 100:.0f}%",
    ))

    if estimate.lower_bound_per_ha is not None and estimate.upper_bound_per_ha is not None:
        rows.append((
            "Incerteza",
            f"{estimate.lower_bound_per_ha:.2f} a {estimate.upper_bound_per_ha:.2f} "
            f"{estimate.unit_label} ({estimate.uncertainty_method})",
        ))
    else:
        rows.append(("Incerteza", "não quantificada"))

    rows.append(("Versão", estimate.model_version))

    if estimate.limitations:
        rows.append(("Limitações", " ".join(estimate.limitations)))

    return rows


def summarize_for_chat(
    monthly: Optional[BiomassEstimate] = None,
    annual: Optional[BiomassEstimate] = None,
    standing: Optional[BiomassEstimate] = None,
    forage: Optional[BiomassEstimate] = None,
    capacity: Optional[StockingCapacityEstimate] = None,
) -> str:
    """
    Resumo em PT-BR das métricas disponíveis, cada uma com o seu contexto.

    Métricas ausentes são declaradas ausentes: o texto nunca substitui uma pela
    outra nem omite o período de referência.

    Args:
        monthly (BiomassEstimate, optional): Produtividade mensal.
        annual (BiomassEstimate, optional): Produtividade anual.
        standing (BiomassEstimate, optional): Biomassa em pé.
        forage (BiomassEstimate, optional): Forragem disponível.
        capacity (StockingCapacityEstimate, optional): Capacidade de suporte.

    Returns:
        str: Texto pronto para o boletim ou para o retorno de uma ferramenta.
    """
    sections: List[str] = ["# ESTIMATIVAS DE BIOMASSA E PRODUTIVIDADE DE PASTAGEM"]
    sections.append(
        "Produtividade (quanto o pasto produziu), biomassa em pé (quanto está no "
        "piquete) e forragem disponível (quanto pode ser pastejado) são grandezas "
        "distintas e estão separadas abaixo.\n"
    )

    blocks = [
        ("## 1. Produtividade mensal de matéria seca", monthly,
         "Sem estimativa mensal disponível para esta propriedade no período consultado."),
        ("## 2. Produtividade anual de matéria seca (série histórica)", annual,
         "Sem estimativa anual disponível para esta propriedade."),
        ("## 3. Biomassa em pé", standing,
         "Sem estimativa de biomassa em pé: exige modelo calibrado com massa seca "
         "medida em campo, que ainda não está disponível."),
        ("## 4. Forragem disponível para pastejo", forage,
         "Sem estimativa de forragem disponível: depende da biomassa em pé."),
    ]

    for heading, estimate, absent_message in blocks:
        sections.append(heading)
        sections.append(estimate.to_report_block() if estimate is not None else absent_message)
        sections.append("---")

    sections.append("## 5. Capacidade de suporte")
    if capacity is not None:
        sections.append(str(capacity))
    else:
        sections.append(
            "Sem cálculo de capacidade de suporte: exige produtividade anual (ou 12 "
            "meses acumulados), ou forragem disponível com manejo informado."
        )

    return "\n".join(sections)
