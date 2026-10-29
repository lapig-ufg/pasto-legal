import datetime

import numpy as np
import openmeteo_requests
import pandas as pd
import requests_cache
from openmeteo_sdk.Variable import Variable
from retry_requests import retry

from semente import tool
from semente import ToolResult
from semente.context import Context as RunContext
from semente.logging import log_debug, log_warning, log_error

from semente.configs.prompts import get_tool_description, get_tool_result_text
from domain.schemas.feature import Feature
from domain.utils.feature_utils import resolve_feature
from domain.services.geospatial.season_forecast import (
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

_THRESHOLD_HORIZON_MONTHS = 7


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


def _resolve_property(run_context: RunContext, feature_id: str) -> Feature:
    selected_property = resolve_feature(run_context, feature_id)
    if selected_property is None:
        raise ValueError(
            f"Property with id {feature_id} not found in the system."
        )
    return selected_property

def _monthly_precipitation(latitude: float, longitude: float, months: int) -> pd.DataFrame:
    """Monthly precipitation totals (mm) from the seasonal model.

    Despite the API's ``precipitation_mean`` name, the values are the month's
    total in millimetres — checked against the Goiás climatology (October to
    March between 177 and 278 mm, April dropping to 76 mm).

    Shared by the forecast listing and the threshold search so both read
    exactly the same numbers.

    Returns:
        DataFrame with ``date`` (first day of the month) and
        ``precipitation`` (mm).
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "monthly": "precipitation_mean",
        "forecast_days": months * 31,
    }
    response = openmeteo.weather_api(SEASONAL_URL, params=params)[0]
    monthly = response.Monthly()

    return pd.DataFrame({
        "date": pd.date_range(
            start=f"{monthly.Year()}-{monthly.Month()}-01",
            periods=monthly.Count(),
            freq="MS",
            inclusive="left",
        ),
        "precipitation": monthly.Variables(0).ValuesAsNumpy(),
    })

def _precipitation_so_far(
    latitude: float, longitude: float, today: datetime.date
) -> float | None:
    """Rain already recorded this month, from day 1 to yesterday (mm).

    The seasonal model reports the whole-month total, including days already
    past. For the current month that overstates what the producer can still
    expect, so the threshold search subtracts what has already fallen.

    This is measured rather than estimated on purpose: rain is not spread
    evenly across the month. In October (start of the rainy season in Goiás)
    19 of 31 days had elapsed — 61% of the days — but only 46% of the rain.

    Returns None when the figure is unavailable (the archive lags a few days,
    and on the first day of the month there is nothing to add up), so the
    caller can fall back to the full monthly total.
    """
    if today.day <= 1:
        return None

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": today.replace(day=1).isoformat(),
        "end_date": (today - datetime.timedelta(days=1)).isoformat(),
        "daily": "precipitation_sum",
    }

    try:
        response = openmeteo.weather_api(ARCHIVE_URL, params=params)[0]
        values = response.Daily().Variables(0).ValuesAsNumpy()
    except Exception as e:
        log_warning(f"_precipitation_so_far: archive unavailable ({e})")
        return None

    return float(np.nansum(values))

@tool(description=get_tool_description("weather_tools", "get_monthly_precipitation_forecast"))
def get_monthly_precipitation_forecast(
    run_context: RunContext, feature_id: str, months: int = 7
) -> ToolResult:
    """
    Retrieves the monthly precipitation forecast (mm) for the rural property.

    params:
        feature_id (str): Identifier (id) of the registered feature.
        months (int): Number of months to forecast, between 1 and 7. Defaults to 7.

    Return:
        ToolResult: Text with the monthly precipitation forecast (date + total mm).
    """
    try:
        log_debug(f"get_monthly_precipitation_forecast: feature_id={feature_id}, months={months}")
        if not 1 <= months <= 7:
            log_warning(f"months fora do intervalo permitido: {months}")
            raise ValueError(
                f"months must be between 1 and 7 (received: {months})."
            )

        property_obj = _resolve_property(run_context, feature_id)
        latitude, longitude = property_obj.get_centroid()

        monthly_dataframe = _monthly_precipitation(latitude, longitude, months)

        lines = []
        for _, row in monthly_dataframe.iterrows():
            total_val = float(row["precipitation"])
            if total_val != total_val:
                total_val = 0.0
            lines.append(
                f"{row['date'].strftime('%Y-%m-%d')}: total {total_val:.1f} mm"
            )

        content = (
            f"Monthly precipitation forecast (seasonal) for property "
            f"{property_obj.id} ({latitude:.4f}, {longitude:.4f}):\n"
            + "\n".join(lines)
        )

        log_debug(f"get_monthly_precipitation_forecast: {len(lines)} meses retornados ({property_obj.id})")
        return ToolResult(content=content)

    except Exception as e:
        log_error(f"get_monthly_precipitation_forecast: {e}")
        return ToolResult(content=get_tool_result_text("weather_tools", "get_monthly_precipitation_forecast", "error", error=e))


@tool(description=get_tool_description("weather_tools", "get_first_month_above_precipitation_threshold"))
def get_first_month_above_precipitation_threshold(
    run_context: RunContext, feature_id: str, threshold_mm: float
) -> ToolResult:
    """Finds the first upcoming month expected to reach a rainfall threshold.

    Walks the seasonal forecast from the current month on and returns the
    first month whose expected rainfall reaches ``threshold_mm``. For the
    current month the comparison uses only the rain still to come, since what
    has already fallen cannot be planned around.

    params:
        feature_id (str): Identifier (id) of the registered feature.
        threshold_mm (float): Minimum monthly rainfall the user is waiting
            for, in millimetres.

    Return:
        ToolResult: The first month that reaches the threshold, or the
        wettest month in the horizon when none of them does.
    """
    try:
        log_debug(
            f"get_first_month_above_precipitation_threshold: "
            f"feature_id={feature_id}, threshold_mm={threshold_mm}"
        )

        if threshold_mm <= 0:
            raise ValueError(
                f"threshold_mm must be greater than zero (received: {threshold_mm})."
            )

        property_obj = _resolve_property(run_context, feature_id)
        latitude, longitude = property_obj.get_centroid()

        forecast = _monthly_precipitation(
            latitude, longitude, _THRESHOLD_HORIZON_MONTHS
        )
        today = datetime.date.today()
        already_fallen = _precipitation_so_far(latitude, longitude, today)

        candidates = []
        for _, row in forecast.iterrows():
            expected = float(row["precipitation"])
            if expected != expected:  # NaN: month without data
                continue

            month = row["date"].date()
            available, note = expected, ""

            is_current = (month.year, month.month) == (today.year, today.month)
            if is_current and already_fallen is not None:
                available = max(expected - already_fallen, 0.0)
                note = (
                    f" ({expected:.0f} mm expected for the whole month, "
                    f"{already_fallen:.0f} mm already fallen)"
                )

            candidates.append((month, available, note))

        if not candidates:
            return ToolResult(
                content="No monthly precipitation forecast available for this property."
            )

        for month, available, note in candidates:
            if available >= threshold_mm:
                log_debug(f"get_first_month_above_precipitation_threshold: {month:%Y-%m}")
                return ToolResult(content=(
                    f"First month reaching {threshold_mm:.0f} mm for property "
                    f"{property_obj.id}: {month:%Y-%m}, with {available:.0f} mm{note}."
                ))

        wettest = max(candidates, key=lambda candidate: candidate[1])
        log_debug("get_first_month_above_precipitation_threshold: no month reaches the threshold")
        return ToolResult(content=(
            f"None of the next {len(candidates)} months reaches {threshold_mm:.0f} mm "
            f"for property {property_obj.id}. The wettest is {wettest[0]:%Y-%m}, "
            f"with {wettest[1]:.0f} mm{wettest[2]}."
        ))

    except Exception as e:
        log_error(f"get_first_month_above_precipitation_threshold: {e}")
        return ToolResult(content=get_tool_result_text(
            "weather_tools", "get_first_month_above_precipitation_threshold", "error", error=e
        ))


@tool(description=get_tool_description("weather_tools", "get_daily_precipitation_forecast"))
def get_daily_precipitation_forecast(
    run_context: RunContext, feature_id: str, forecast_days: int = 1
) -> ToolResult:
    """
    Retrieves the precipitation forecast (mm) for a specific target day of the rural property.

    params:
        feature_id (str): Identifier (id) of the registered feature.
        forecast_days (int): Target day to forecast, between 1 and 36. Defaults to 1.

    Return:
        ToolResult: Text with the precipitation forecast for the chosen day.
    """
    try:
        log_debug(f"get_daily_precipitation_forecast: feature_id={feature_id}, forecast_days={forecast_days}")
        if not 1 <= forecast_days <= 36:
            log_warning(f"forecast_days fora do intervalo permitido: {forecast_days}")
            raise ValueError(
                f"forecast_days must be between 1 and 36 (received: {forecast_days})."
            )

        property_obj = _resolve_property(run_context, feature_id)
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
            f"{property_obj.id} ({latitude:.4f}, {longitude:.4f}) "
            f"on {target_date} (day {forecast_days}):\n"
            f"Q1 (lower): {q1:.1f} mm / Q3 (upper): {q3:.1f} mm"
        )

        log_debug(f"get_daily_precipitation_forecast: Q1={q1:.1f}mm Q3={q3:.1f}mm ({property_obj.id})")
        return ToolResult(content=content)

    except Exception as e:
        log_error(f"get_daily_precipitation_forecast: {e}")
        return ToolResult(content=get_tool_result_text("weather_tools", "get_daily_precipitation_forecast", "error", error=e))


@tool(description=get_tool_description("weather_tools", "get_rain_season_onset_forecast"))
def get_rain_season_onset_forecast(
    run_context: RunContext, feature_id: str
) -> ToolResult:
    """
    Predicts the start date of the rainy season for the rural property.

    params:
        feature_id (str): Identifier (id) of the registered feature.

    Return:
        ToolResult: Predicted rain onset date (YYYY-MM-DD), or a message
        indicating the rainy season has already begun / is unavailable.
    """
    try:
        log_debug(f"get_rain_season_onset_forecast: feature_id={feature_id}")
        property_obj = _resolve_property(run_context, feature_id)
        latitude, longitude = property_obj.get_centroid()

        today = datetime.date.today()
        result = _get_rain_onset(latitude, longitude, today)

        content = (
            f"Rain onset forecast for property {property_obj.id} "
            f"({latitude:.4f}, {longitude:.4f}): {result}"
        )

        log_debug(f"get_rain_season_onset_forecast: {result} ({property_obj.id})")
        return ToolResult(content=content)

    except Exception as e:
        log_error(f"get_rain_season_onset_forecast: {e}")
        return ToolResult(content=get_tool_result_text("weather_tools", "get_rain_season_onset_forecast", "error", error=e))


@tool(description=get_tool_description("weather_tools", "get_dry_season_onset_forecast"))
def get_dry_season_onset_forecast(
    run_context: RunContext, feature_id: str
) -> ToolResult:
    """
    Predicts the start date of the dry season (end of rains) for the rural property.

    params:
        feature_id (str): Identifier (id) of the registered feature.

    Return:
        ToolResult: Predicted dry-season onset date (YYYY-MM-DD), or a
        message indicating the dry season is underway / the forecast
        horizon does not extend far enough.
    """
    try:
        log_debug(f"get_dry_season_onset_forecast: feature_id={feature_id}")
        property_obj = _resolve_property(run_context, feature_id)
        latitude, longitude = property_obj.get_centroid()

        today = datetime.date.today()
        result = _get_dry_season_onset(latitude, longitude, today)

        content = (
            f"Dry season onset forecast for property {property_obj.id} "
            f"({latitude:.4f}, {longitude:.4f}): {result}"
        )

        log_debug(f"get_dry_season_onset_forecast: {result} ({property_obj.id})")
        return ToolResult(content=content)

    except Exception as e:
        log_error(f"get_dry_season_onset_forecast: {e}")
        return ToolResult(content=get_tool_result_text("weather_tools", "get_dry_season_onset_forecast", "error", error=e))


@tool(description=get_tool_description("weather_tools", "get_temperature_forecast"))
def get_temperature_forecast(
    run_context: RunContext, feature_id: str, forecast_days: int = 16
) -> ToolResult:
    """
    Retrieves the daily maximum and minimum temperature forecast (°C) for the rural property.

    params:
        feature_id (str): Identifier (id) of the registered feature.
        forecast_days (int): Number of forecast days, between 1 and 16. Defaults to 16.

    Return:
        ToolResult: Text with the daily temperature forecast (date, max, min).
    """
    try:
        log_debug(f"get_temperature_forecast: feature_id={feature_id}, forecast_days={forecast_days}")
        if not 1 <= forecast_days <= 16:
            log_warning(f"forecast_days fora do intervalo permitido: {forecast_days}")
            raise ValueError(
                f"forecast_days must be between 1 and 16 (received: {forecast_days})."
            )

        property_obj = _resolve_property(run_context, feature_id)
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
            f"{property_obj.id} ({latitude:.4f}, {longitude:.4f}):\n"
            + "\n".join(lines)
        )

        log_debug(f"get_temperature_forecast: {len(lines)} dias retornados ({property_obj.id})")
        return ToolResult(content=content)

    except Exception as e:
        log_error(f"get_temperature_forecast: {e}")
        return ToolResult(content=get_tool_result_text("weather_tools", "get_temperature_forecast", "error", error=e))
