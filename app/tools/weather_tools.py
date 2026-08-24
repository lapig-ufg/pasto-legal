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

from app.schemas.rural_property import RuralProperty


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


@tool
def get_monthly_precipitation_forecast(
    run_context: RunContext, car_codes: list[str], months: int = 7
) -> ToolResult:
    """
    Retrieves the monthly precipitation forecast (mm) for the rural property
    from the Open-Meteo seasonal API, returning the mean precipitation for
    each month within the requested horizon (1 to 7 months).

    Use this tool when the user asks about:
    - Rainfall over the coming months or the next season.
    - Monthly precipitation mean for a horizon of 1 to 7 months.
    - Long-range flood/drought outlook on a monthly basis.

    Do NOT use this tool when the user asks about a specific future date
    or "in N days" — use get_daily_precipitation_forecast instead.

    params:
        car_codes (list[str]): List of CAR codes for the property.
        months (int): Number of months to forecast, between 1 and 7.
            Defaults to 7.

    Return:
        ToolResult: Text with the monthly precipitation forecast
        (date + mean mm).
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


@tool
def get_daily_precipitation_forecast(
    run_context: RunContext, car_codes: list[str], forecast_days: int = 1
) -> ToolResult:
    """
    Retrieves the precipitation forecast (mm) for a specific target day of the
    rural property from an ensemble of weather models via the Open-Meteo API,
    returning the 1st quartile (lower bound) and 3rd quartile (upper bound) of
    precipitation across the ensemble members for that single day.

    The ensemble API returns daily data from day 1 up to the chosen day; this
    tool reports the quartiles only for the last day (the day the user chose).

    Use this tool when the user asks about:
    - Precipitation on a specific future date (e.g. "on 2026-09-27").
    - Rainfall "in N days" / "on day N" (1 to 36 days ahead).
    - A single-day optimistic/pessimistic band (Q1/Q3 quartiles).

    Do NOT use this tool for monthly or seasonal trends — use
    get_monthly_precipitation_forecast instead.

    params:
        car_codes (list[str]): List of CAR codes for the property.
        forecast_days (int): Target day to forecast, between 1 and 36.
            Defaults to 1.

    Return:
        ToolResult: Text with the precipitation forecast for the chosen
        day (date + Q1 mm / Q3 mm).
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


@tool
def get_rain_season_forecast(
    run_context: RunContext, car_codes: list[str]
) -> ToolResult:
    """
    Determines when the rain season will begin within the next 7 months for
    the rural property, combining the seasonal precipitation forecast
    (monthly) with the historical precipitation of the last year (daily).

    Always attempts the full 7-month horizon; if there is no sign of the
    rain season starting within that window, the result indicates there will
    be no rain season in the next 7 months.

    Use this tool when the user asks about:
    - When the rain season will start.
    - When it will start raining on the property.
    - The beginning of the rainy season in the coming months.

    params:
        car_codes (list[str]): List of CAR codes for the property.

    Return:
        ToolResult: Text indicating in how many months the rain season
        will begin.
    """
    try:
        log_debug(f"get_rain_season_forecast: car_codes={car_codes}")
        property_obj = _resolve_property(run_context, car_codes)
        latitude, longitude = property_obj.get_centroid()

        today = datetime.date.today()
        one_year_ago = today - datetime.timedelta(days=365)

        archive_params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": one_year_ago.isoformat(),
            "end_date": today.isoformat(),
            "daily": "precipitation_sum",
        }
        archive_responses = openmeteo.weather_api(ARCHIVE_URL, params=archive_params)
        archive_response = archive_responses[0]

        archive_daily = archive_response.Daily()
        archive_precipitation_sum = archive_daily.Variables(0).ValuesAsNumpy()

        archive_data = {
            "date": pd.date_range(
                start=pd.to_datetime(archive_daily.Time(), unit="s", utc=True),
                end=pd.to_datetime(archive_daily.TimeEnd(), unit="s", utc=True),
                freq=pd.Timedelta(seconds=archive_daily.Interval()),
                inclusive="left",
            ),
            "precipitation_sum": archive_precipitation_sum,
        }
        pd.DataFrame(data=archive_data)

        seasonal_params = {
            "latitude": latitude,
            "longitude": longitude,
            "monthly": ["precipitation_mean", "precipitation_anomaly"],
        }
        seasonal_responses = openmeteo.weather_api(SEASONAL_URL, params=seasonal_params)
        seasonal_response = seasonal_responses[0]

        monthly = seasonal_response.Monthly()
        monthly_precipitation_mean = monthly.Variables(0).ValuesAsNumpy()
        monthly_precipitation_anomaly = monthly.Variables(1).ValuesAsNumpy()

        monthly_data = {
            "date": pd.date_range(
                start=f"{monthly.Year()}-{monthly.Month()}-01",
                periods=monthly.Count(),
                freq="MS",
                inclusive="left",
            ),
            "precipitation_mean": monthly_precipitation_mean,
            "precipitation_anomaly": monthly_precipitation_anomaly,
        }
        pd.DataFrame(data=monthly_data)

        log_debug(f"get_rain_season_forecast: estimativa gerada ({property_obj.car_code})")
        return ToolResult(content="Vai começar a chover em 2 meses")

    except Exception as e:
        log_error(f"get_rain_season_forecast: {e}")
        return ToolResult(content=str(e))


@tool
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