import datetime
from datetime import date
from typing import List, NamedTuple, Optional, Tuple

from semente.logging import log_warning
from reportlab.platypus import Flowable

from domain.schemas.feature import Feature
from domain.schemas.property_stats import (
    AgeData,
    AgeStats,
    BiomassStats,
    LULCData,
    LULCStats,
    PastureStats,
    PropertyStats,
    SoilStats,
    TopographicStats,
    Value,
    VigorData,
    VigorStats,
)
from domain.services import pdf_scripts as pdf


_SEASON_ONSET_TRANSLATIONS = {
    "The rainy season has already begun for this location.": "A estação chuvosa já começou nesta localização.",
    "The dry season is currently underway.": "A estação seca já está em curso.",
    "The forecast horizon does not currently extend far enough to determine the end date consistently.":
        "O horizonte de previsão ainda não é longo o suficiente para determinar essa data com segurança.",
}


def _format_season_onset(value: Optional[str]) -> Optional[str]:
    """Traduz as mensagens fixas de `season_forecast.py` (em inglês) e formata datas ISO em dd/mm/aaaa."""
    if not value:
        return None
    if value in _SEASON_ONSET_TRANSLATIONS:
        return _SEASON_ONSET_TRANSLATIONS[value]
    try:
        return datetime.date.fromisoformat(value).strftime("%d/%m/%Y")
    except ValueError:
        return value


class PropertyScore(NamedTuple):
    stars: int
    rationale: str


_SOIL_TEXTURE_FAVORABLE = {"Argila", "Muito Argiloso", "Médio", "Siltoso"}


def _area_fraction(data, matches) -> Optional[float]:
    """Fração da área total (0-1) dos itens cujo rótulo satisfaz `matches`, ou None se a lista estiver vazia."""
    total = sum(item.amount.value for item in data)
    if total <= 0:
        return None
    return sum(item.amount.value for item in data if matches(item)) / total


def compute_property_score(pasture_stats: Optional[PastureStats], soil_stats: Optional[SoilStats]) -> PropertyScore:
    """
    Nota geral da propriedade, de 3 a 5 estrelas — ferramenta didática pra dar
    uma noção rápida ao produtor, NUNCA um veredito alarmista: o piso é
    sempre 3 estrelas, mesmo quando os indicadores são ruins (problemas reais
    continuam detalhados no texto do diagnóstico, não escondidos aqui).

    Considera, com pesos decrescentes: vigor vegetativo (indicador mais
    direto da saúde atual da pastagem), idade da pastagem (mais jovem tende
    a ser mais produtiva) e textura do solo (classes mais favoráveis à
    retenção de água/nutrientes puxam a nota pra cima).
    """
    score = 3.0
    notes: List[str] = []

    if pasture_stats and pasture_stats.vigor_stats and pasture_stats.vigor_stats.data:
        data = pasture_stats.vigor_stats.data
        pct_alto = _area_fraction(data, lambda item: item.vigor.startswith("Alto")) or 0.0
        pct_baixo = _area_fraction(data, lambda item: item.vigor.startswith("Baixo")) or 0.0
        score += pct_alto * 1.5 - pct_baixo * 1.2
        notes.append(f"{pct_alto:.0%} da área de pastagem com vigor alto e {pct_baixo:.0%} com vigor baixo")

    if pasture_stats and pasture_stats.age_stats and pasture_stats.age_stats.data:
        data = pasture_stats.age_stats.data
        pct_jovem = _area_fraction(data, lambda item: item.age in ("1-10", "10-20"))
        if pct_jovem is not None:
            score += pct_jovem * 0.5
            notes.append(f"{pct_jovem:.0%} da pastagem com até 20 anos")

    if soil_stats and soil_stats.data:
        data = soil_stats.data
        pct_favoravel = _area_fraction(data, lambda item: item.soil_class in _SOIL_TEXTURE_FAVORABLE)
        if pct_favoravel is not None:
            score += (pct_favoravel - 0.5) * 0.4
            notes.append(f"{pct_favoravel:.0%} da área com textura de solo favorável ao manejo")

    # Arredondamento "meio pra cima" (não o "half to even" do round() nativo) —
    # mais intuitivo pra uma nota (4.5 vira 5, não 4).
    stars = max(3, min(5, int(score + 0.5)))
    rationale = "; ".join(notes) if notes else "dados insuficientes para uma análise detalhada da nota"
    return PropertyScore(stars=stars, rationale=rationale)


