import datetime

import numpy as np
import openmeteo_requests
import pandas as pd
import requests_cache
from openmeteo_sdk.Variable import Variable
from retry_requests import retry

from agno.tools import tool
from agno.tools.function import ToolResult
from agno.run import RunContext
from agno.utils.log import log_debug, log_warning, log_error

from app.configs.prompts import get_tool_description
from app.schemas.rural_property import RuralProperty
from app.services.geospatial.season_forecast import (
    get_dry_season_onset as _get_dry_season_onset,
    get_rain_onset as _get_rain_onset,
)


cache_session = requests_cache.CachedSession('.cache', expire_after=3600)
retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
openmeteo = openmeteo_requests.Client(session=retry_session)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
SEASONAL_URL = "https://seasonal-api.open-meteo.com/v1/seasonal"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


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


@tool(description=get_tool_description("weather_tools", "get_monthly_precipitation_forecast"))
def get_monthly_precipitation_forecast(
    run_context: RunContext, car_codes: list[str], months: int = 7
) -> ToolResult:
    """
    Retrieves the monthly precipitation forecast (mm) for the rural property.

    params:
        car_codes (list[str]): List of CAR codes for the property.
        months (int): Number of months to forecast, between 1 and 7. Defaults to 7.

    Return:
        ToolResult: Text with the monthly precipitation forecast (date + mean mm).
    """
    try:
        log_debug(f"get_monthly_precipitation_forecast: car_codes={car_codes}, months={months}")
        if not 1 <= months <= 7:
            log_warning(f"months fora do intervalo permitido: {months}")
            raise ValueError(
                f"months must be between 1 and 7 (received: {months})."
            )

        property_obj = _resolve_property(run_context, car_codes)
        latitude, longitude = property_obj.get_centroid()

        forecast_days = months * 31

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "monthly": "precipitation_mean",
            "forecast_days": forecast_days,
        }
        responses = openmeteo.weather_api(SEASONAL_URL, params=params)
        response = responses[0]

        monthly = response.Monthly()
        monthly_precipitation_mean = monthly.Variables(0).ValuesAsNumpy()

        monthly_data = {
            "date": pd.date_range(
                start=f"{monthly.Year()}-{monthly.Month()}-01",
                periods=monthly.Count(),
                freq="MS",
                inclusive="left",
            ),
            "precipitation_mean": monthly_precipitation_mean,
        }
        monthly_dataframe = pd.DataFrame(data=monthly_data)

        lines = []
        for _, row in monthly_dataframe.iterrows():
            mean_val = float(row["precipitation_mean"])
            if mean_val != mean_val:
                mean_val = 0.0
            lines.append(
                f"{row['date'].strftime('%Y-%m-%d')}: mean {mean_val:.1f} mm"
            )

        content = (
            f"Monthly precipitation forecast (seasonal) for property "
            f"{property_obj.car_code} ({latitude:.4f}, {longitude:.4f}):\n"
            + "\n".join(lines)
        )

        log_debug(f"get_monthly_precipitation_forecast: {len(lines)} meses retornados ({property_obj.car_code})")
        return ToolResult(content=content)

    except Exception as e:
        log_error(f"get_monthly_precipitation_forecast: {e}")
        return ToolResult(content=str(e))


@tool(description=get_tool_description("weather_tools", "get_daily_precipitation_forecast"))
def get_daily_precipitation_forecast(
    run_context: RunContext, car_codes: list[str], forecast_days: int = 1
) -> ToolResult:
    """
    Retrieves the precipitation forecast (mm) for a specific target day of the rural property.

    params:
        car_codes (list[str]): List of CAR codes for the property.
        forecast_days (int): Target day to forecast, between 1 and 36. Defaults to 1.

    Return:
        ToolResult: Text with the precipitation forecast for the chosen day.
    """
    try:
        log_debug(f"get_daily_precipitation_forecast: car_codes={car_codes}, forecast_days={forecast_days}")
        if not 1 <= forecast_days <= 36:
            log_warning(f"forecast_days fora do intervalo permitido: {forecast_days}")
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
            if v.Variable() == Variable.precipitation
        ]

        if not precipitation_members:
            raise ValueError(
                "No ensemble member with precipitation was returned."
            )

        members_array = np.array(precipitation_members)
        last_day_values = members_array[:, -1]

        q1 = float(np.nanquantile(last_day_values, 0.25))
        q3 = float(np.nanquantile(last_day_values, 0.75))

        target_date = _daily_dates(daily)[-1].isoformat()

        content = (
            f"Daily precipitation forecast (ensemble quartiles) for property "
            f"{property_obj.car_code} ({latitude:.4f}, {longitude:.4f}) "
            f"on {target_date} (day {forecast_days}):\n"
            f"Q1 (lower): {q1:.1f} mm / Q3 (upper): {q3:.1f} mm"
        )

        log_debug(f"get_daily_precipitation_forecast: Q1={q1:.1f}mm Q3={q3:.1f}mm ({property_obj.car_code})")
        return ToolResult(content=content)

    except Exception as e:
        log_error(f"get_daily_precipitation_forecast: {e}")
        return ToolResult(content=str(e))


