import datetime

import numpy as np
import openmeteo_requests
import requests_cache
from openmeteo_sdk.Variable import Variable
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
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"


def _daily_dates(daily) -> list[datetime.date]:
    """Generates the list of dates (UTC) covered by the daily response."""
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
            f"Property with CAR {', '.join(car_codes)} not found in the system."
        )
    return RuralProperty.model_validate(selected_property)


@tool(tool_hooks=[validate_selected_property_hook])
def get_precipitation_forecast(
    run_context: RunContext, car_codes: list[str], forecast_days: int = 36
) -> ToolResult:
    """
    Retrieves the daily precipitation forecast (mm) for the rural property
    from an ensemble of weather models via the Open-Meteo API, returning the
    most pessimistic (highest volume) and most optimistic (lowest volume)
    values among the ensemble members.

    Use this tool when the user asks about:
    - Rain or precipitation forecast.
    - Expected rainfall volume for the coming days.
    - Pessimistic/optimistic rain scenario.
    - Flood or drought risk within the forecast horizon.

    params:
        car_codes (list[str]): List of CAR codes for the property.
        forecast_days (int): Number of forecast days, between 1 and 36.
            Defaults to 36.

    Return:
        ToolResult: Text with the daily precipitation forecast
        (date + pessimistic mm / optimistic mm).
    """
    try:
        if not 1 <= forecast_days <= 36:
            raise ValueError(
                f"forecast_days must be between 1 and 36 (received: {forecast_days})."
            )

        property_obj = _resolve_property(run_context, car_codes)
        latitude, longitude = property_obj.get_centroid()

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": "precipitation_sum",
            "timezone": "America/Sao_Paulo",
            "forecast_days": forecast_days,
        }
        responses = openmeteo.weather_api(ENSEMBLE_URL, params=params)
        response = responses[0]

        daily = response.Daily()
        daily_variables = [
            daily.Variables(i) for i in range(daily.VariablesLength())
        ]
        precipitation_members = [
            v.ValuesAsNumpy()
            for v in daily_variables
            if v.Variable() == Variable.precipitation_sum
        ]

        if not precipitation_members:
            raise ValueError(
                "No ensemble member with precipitation_sum was returned."
            )

        members_array = np.ma.array(precipitation_members, mask=np.isnan(precipitation_members))
        pessimist = members_array.max(axis=0)
        optimist = members_array.min(axis=0)

        dates = _daily_dates(daily)

        lines = []
        for date, pess, opt in zip(dates, pessimist, optimist):
            pess_val = float(pess) if pess is not np.ma.masked else 0.0
            opt_val = float(opt) if opt is not np.ma.masked else 0.0
            lines.append(
                f"{date.isoformat()}: "
                f"pessimistic {pess_val:.1f} mm / optimistic {opt_val:.1f} mm"
            )

        content = (
            f"Precipitation forecast (ensemble) for property "
            f"{property_obj.car_code} ({latitude:.4f}, {longitude:.4f}):\n"
            + "\n".join(lines)
        )

        return ToolResult(content=content)

    except Exception as e:
        log_error(f"ERROR: {e}")
        return ToolResult(content=str(e))


@tool(tool_hooks=[validate_selected_property_hook])
def get_temperature_forecast(
    run_context: RunContext, car_codes: list[str], forecast_days: int = 16
) -> ToolResult:
    """
    Retrieves the daily maximum and minimum temperature forecast (°C) for the
    rural property using the Open-Meteo API.

    Use this tool when the user asks about:
    - Temperature forecast (max and min).
    - Heat or cold waves in the coming days.
    - Thermal variation on the property.

    params:
        car_codes (list[str]): List of CAR codes for the property.
        forecast_days (int): Number of forecast days, between 1 and 16.
            Defaults to 16.

    Return:
        ToolResult: Text with the daily temperature forecast (date, max, min).
    """
    try:
        if not 1 <= forecast_days <= 16:
            raise ValueError(
                f"forecast_days must be between 1 and 16 (received: {forecast_days})."
            )

        property_obj = _resolve_property(run_context, car_codes)
        latitude, longitude = property_obj.get_centroid()

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": ["temperature_2m_max", "temperature_2m_min"],
            "forecast_days": forecast_days,
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
                f"{date.isoformat()}: max {t_max_val:.1f} °C / min {t_min_val:.1f} °C"
            )

        content = (
            f"Temperature forecast for property "
            f"{property_obj.car_code} ({latitude:.4f}, {longitude:.4f}):\n"
            + "\n".join(lines)
        )

        return ToolResult(content=content)

    except Exception as e:
        log_error(f"ERROR: {e}")
        return ToolResult(content=str(e))