def build_placeholder_property_stats(car_code: str) -> PropertyStats:
    """Monta um PropertyStats com dados de exemplo (placeholder), no formato real esperado pela issue #126."""
    current_year = date.today().year

    pasture_stats = PastureStats(
        biomass_stats=BiomassStats(observation_year=current_year, period="anual", amount=Value(value=14.8, unity="t/ha")),
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


def _municipio_uf(rural_property: Feature) -> str:
    """Monta 'Município/UF' (ex.: 'Corrego do Ouro/GO') a partir da região e do CAR."""
    municipio = rural_property.region
    car_code = rural_property.get_metadata("car_code")
    uf = car_code[:2] if car_code and len(car_code) >= 2 else None

    if municipio and uf:
        return f"{municipio}/{uf}"
    return municipio or ""


def _rows_with_percentage(pairs: List[Tuple[str, Value]]) -> List[List[str]]:
    """Linhas [rótulo, área, percentual] — percentual relativo à soma das próprias linhas da tabela."""
    total = sum(value.value for _, value in pairs)
    rows = []
    for label, value in pairs:
        pct = (value.value / total * 100) if total else 0.0
        rows.append([label, str(value), f"{pct:.0f}%"])
    return rows


def generate_boletim_diagnostic(pasture_stats: Optional[PastureStats], soil_stats: Optional[SoilStats]) -> Optional[str]:
    """
    Gera o texto da seção "Diagnóstico do Pasto Legal" via LLM, interpretando os
    dados já coletados da propriedade (não recalcula nada — só resume/interpreta).

    Retorna None (a seção some do boletim) se não houver dado nenhum pra
    interpretar, ou se a chamada ao modelo falhar — o boletim nunca deixa de
    ser gerado por causa do diagnóstico.
    """
    if pasture_stats is None:
        return None

    score = compute_property_score(pasture_stats, soil_stats)

    summary_parts = [str(pasture_stats)]
    if soil_stats:
        summary_parts.append(str(soil_stats))
    summary_parts.append(
        f"Nota geral já calculada para esta propriedade: {score.stars} de 5 estrelas. "
        f"Motivos considerados no cálculo: {score.rationale}."
    )
    summary = "\n\n".join(summary_parts)

    # Import local pelo mesmo motivo do agente acima.
    from domain.services.response_sanitizer import strip_leaked_reasoning

    try:
        # Imports locais para evitar ciclo: domain.agent importa analysis_tools,
        # que importa este módulo.
        from semente.backends.base import AgentInput

        from domain.agents.boletim_diagnostic_agent import boletim_diagnostic_agent

        turn = boletim_diagnostic_agent.run(AgentInput(text=summary))
        content = turn.content if turn else None
        content = strip_leaked_reasoning(content) if isinstance(content, str) else content
        return content.strip() if isinstance(content, str) and content.strip() else None
    except Exception as exc:
        log_warning(f"generate_boletim_diagnostic: falha ao gerar diagnóstico: {exc}")
        return None


def _build_age_blocks(pasture_stats: Optional[PastureStats]) -> List[Flowable]:
    blocks: List[Flowable] = [pdf.subsection_title("Idade da Pastagem")]
    if pasture_stats and pasture_stats.age_stats and pasture_stats.age_stats.data:
        blocks.append(pdf.placeholder_note(f"Ano de referência: {pasture_stats.age_stats.observation_year}."))
        blocks.append(pdf.data_table(
            ["Faixa de Idade", "Área", "Percentual"],
            _rows_with_percentage([(item.age, item.amount) for item in pasture_stats.age_stats.data]),
        ))
    else:
        blocks.append(pdf.placeholder_note("Dados de idade indisponíveis."))
    return blocks


def _build_vigor_blocks(
    pasture_stats: Optional[PastureStats], vigor_map_image_bytes: Optional[bytes]
) -> List[Flowable]:
    if vigor_map_image_bytes:
        blocks: List[Flowable] = [pdf.subsection_header(
            "Vigor da Pastagem",
            pdf.single_image(vigor_map_image_bytes, caption="Mapa de vigor", image_height_mm=90),
        )]
        blocks.append(pdf.spacer(2))
    else:
        blocks = [pdf.subsection_title("Vigor da Pastagem")]

    if pasture_stats and pasture_stats.vigor_stats and pasture_stats.vigor_stats.data:
        blocks.append(pdf.placeholder_note(f"Ano de referência: {pasture_stats.vigor_stats.observation_year}."))
        blocks.append(pdf.data_table(
            ["Nível de Vigor", "Área", "Percentual"],
            _rows_with_percentage([(item.vigor, item.amount) for item in pasture_stats.vigor_stats.data]),
        ))
    else:
        blocks.append(pdf.placeholder_note("Dados de vigor indisponíveis."))

    return blocks


def _build_lulc_blocks(pasture_stats: Optional[PastureStats]) -> List[Flowable]:
    blocks: List[Flowable] = [pdf.subsection_title("Uso e Cobertura do Solo (LULC)")]
    if pasture_stats and pasture_stats.lulc_stats and pasture_stats.lulc_stats.data:
        blocks.append(pdf.placeholder_note(f"Ano de referência: {pasture_stats.lulc_stats.observation_year}."))
        blocks.append(pdf.data_table(
            ["Classe", "Área", "Percentual"],
            _rows_with_percentage([(item.lulc_class, item.amount) for item in pasture_stats.lulc_stats.data]),
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
        ("Estimativa de biomassa", f"{biomass.amount.value:.1f} {biomass.amount.unity}"),
    ])]


