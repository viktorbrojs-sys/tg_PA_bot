"""Weather for the morning digest, via Open-Meteo (free, no API key).

Same pattern as the other integrations: an abstraction (``WeatherClient``)
with a no-op fallback (``NullWeatherClient``) so the bot works fine without
coordinates configured — the digest just won't mention weather.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes (https://open-meteo.com/en/docs), grouped to short
# Russian descriptions. Codes not listed fall back to a generic description.
_WEATHER_DESCRIPTIONS: dict[int, str] = {
    0: "ясно",
    1: "малооблачно",
    2: "переменная облачность",
    3: "облачно",
    45: "туман",
    48: "туман с изморозью",
    51: "лёгкая морось",
    53: "морось",
    55: "сильная морось",
    56: "ледяная морось",
    57: "сильная ледяная морось",
    61: "небольшой дождь",
    63: "дождь",
    65: "сильный дождь",
    66: "ледяной дождь",
    67: "сильный ледяной дождь",
    71: "небольшой снег",
    73: "снег",
    75: "сильный снег",
    77: "снежные зёрна",
    80: "кратковременный дождь",
    81: "ливень",
    82: "сильный ливень",
    85: "небольшой снегопад",
    86: "сильный снегопад",
    95: "гроза",
    96: "гроза с градом",
    99: "сильная гроза с градом",
}

# Precipitation-probability threshold (%) above which the digest suggests
# taking an umbrella.
UMBRELLA_THRESHOLD = 40


def describe_weather_code(code: int) -> str:
    return _WEATHER_DESCRIPTIONS.get(code, "переменная облачность")


@dataclass(frozen=True)
class DailyWeather:
    date: date
    temp_min: float
    temp_max: float
    precipitation_probability: int
    weather_code: int


class WeatherClient(Protocol):
    async def today(self) -> DailyWeather | None:
        """Return today's forecast, or None if unavailable."""
        ...


class NullWeatherClient:
    """Fallback used when no coordinates are configured — never any weather."""

    async def today(self) -> DailyWeather | None:
        return None


class OpenMeteoClient:
    """Free, keyless weather via the Open-Meteo forecast API."""

    def __init__(self, latitude: float, longitude: float) -> None:
        self._latitude = latitude
        self._longitude = longitude

    async def today(self) -> DailyWeather | None:
        params: dict[str, str | int | float] = {
            "latitude": self._latitude,
            "longitude": self._longitude,
            "daily": (
                "temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max,weathercode"
            ),
            "timezone": "auto",
            "forecast_days": 1,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(FORECAST_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
                daily = data["daily"]
                return DailyWeather(
                    date=date.fromisoformat(daily["time"][0]),
                    temp_min=float(daily["temperature_2m_min"][0]),
                    temp_max=float(daily["temperature_2m_max"][0]),
                    precipitation_probability=int(daily["precipitation_probability_max"][0]),
                    weather_code=int(daily["weathercode"][0]),
                )
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                logger.warning("Open-Meteo forecast fetch failed: %s", exc)
                return None
