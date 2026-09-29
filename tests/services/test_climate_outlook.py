"""
Teste de `_round_or_none` (`app/services/geospatial/climate_outlook.py`) —
regressão do bug em que `nan` (dia/mês sem previsão da API) virava um número
"real" (`0.0 mm` ou `nan°C`) em vez de `None`, o que pareceria dado genuíno
("previsão de zero chuva") quando na verdade é "sem dado disponível".

    .venv/bin/python -m pytest tests/services/test_climate_outlook.py -v
"""
import math

from app.services.geospatial.climate_outlook import _round_or_none


def test_round_or_none_rounds_real_values():
    assert _round_or_none(31.234) == 31.2


def test_round_or_none_returns_none_for_nan():
    assert _round_or_none(math.nan) is None