def _build_soil_blocks(
    soil_stats: Optional[SoilStats], soil_map_image_bytes: Optional[bytes]
) -> List[Flowable]:
    blocks: List[Flowable] = []

    if soil_map_image_bytes:
        blocks.append(pdf.single_image(soil_map_image_bytes, caption="Textura do solo", image_height_mm=90))
        blocks.append(pdf.spacer(2))

    if soil_stats and soil_stats.data:
        blocks.append(pdf.placeholder_note(f"Ano de referência: {soil_stats.observation_year}."))
        blocks.append(pdf.data_table(
            ["Classe Textural", "Área", "Percentual"],
            _rows_with_percentage([(item.soil_class, item.amount) for item in soil_stats.data]),
        ))
    else:
        blocks.append(pdf.placeholder_note("Dados de textura do solo indisponíveis."))

    return blocks


def _build_biomass_history_blocks(
    image_bytes: Optional[bytes],
    history_start_year: Optional[int],
    history_end_year: Optional[int],
    latest_avg_t_ha: Optional[float],
) -> List[Flowable]:
    if not image_bytes:
        return [pdf.placeholder_note("Histórico de biomassa indisponível para esta propriedade.")]

    blocks: List[Flowable] = [
        pdf.single_image(
            image_bytes,
            caption=f"Evolução da biomassa seca média da propriedade ({history_start_year}-{history_end_year})",
        ),
    ]

    if latest_avg_t_ha is not None:
        blocks.append(pdf.spacer(2))
        blocks.append(pdf.key_value_table([
            (f"Média em {history_end_year} (último ano disponível)", f"{latest_avg_t_ha:.2f} t MS/ha/ano"),
        ]))

    return blocks


def _build_topographic_blocks(topographic_stats: Optional[TopographicStats]) -> List[Flowable]:
    if not topographic_stats:
        return [pdf.placeholder_note("Dados topográficos indisponíveis para esta propriedade.")]

    return [pdf.key_value_table([
        ("Altitude média", str(topographic_stats.elevation)),
        ("Declividade média", str(topographic_stats.slope)),
    ])]


