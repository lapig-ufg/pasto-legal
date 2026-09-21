"""Gráfico da série histórica anual de produtividade de matéria seca.

Um gráfico de linha com faixa de incerteza, na identidade visual do LAPIG. A
série estimada é a linha cheia verde; o MapBiomas, quando informado, entra como
linha tracejada de referência — o tracejado carrega a identidade junto com a
legenda, de modo que a leitura não dependa só da cor.
"""

from io import BytesIO
from typing import List, Optional, Sequence

import PIL.Image

from app.schemas.biomass_schemas import BiomassEstimate


# Paleta institucional do LAPIG (https://lapig-ufg.github.io/identidade-visual/).
_GREEN = "#429B4D"
_DARK_GREEN = "#1B3A2A"
_BROWN = "#6B4C3B"
_CREAM = "#F6F1E7"
_GRID = "#DDD3C2"

# Tinta do texto: rótulos e valores nunca vestem a cor da série.
_INK = "#1B3A2A"
_INK_MUTED = "#6B4C3B"


def render_historical_series_chart(
    estimates: Sequence[BiomassEstimate],
    reference_values: Optional[dict] = None,
    reference_label: str = "MapBiomas (referência)",
    width_px: int = 1000,
    height_px: int = 520,
) -> "PIL.Image.Image":
    """
    Renderiza a série histórica anual como gráfico de linha com faixa de incerteza.

    Args:
        estimates (Sequence[BiomassEstimate]): Estimativas anuais, uma por ano.
        reference_values (dict, optional): Mapa ano -> valor de referência
            (t MS/ha/ano), desenhado como linha tracejada.
        reference_label (str): Rótulo da série de referência na legenda.
        width_px (int): Largura da imagem, em pixels.
        height_px (int): Altura da imagem, em pixels.

    Returns:
        PIL.Image.Image: Gráfico pronto para o chat ou para o boletim.

    Raises:
        ValueError: Se não houver estimativa com valor para desenhar.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    points = [item for item in estimates if item.value_per_ha is not None]
    if not points:
        raise ValueError("Não há estimativa com valor para desenhar o gráfico.")

    points = sorted(points, key=lambda item: item.period_start)
    years = [item.period_start.year for item in points]
    values = [item.value_per_ha for item in points]

    dpi = 100
    figure, axes = plt.subplots(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    figure.patch.set_facecolor("white")
    axes.set_facecolor("white")

    # Faixa de incerteza: só quando toda a série a tem, para não sugerir que os
    # anos sem intervalo são mais certos do que são.
    lower = [item.lower_bound_per_ha for item in points]
    upper = [item.upper_bound_per_ha for item in points]
    if all(bound is not None for bound in lower + upper):
        axes.fill_between(
            years, lower, upper, color=_GREEN, alpha=0.16, linewidth=0,
            label=f"Incerteza ({points[0].uncertainty_method})",
        )

    axes.plot(
        years, values, color=_GREEN, linewidth=2.0, marker="o", markersize=5,
        markerfacecolor=_GREEN, markeredgecolor="white", markeredgewidth=1.0,
        label=points[0].metric_label, zorder=3,
    )

    if reference_values:
        reference_years = sorted(year for year in reference_values if year in set(years))
        if reference_years:
            axes.plot(
                reference_years, [reference_values[year] for year in reference_years],
                color=_BROWN, linewidth=2.0, linestyle=(0, (6, 3)), marker="",
                label=reference_label, zorder=2,
            )

    # Rótulos diretos apenas no primeiro e no último ponto: um número em cada
    # ponto polui a leitura e esconde a forma da série.
    for index in (0, len(years) - 1):
        axes.annotate(
            f"{values[index]:.1f}",
            xy=(years[index], values[index]),
            xytext=(0, 9), textcoords="offset points",
            ha="center", fontsize=9, color=_INK, fontweight="bold",
        )

    axes.set_title(
        f"{points[0].metric_label}\n{points[0].source}",
        fontsize=12, color=_INK, fontweight="bold", loc="left", pad=12,
    )
    axes.set_ylabel(points[0].unit_label, fontsize=10, color=_INK_MUTED)
    axes.set_xlabel("Ano", fontsize=10, color=_INK_MUTED, labelpad=8)

    axes.grid(True, axis="y", color=_GRID, linewidth=0.8, alpha=0.9)
    axes.set_axisbelow(True)
    for side in ("top", "right"):
        axes.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axes.spines[side].set_color(_GRID)

    axes.tick_params(colors=_INK_MUTED, labelsize=9)
    axes.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=12))
    axes.set_ylim(bottom=0)

    # A série estimada encabeça a legenda; a faixa de incerteza é acessório dela e
    # vai por último, na ordem em que o leitor procura.
    handles, labels = axes.get_legend_handles_labels()
    order = sorted(range(len(labels)), key=lambda index: "Incerteza" in labels[index])
    legend = axes.legend(
        [handles[index] for index in order], [labels[index] for index in order],
        loc="upper left", bbox_to_anchor=(0, -0.16), ncol=2,
        frameon=False, fontsize=9,
    )
    for text in legend.get_texts():
        text.set_color(_INK_MUTED)

    mask = points[0]
    figure.text(
        0.01, 0.015,
        f"Resolução do produto: {mask.raster_resolution_m:g} m · "
        f"Máscara de pastagem: {mask.pasture_mask_source}, "
        f"{mask.effective_mask_resolution_m:g} m"
        + (f", referência {mask.pasture_mask_reference_year}" if mask.pasture_mask_reference_year else "")
        + f" · Versão: {mask.model_version}",
        fontsize=7.5, color=_INK_MUTED,
    )

    figure.tight_layout(rect=(0, 0.08, 1, 1))

    buffer = BytesIO()
    figure.savefig(buffer, format="png", facecolor="white", bbox_inches="tight")
    plt.close(figure)
    buffer.seek(0)

    return PIL.Image.open(buffer)


def series_table(estimates: Sequence[BiomassEstimate]) -> List[tuple]:
    """
    Série como linhas de tabela — a alternativa textual ao gráfico.

    Args:
        estimates (Sequence[BiomassEstimate]): Estimativas anuais.

    Returns:
        List[tuple]: Linhas (ano, valor, intervalo, total), com cabeçalho na primeira.
    """
    unit = estimates[0].unit_label if estimates else "t MS/ha/ano"

    rows: List[tuple] = [("Ano", f"Valor ({unit})", "Intervalo", "Total (t MS)")]

    for item in sorted(estimates, key=lambda entry: entry.period_start):
        if item.value_per_ha is None:
            rows.append((str(item.period_start.year), "indisponível", "-", "-"))
            continue

        interval = (
            "-" if item.lower_bound_per_ha is None or item.upper_bound_per_ha is None
            else f"{item.lower_bound_per_ha:.1f} a {item.upper_bound_per_ha:.1f}"
        )
        total = "-" if item.total_value is None else f"{item.total_value:.1f}"
        rows.append((str(item.period_start.year), f"{item.value_per_ha:.2f}", interval, total))

    return rows
