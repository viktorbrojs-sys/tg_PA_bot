import httpx
import pytest
from integrations.weather_client import (
    UMBRELLA_THRESHOLD,
    NullWeatherClient,
    OpenMeteoClient,
    describe_weather_code,
)


@pytest.mark.asyncio
async def test_null_weather_client_always_returns_none():
    client = NullWeatherClient()
    assert await client.today() is None


def test_describe_weather_code_known_code():
    assert describe_weather_code(0) == "ясно"
    assert describe_weather_code(61) == "небольшой дождь"


def test_describe_weather_code_unknown_code_has_generic_fallback():
    assert describe_weather_code(12345) == "переменная облачность"


def _mock_forecast_response(monkeypatch, payload: dict) -> None:
    async def fake_get(self, url, params=None):  # noqa: ARG001
        request = httpx.Request("GET", url)
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)


@pytest.mark.asyncio
async def test_open_meteo_client_parses_forecast(monkeypatch):
    _mock_forecast_response(
        monkeypatch,
        {
            "daily": {
                "time": ["2026-09-15"],
                "temperature_2m_min": [12.3],
                "temperature_2m_max": [21.7],
                "precipitation_probability_max": [70],
                "weathercode": [61],
            }
        },
    )
    client = OpenMeteoClient(latitude=55.75, longitude=37.62)

    weather = await client.today()
    assert weather is not None
    assert weather.temp_min == 12.3
    assert weather.temp_max == 21.7
    assert weather.precipitation_probability == 70
    assert weather.weather_code == 61
    assert weather.precipitation_probability >= UMBRELLA_THRESHOLD


@pytest.mark.asyncio
async def test_open_meteo_client_returns_none_on_http_error(monkeypatch):
    async def fake_get(self, url, params=None):  # noqa: ARG001
        raise httpx.ConnectError("boom", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    client = OpenMeteoClient(latitude=55.75, longitude=37.62)

    assert await client.today() is None


@pytest.mark.asyncio
async def test_open_meteo_client_returns_none_on_malformed_payload(monkeypatch):
    _mock_forecast_response(monkeypatch, {"daily": {}})
    client = OpenMeteoClient(latitude=55.75, longitude=37.62)

    assert await client.today() is None