def _build_climate_blocks(
    rain_onset: Optional[str],
    dry_onset: Optional[str],
    temperature_outlook: Optional[dict],
    precipitation_outlook: Optional[List[Tuple[datetime.date, Optional[float]]]],
) -> List[Flowable]:
    summary_rows: List[Tuple[str, str]] = []

    rain_onset_text = _format_season_onset(rain_onset)
    if rain_onset_text:
        summary_rows.append(("Início previsto da estação chuvosa", rain_onset_text))

    dry_onset_text = _format_season_onset(dry_onset)
    if dry_onset_text:
        summary_rows.append(("Início previsto da estação seca", dry_onset_text))

    if temperature_outlook:
        summary_rows.append((
            f"Temperatura prevista (próximos {temperature_outlook['days']} dias)",
            f"média entre {temperature_outlook['avg_min_c']:.1f}°C e {temperature_outlook['avg_max_c']:.1f}°C",
        ))

    blocks: List[Flowable] = []
    if summary_rows:
        blocks.append(pdf.key_value_table(summary_rows))

    if precipitation_outlook:
        if blocks:
            blocks.append(pdf.spacer(2))
        blocks.append(pdf.data_table(
            ["Mês", "Precipitação média prevista"],
            [
                [month.strftime("%m/%Y"), f"{mm:.1f} mm" if mm is not None else "sem previsão"]
                for month, mm in precipitation_outlook
            ],
        ))

    if not blocks:
        blocks.append(pdf.placeholder_note("Panorama climático indisponível no momento."))

    return blocks


