"""weather: live weather via Open-Meteo (docs/07 §3, TD-8). No API key needed."""

from __future__ import annotations

import time
from typing import Any

import httpx
from pydantic import BaseModel, Field

from nova.core.errors import ToolError
from nova.tools.base import Tool, ToolContext, ToolOutput, ToolSpec

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_HTTP_TIMEOUT_S = 10.0
_CACHE_TTL_S = 600.0  # 10-min per-city cache (R-3)

# WMO weather interpretation codes -> (child-friendly condition, emoji)
_WMO: dict[int, tuple[str, str]] = {
    0: ("clear", "☀️"),
    1: ("mostly clear", "🌤️"),
    2: ("partly cloudy", "⛅"),
    3: ("cloudy", "☁️"),
    45: ("foggy", "🌫️"),
    48: ("foggy", "🌫️"),
    51: ("drizzly", "🌦️"),
    53: ("drizzly", "🌦️"),
    55: ("drizzly", "🌦️"),
    61: ("rainy", "🌧️"),
    63: ("rainy", "🌧️"),
    65: ("very rainy", "🌧️"),
    66: ("icy rain", "🌧️"),
    67: ("icy rain", "🌧️"),
    71: ("snowy", "🌨️"),
    73: ("snowy", "🌨️"),
    75: ("very snowy", "❄️"),
    77: ("snowy", "❄️"),
    80: ("showery", "🌦️"),
    81: ("showery", "🌦️"),
    82: ("stormy showers", "⛈️"),
    85: ("snow showers", "🌨️"),
    86: ("snow showers", "🌨️"),
    95: ("thundery", "⛈️"),
    96: ("thundery with hail", "⛈️"),
    99: ("thundery with hail", "⛈️"),
}


def _condition(code: int | None) -> tuple[str, str]:
    return _WMO.get(code if code is not None else -1, ("unsettled", "🌡️"))


class WeatherParams(BaseModel):
    """Arguments for the weather tool."""

    city: str | None = Field(
        default=None, description="City name; null means the user's default city."
    )
    days: int = Field(default=1, ge=1, le=3, description="How many days of forecast (1-3).")


class WeatherTool(Tool):
    """Geocode the city, fetch current + daily forecast, cache 10 minutes per city."""

    spec = ToolSpec(
        name="weather",
        title="Weather",
        description=(
            "Get the current weather and a short forecast for a city. Use when the user "
            "asks about weather, temperature, rain or snow, e.g. 'what's the weather in "
            "Lagos' or 'will it rain tomorrow'."
        ),
        parameters=WeatherParams,
        sensitive=False,
        icon="cloud-sun",
        detail_template="Checking the weather in {city}",
    )

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        # transport is a test seam (httpx.MockTransport); None = real network.
        self._client = httpx.Client(timeout=_HTTP_TIMEOUT_S, transport=transport)
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def execute(self, args: BaseModel, ctx: ToolContext) -> ToolOutput:
        assert isinstance(args, WeatherParams)
        city = (args.city or ctx.settings.weather.default_city).strip()
        cache_key = f"{city.lower()}|{args.days}"

        cached = self._cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < _CACHE_TTL_S:
            return ToolOutput(data=cached[1])

        place = self._geocode(city)
        data = self._forecast(place, args.days)
        self._cache[cache_key] = (time.monotonic(), data)
        return ToolOutput(data=data)

    def _geocode(self, city: str) -> dict[str, Any]:
        payload = self._get(_GEOCODE_URL, {"name": city, "count": 1})
        results = payload.get("results") or []
        if not results:
            raise ToolError(
                f"No city named {city!r} was found. Ask the user to check the spelling.",
                code="city_not_found",
            )
        return results[0]

    def _forecast(self, place: dict[str, Any], days: int) -> dict[str, Any]:
        payload = self._get(
            _FORECAST_URL,
            {
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,weather_code",
                "forecast_days": days,
                "timezone": "auto",
            },
        )
        current = payload.get("current") or {}
        daily = payload.get("daily") or {}
        temp = round(current.get("temperature_2m", 0))
        condition, emoji = _condition(current.get("weather_code"))
        highs = daily.get("temperature_2m_max") or [temp]
        lows = daily.get("temperature_2m_min") or [temp]
        codes = daily.get("weather_code") or []
        day_list = [
            {
                "date": date,
                "high_c": round(high),
                "low_c": round(low),
                "condition": _condition(code)[0],
            }
            for date, high, low, code in zip(
                daily.get("time") or [], highs, lows, codes, strict=False
            )
        ]
        city_name = place.get("name", "")
        return {
            "city": city_name,
            "country": place.get("country", ""),
            "temp_c": temp,
            "condition": condition,
            "condition_emoji": emoji,
            "high_c": round(highs[0]),
            "low_c": round(lows[0]),
            "days": day_list,
            "summary": f"It's {temp}° and {condition} in {city_name}",
        }

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise ToolError(
                f"Couldn't reach the weather service: {exc}", code="network_error"
            ) from exc
        if response.status_code >= 400:
            raise ToolError(
                f"The weather service answered with an error (HTTP {response.status_code}).",
                code="service_error",
            )
        result: dict[str, Any] = response.json()
        return result
