"""
Panorama climático (precipitação e temperatura) via Open-Meteo, para uso em
relatórios/boletins — versão "resumo estruturado" das mesmas chamadas usadas
pelas tools de previsão em `app/tools/weather_tools.py` (que devolvem texto
pronto pra LLM; aqui devolvemos dados brutos pra montar tabelas no PDF).
"""
import datetime
from typing import List, Tuple

import numpy as np
import openmeteo_requests
import pandas as pd
import requests_cache
from retry_requests import retry


# Nome de cache DISTINTO do usado em `app/tools/weather_tools.py` (`.cache`) —
# ambos os módulos são importados no mesmo processo (single_agent.py importa
# weather_tools.py na raiz), e duas `CachedSession` de requests_cache abertas
# ao mesmo tempo sobre o MESMO arquivo .sqlite podem travar o processo inteiro
# esperando um lock do SQLite (visto na prática: teste real travou 20+ minutos
# sem nenhum progresso, preso num fd apontando pro `.cache.sqlite` compartilhado).
cache_session = requests_cache.CachedSession('tmp/.cache_climate_outlook', expire_after=3600)
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
) -> List[Tuple[datetime.date, float]]:
    """
    Previsão sazonal de precipitação média mensal (mm) para os próximos `months` meses.

    Returns:
        List[Tuple[date, float]]: (primeiro dia do mês, precipitação média mm).
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
        (date.date(), float(value) if value == value else 0.0)
        for date, value in zip(dates, precipitation_mean)
    ]


def estimate_temperature_outlook(latitude: float, longitude: float, days: int = 7) -> dict:
    """
    Resumo da previsão de temperatura (°C) para os próximos `days` dias.

    Returns:
        dict: {"days", "avg_max_c", "avg_min_c", "max_c", "min_c"}.
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

    return {
        "days": days,
        "avg_max_c": round(float(np.nanmean(temp_max)), 1),
        "avg_min_c": round(float(np.nanmean(temp_min)), 1),
        "max_c": round(float(np.nanmax(temp_max)), 1),
        "min_c": round(float(np.nanmin(temp_min)), 1),
    }