def build_boletim_story(
    rural_property: Feature,
    property_stats: PropertyStats,
    location_image_bytes: bytes,
    pasture_map_image_bytes: bytes,
    vigor_map_image_bytes: Optional[bytes] = None,
    biomass_map_image_bytes: Optional[bytes] = None,
    soil_map_image_bytes: Optional[bytes] = None,
    soil_stats: Optional[SoilStats] = None,
    diagnostic_text: Optional[str] = None,
    biomass_history_image_bytes: Optional[bytes] = None,
    biomass_history_start_year: Optional[int] = None,
    biomass_history_end_year: Optional[int] = None,
    biomass_history_latest_avg_t_ha: Optional[float] = None,
    topographic_stats: Optional[TopographicStats] = None,
    rain_onset: Optional[str] = None,
    dry_onset: Optional[str] = None,
    temperature_outlook: Optional[dict] = None,
    precipitation_outlook: Optional[List[Tuple[datetime.date, Optional[float]]]] = None,
    emission_date: Optional[date] = None,
) -> List[Flowable]:
    """
    Monta a lista de flowables do boletim: diagnóstico executivo (quando o
    texto LLM está disponível), localização da propriedade (seção 1, imagem
    de satélite), pastagem (idade/vigor/LULC), biomassa, tipos de solo,
    histórico de biomassa, topografia e panorama climático — cada seção
    temática espacial mostra o mapa temático sozinho, em largura cheia (a
    imagem de satélite "crua" já tem seção própria no início, não repete
    lado a lado em cada seção).
    """
    emission_date = emission_date or date.today()
    farm_name = rural_property.name or rural_property.id or "Propriedade"
    municipio_uf = _municipio_uf(rural_property)
    pasture_stats_list = property_stats.list_pasture_stats or []
    latest_pasture_stats = pasture_stats_list[-1] if pasture_stats_list else None

    subtitle = f"Data de Emissão: {emission_date.strftime('%d/%m/%Y')} · ID: {rural_property.id}"
    if municipio_uf:
        subtitle = f"{municipio_uf} · {subtitle}"

    story: List[Flowable] = [
        pdf.masthead(farm_name, subtitle),
        pdf.spacer(4),
        pdf.warning_box(
            "A biomassa é calculada para o mês/ano atual. Idade, vigor e uso do solo (LULC) "
            "refletem o ano mais recente disponível no MapBiomas, podendo estar até um ano defasados."
        ),
        pdf.spacer(4),
    ]

    # Diagnóstico do Pasto Legal (texto do LLM + nota em estrelas) — a visão
    # geral da propriedade NÃO vive aqui: tem seção numerada própria (a 1.),
    # então a imagem de localização nunca conflita com o diagnóstico vazio
    # (o agente LLM está desabilitado temporariamente).
    if diagnostic_text:
        score = compute_property_score(latest_pasture_stats, soil_stats)
        story.append(pdf.section_header(
            "Diagnóstico do Pasto Legal",
            pdf.score_row(score.stars, f"Nota Geral da Propriedade: {score.stars} de 5"),
        ))
        story.append(pdf.spacer(3))
        story.append(pdf.body_text(diagnostic_text))
        story.append(pdf.spacer(4))

    if location_image_bytes:
        story.append(pdf.section_header(
            "1. Localização da Propriedade",
            pdf.single_image(location_image_bytes, caption="Imagem de satélite com o limite do CAR", image_height_mm=90),
        ))
        story.append(pdf.spacer(4))

    story.append(pdf.section_header(
        "2. Dados de Pastagem",
        pdf.single_image(pasture_map_image_bytes, caption="Classificação de pastagem", image_height_mm=90),
    ))
    story.append(pdf.spacer(3))
    story.extend(_build_age_blocks(latest_pasture_stats))
    story.extend(_build_vigor_blocks(latest_pasture_stats, vigor_map_image_bytes))
    story.extend(_build_lulc_blocks(latest_pasture_stats))

    story.append(pdf.spacer(4))

    if biomass_map_image_bytes:
        story.append(pdf.section_header(
            "3. Análise de Biomassa",
            pdf.single_image(biomass_map_image_bytes, caption="Mapa de biomassa", image_height_mm=90),
        ))
        story.append(pdf.spacer(3))
    else:
        story.append(pdf.section_header("3. Análise de Biomassa"))
        story.append(pdf.spacer(3))
    story.extend(_build_biomass_blocks(latest_pasture_stats))

    if soil_map_image_bytes or soil_stats:
        story.append(pdf.spacer(4))
        soil_blocks = _build_soil_blocks(soil_stats, soil_map_image_bytes)
        story.append(pdf.section_header("4. Tipos de Solo", soil_blocks[0]))
        story.extend(soil_blocks[1:])

    story.append(pdf.spacer(4))
    history_blocks = _build_biomass_history_blocks(
        biomass_history_image_bytes, biomass_history_start_year, biomass_history_end_year, biomass_history_latest_avg_t_ha,
    )
    story.append(pdf.section_header("5. Histórico de Biomassa", history_blocks[0]))
    story.extend(history_blocks[1:])

    story.append(pdf.spacer(4))
    topo_blocks = _build_topographic_blocks(topographic_stats)
    story.append(pdf.section_header("6. Dados Topográficos", topo_blocks[0]))
    story.extend(topo_blocks[1:])

    story.append(pdf.spacer(4))
    climate_blocks = _build_climate_blocks(rain_onset, dry_onset, temperature_outlook, precipitation_outlook)
    story.append(pdf.section_header("7. Panorama Climático", climate_blocks[0]))
    story.extend(climate_blocks[1:])

    return story


def build_boletim_chat_summary(rural_property: Feature, pasture_stats: PastureStats) -> str:
    """Monta a mensagem de chat que acompanha o PDF, pronta em Python (sem depender da LLM
    compor um resumo criativo) — reduz o boletim a uma única chamada de tool cujo resultado
    a LLM só precisa repassar ao usuário.
    """
    farm_name = rural_property.name or rural_property.id or "Propriedade"

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
            f"*{biomass.amount.value:.1f} {biomass.amount.unity}*."
        )

    return (
        f"O boletim em PDF da *{farm_name}* foi gerado com sucesso!{year_text} A propriedade tem "
        f"{area_text}.{biomass_text} O documento traz um diagnóstico geral, os mapas de pastagem, "
        "vigor, biomassa e solo, além do histórico de biomassa, dados topográficos e panorama "
        "climático — pronto para compartilhar com seu agrônomo ou parceiros."
    )