@tool(description=get_tool_description("weather_tools", "get_rain_season_onset_forecast"))
def get_rain_season_onset_forecast(
    run_context: RunContext, car_codes: list[str]
) -> ToolResult:
    """
    Predicts the start date of the rainy season for the rural property.

    params:
        car_codes (list[str]): List of CAR codes for the property.

    Return:
        ToolResult: Predicted rain onset date (YYYY-MM-DD), or a message
        indicating the rainy season has already begun / is unavailable.
    """
    try:
        log_debug(f"get_rain_season_onset_forecast: car_codes={car_codes}")
        property_obj = _resolve_property(run_context, car_codes)
        latitude, longitude = property_obj.get_centroid()

        today = datetime.date.today()
        result = _get_rain_onset(latitude, longitude, today)

        content = (
            f"Rain onset forecast for property {property_obj.car_code} "
            f"({latitude:.4f}, {longitude:.4f}): {result}"
        )

        log_debug(f"get_rain_season_onset_forecast: {result} ({property_obj.car_code})")
        return ToolResult(content=content)

    except Exception as e:
        log_error(f"get_rain_season_onset_forecast: {e}")
        return ToolResult(content=str(e))


@tool(description=get_tool_description("weather_tools", "get_dry_season_onset_forecast"))
def get_dry_season_onset_forecast(
    run_context: RunContext, car_codes: list[str]
) -> ToolResult:
    """
    Predicts the start date of the dry season (end of rains) for the rural property.

    params:
        car_codes (list[str]): List of CAR codes for the property.

    Return:
        ToolResult: Predicted dry-season onset date (YYYY-MM-DD), or a
        message indicating the dry season is underway / the forecast
        horizon does not extend far enough.
    """
    try:
        log_debug(f"get_dry_season_onset_forecast: car_codes={car_codes}")
        property_obj = _resolve_property(run_context, car_codes)
        latitude, longitude = property_obj.get_centroid()

        today = datetime.date.today()
        result = _get_dry_season_onset(latitude, longitude, today)

        content = (
            f"Dry season onset forecast for property {property_obj.car_code} "
            f"({latitude:.4f}, {longitude:.4f}): {result}"
        )

        log_debug(f"get_dry_season_onset_forecast: {result} ({property_obj.car_code})")
        return ToolResult(content=content)

    except Exception as e:
        log_error(f"get_dry_season_onset_forecast: {e}")
        return ToolResult(content=str(e))


@tool(description=get_tool_description("weather_tools", "get_temperature_forecast"))
def get_temperature_forecast(
    run_context: RunContext, car_codes: list[str], forecast_days: int = 16
) -> ToolResult:
    """
    Retrieves the daily maximum and minimum temperature forecast (°C) for the rural property.

    params:
        car_codes (list[str]): List of CAR codes for the property.
        forecast_days (int): Number of forecast days, between 1 and 16. Defaults to 16.

    Return:
        ToolResult: Text with the daily temperature forecast (date, max, min).
    """
    try:
        log_debug(f"get_temperature_forecast: car_codes={car_codes}, forecast_days={forecast_days}")
        if not 1 <= forecast_days <= 16:
            log_warning(f"forecast_days fora do intervalo permitido: {forecast_days}")
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

        log_debug(f"get_temperature_forecast: {len(lines)} dias retornados ({property_obj.car_code})")
        return ToolResult(content=content)

    except Exception as e:
        log_error(f"get_temperature_forecast: {e}")
        return ToolResult(content=str(e))