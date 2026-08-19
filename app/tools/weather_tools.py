import datetime

import openmeteo_requests
import requests_cache
from retry_requests import retry

from agno.tools import tool
from agno.tools.function import ToolResult
from agno.run import RunContext
from agno.utils.log import log_error

from app.hooks.tool_hooks import validate_selected_property_hook
from app.schemas.rural_property import RuralProperty


cache_session = requests_cache.CachedSession('.cache', expire_after=3600)
retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
openmeteo = openmeteo_requests.Client(session=retry_session)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def _property_centroid(coords) -> tuple[float, float]:
    """
    Calcula o centroide (área-ponderado) de um polígono de propriedade rural.

    Args:
        coords: Estrutura GeoJSON das coordenadas da propriedade
                (lista de polígonos, cada polígono como lista de anéis,
                cada anel como lista de [lon, lat]).

    Returns:
        Tupla (latitude, longitude) do centroide.
    """
    total_area = 0.0
    weighted_lat = 0.0
    weighted_lon = 0.0

    for polygon in coords:
        for ring in polygon:
            n = len(ring)
            signed_area = 0.0
            for i in range(n):
                lon1, lat1 = ring[i]
                lon2, lat2 = ring[(i + 1) % n]
                signed_area += (lon1 * lat2 - lon2 * lat1)
            signed_area /= 2.0

            if signed_area == 0.0:
                continue

            cx = 0.0
            cy = 0.0
            for i in range(n):
                lon1, lat1 = ring[i]
                lon2, lat2 = ring[(i + 1) % n]
                cross = (lon1 * lat2 - lon2 * lat1)
                cx += (lon1 + lon2) * cross
                cy += (lat1 + lat2) * cross

            cx /= (6.0 * signed_area)
            cy /= (6.0 * signed_area)

            ring_area = abs(signed_area)
            weighted_lat += cy * ring_area
            weighted_lon += cx * ring_area
            total_area += ring_area

    if total_area == 0.0:
        pts = []
        for polygon in coords:
            for ring in polygon:
                pts.extend(ring)
        if not pts:
            raise ValueError("Coordenadas da propriedade estão vazias.")
        lat = sum(p[1] for p in pts) / len(pts)
        lon = sum(p[0] for p in pts) / len(pts)
        return lat, lon

    return weighted_lat / total_area, weighted_lon / total_area


def _daily_dates(daily) -> list[datetime.date]:
    """Gera a lista de datas (UTC) cobertas pela resposta diária."""
    start = datetime.datetime.utcfromtimestamp(daily.Time()).date()
    end = datetime.datetime.utcfromtimestamp(daily.TimeEnd()).date()
    interval = datetime.timedelta(seconds=daily.Interval())
    dates = []
    current = start
    while current < end:
        dates.append(current)
        current += interval
    return dates


def _resolve_property(run_context: RunContext, car_codes: list[str]) -> RuralProperty:
    all_properties = run_context.session_state["all_properties"]
    selected_property = next(
        (prop for prop in all_properties if prop["car_code"] == ', '.join(car_codes)),
        None,
    )
    if selected_property is None:
        raise ValueError(
            f"Propriedade com CAR {', '.join(car_codes)} não encontrada no sistema."
        )
    return RuralProperty.model_validate(selected_property)


@tool(tool_hooks=[validate_selected_property_hook])
def get_precipitation_forecast(run_context: RunContext, car_codes: list[str]) -> ToolResult:
    """
    Recupera a previsão diária de precipitação (mm) para a propriedade rural,
    usando a API Open-Meteo.

    Use esta ferramenta quando o usuário perguntar sobre:
    - Previsão de chuva ou precipitação.
    - Volume de chuva esperado para os próximos dias.
    - Risco de enchente ou seca no horizonte de previsão.

    params:
        car_codes (list[str]): Lista de códigos CAR da propriedade.

    Return:
        ToolResult: Texto com a previsão diária de precipitação (data + mm).
    """
    try:
        property_obj = _resolve_property(run_context, car_codes)
        latitude, longitude = _property_centroid(property_obj.get_coords())

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": ["precipitation_sum"],
        }
        responses = openmeteo.weather_api(FORECAST_URL, params=params)
        response = responses[0]

        daily = response.Daily()
        precipitation_sum = daily.Variables(0).ValuesAsNumpy()
        dates = _daily_dates(daily)

        lines = []
        for date, value in zip(dates, precipitation_sum):
            mm = float(value) if value == value else 0.0
            lines.append(f"{date.isoformat()}: {mm:.1f} mm")

        content = (
            f"Previsão de precipitação para a propriedade "
            f"{property_obj.car_code} ({latitude:.4f}, {longitude:.4f}):\n"
            + "\n".join(lines)
        )

        return ToolResult(content=content)

    except Exception as e:
        log_error(f"ERROR: {e}")
        return ToolResult(content=str(e))


@tool(tool_hooks=[validate_selected_property_hook])
def get_temperature_forecast(run_context: RunContext, car_codes: list[str]) -> ToolResult:
    """
    Recupera a previsão diária de temperatura máxima e mínima (°C) para a
    propriedade rural, usando a API Open-Meteo.

    Use esta ferramenta quando o usuário perguntar sobre:
    - Previsão de temperatura (máxima e mínima).
    - Ondas de calor ou frio nos próximos dias.
    - Variação térmica na propriedade.

    params:
        car_codes (list[str]): Lista de códigos CAR da propriedade.

    Return:
        ToolResult: Texto com a previsão diária de temperatura (data, máxima, mínima).
    """
    try:
        property_obj = _resolve_property(run_context, car_codes)
        latitude, longitude = _property_centroid(property_obj.get_coords())

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": ["temperature_2m_max", "temperature_2m_min"],
        }
        responses = openmeteo.weather_api(FORECAST_URL, params=params)
        response = responses[0]

        daily = response.Daily()
        temp_max = daily.Variables(0).ValuesAsNumpy()
        temp_min = daily.Variables(1).ValuesAsNumpy()
        dates = _daily_dates(daily)

        lines = []
        for date, t_max, t_min in zip(dates, temp_max, temp_min):
            t_max_val = float(t_max) if t_max == t_max else 0.0
            t_min_val = float(t_min) if t_min == t_min else 0.0
            lines.append(
                f"{date.isoformat()}: máx {t_max_val:.1f} °C / mín {t_min_val:.1f} °C"
            )

        content = (
            f"Previsão de temperatura para a propriedade "
            f"{property_obj.car_code} ({latitude:.4f}, {longitude:.4f}):\n"
            + "\n".join(lines)
        )

        return ToolResult(content=content)

    except Exception as e:
        log_error(f"ERROR: {e}")
        return ToolResult(content=str(e))