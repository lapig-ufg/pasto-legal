"""
Panorama climático (precipitação e temperatura) via Open-Meteo, para uso em
relatórios/boletins — versão "resumo estruturado" das mesmas chamadas usadas
pelas tools de previsão em `app/tools/weather_tools.py` (que devolvem texto
pronto pra LLM; aqui devolvemos dados brutos pra montar tabelas no PDF).
"""
import datetime
from typing import List, Optional, Tuple

import numpy as np
import openmeteo_requests
import pandas as pd
import requests_cache
from retry_requests import retry


# Backend em memória, de propósito — não em SQLite. Duas travas reais e
# distintas já apareceram aqui com backend em disco: (1) colisão com o
# `.cache` de `app/tools/weather_tools.py`, que é importado no mesmo processo
# (corrigido antes com um nome de arquivo isolado); (2) mesmo com nome
# isolado, chamadas repetidas pela MESMA `CachedSession` dentro de um
# processo longo (ex.: suíte de testes) voltaram a travar sem nenhum
# progresso, mesmo com timeout de rede configurado — cada chamada isolada
# funciona rápido, então o travamento é do SQLite (lock), não da rede. Cache
# em memória evita essa classe inteira de problema: sem arquivo, sem lock,
# sem risco de duas sessões (ou chamadas sucessivas da mesma sessão)
# disputando o mesmo `.sqlite`. Custo aceito: o cache não sobrevive a um
# restart do processo — previsão do tempo não precisa disso.
cache_session = requests_cache.CachedSession('climate_outlook', backend="memory", expire_after=3600)
retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
openmeteo = openmeteo_requests.Client(session=retry_session)

SEASONAL_URL = "https://seasonal-api.open-meteo.com/v1/seasonal"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# `requests`/`openmeteo_requests` não aplicam nenhum timeout por padrão — uma
# resposta que nunca chega (rede instável, servidor não responde) trava o
# processo INDEFINIDAMENTE, não só por alguns segundos. Visto na prática: um
# teste real travou 20+ minutos sem nenhum progresso até eu adicionar isto.
_REQUEST_TIMEOUT_S = 30


def estimate_monthly_precipitation_outlook(
    latitude: float, longitude: float, months: int = 3
) -> List[Tuple[datetime.date, Optional[float]]]:
    """
    Previsão sazonal de precipitação média mensal (mm) para os próximos `months` meses.

    Returns:
        List[Tuple[date, Optional[float]]]: (primeiro dia do mês, precipitação média mm).
        O valor vem None quando a API não tem previsão pro mês (NaN) — nunca
        convertido silenciosamente pra 0.0, que pareceria "previsão de zero
        chuva" em vez de "sem dado disponível".
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "monthly": "precipitation_mean",
        "forecast_days": months * 31,
    }
    responses = openmeteo.weather_api(SEASONAL_URL, params=params, timeout=_REQUEST_TIMEOUT_S)
    response = responses[0]

    monthly = response.Monthly()
    precipitation_mean = monthly.Variables(0).ValuesAsNumpy()
    dates = pd.date_range(
        start=f"{monthly.Year()}-{monthly.Month()}-01",
        periods=monthly.Count(),
        freq="MS",
        inclusive="left",
    )

    return [
        (date.date(), float(value) if value == value else None)
        for date, value in zip(dates, precipitation_mean)
    ]


def _round_or_none(value: float) -> Optional[float]:
    """`nan` (ex.: `np.nanmean` de um array 100% NaN) nunca vira número — vira None."""
    return round(float(value), 1) if value == value else None


def estimate_temperature_outlook(latitude: float, longitude: float, days: int = 7) -> Optional[dict]:
    """
    Resumo da previsão de temperatura (°C) para os próximos `days` dias.

    Returns:
        Optional[dict]: {"days", "avg_max_c", "avg_min_c", "max_c", "min_c"},
        ou None se a API não devolveu nenhum dia com dado válido — nunca "nan°C".
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": ["temperature_2m_max", "temperature_2m_min"],
        "forecast_days": days,
    }
    responses = openmeteo.weather_api(FORECAST_URL, params=params, timeout=_REQUEST_TIMEOUT_S)
    response = responses[0]

    daily = response.Daily()
    temp_max = daily.Variables(0).ValuesAsNumpy()
    temp_min = daily.Variables(1).ValuesAsNumpy()

    avg_max_c = _round_or_none(np.nanmean(temp_max)) if len(temp_max) else None
    avg_min_c = _round_or_none(np.nanmean(temp_min)) if len(temp_min) else None
    if avg_max_c is None or avg_min_c is None:
        return None

    return {
        "days": days,
        "avg_max_c": avg_max_c,
        "avg_min_c": avg_min_c,
        "max_c": _round_or_none(np.nanmax(temp_max)),
        "min_c": _round_or_none(np.nanmin(temp_min)),
    }
