"""Testes da regra de chuva disponível por mês (issue #140).

`_available_rain` decide quanto da chuva de um mês ainda pode ser levado em
conta na busca por limiar. É a única parte da ferramenta com regra de
negócio — o resto é chamada de API — e é pura, então roda sem rede.

Roda com:  PYTHONPATH=. .venv/bin/pytest tests/tools/test_rain_threshold.py -v
"""

import datetime

import pytest

from domain.tools.weather_tools import _available_rain


HOJE = datetime.date(2026, 10, 20)
OUTUBRO = datetime.date(2026, 10, 1)
NOVEMBRO = datetime.date(2026, 11, 1)


def test_mes_futuro_usa_a_previsao_inteira():
    """Novembro ainda está todo pela frente."""
    disponivel, nota = _available_rain(NOVEMBRO, 189.2, HOJE, already_fallen=81.8)

    assert disponivel == 189.2
    assert nota == ""


def test_mes_corrente_desconta_o_que_ja_caiu():
    """O caso que a issue não previa: outubro mostra 177, mas restam 95."""
    disponivel, nota = _available_rain(OUTUBRO, 177.0, HOJE, already_fallen=81.8)

    assert disponivel == pytest.approx(95.2)
    assert "177 mm expected" in nota
    assert "82 mm already fallen" in nota


def test_mes_corrente_sem_medicao_usa_o_total():
    """Archive indisponível: perde precisão, mas a ferramenta responde."""
    disponivel, nota = _available_rain(OUTUBRO, 177.0, HOJE, already_fallen=None)

    assert disponivel == 177.0
    assert nota == ""


def test_choveu_mais_que_o_previsto_nao_fica_negativo():
    """Acontece: o acumulado passa a previsão do modelo."""
    disponivel, _ = _available_rain(OUTUBRO, 177.0, HOJE, already_fallen=200.0)

    assert disponivel == 0.0


def test_mesmo_mes_de_outro_ano_nao_e_o_corrente():
    """Outubro/2027 está no horizonte de 7 meses a partir de um verão."""
    outubro_que_vem = datetime.date(2027, 10, 1)
    disponivel, nota = _available_rain(outubro_que_vem, 177.0, HOJE, already_fallen=81.8)

    assert disponivel == 177.0
    assert nota == ""


def test_primeiro_dia_do_mes_sem_nada_caido():
    """Dia 1: o mês inteiro está pela frente."""
    primeiro = datetime.date(2026, 10, 1)
    disponivel, nota = _available_rain(OUTUBRO, 177.0, primeiro, already_fallen=0.0)

    assert disponivel == 177.0
    assert "0 mm already fallen" in nota
