"""weather: MockTransport-driven — happy path, cache, every declared error (docs/07 §3)."""

from __future__ import annotations

import httpx
import pytest

from nova.core.errors import ToolError
from nova.tools.base import ToolContext
from nova.tools.weather import WeatherParams, WeatherTool

_GEOCODE_OK = {
    "results": [{"name": "Lagos", "country": "Nigeria", "latitude": 6.45, "longitude": 3.39}]
}
_FORECAST_OK = {
    "current": {"temperature_2m": 31.2, "weather_code": 0},
    "daily": {
        "time": ["2026-07-10", "2026-07-11"],
        "temperature_2m_max": [33.1, 30.0],
        "temperature_2m_min": [24.9, 23.0],
        "weather_code": [0, 61],
    },
}


def _tool(responder) -> WeatherTool:
    return WeatherTool(transport=httpx.MockTransport(responder))


def _ok_responder(request: httpx.Request) -> httpx.Response:
    if "geocoding" in request.url.host:
        return httpx.Response(200, json=_GEOCODE_OK)
    return httpx.Response(200, json=_FORECAST_OK)


def test_happy_path(ctx: ToolContext) -> None:
    data = _tool(_ok_responder).execute(WeatherParams(city="Lagos"), ctx).data
    assert data["city"] == "Lagos"
    assert data["temp_c"] == 31
    assert data["condition"] == "clear"
    assert data["high_c"] == 33
    assert data["summary"] == "It's 31° and clear in Lagos"


def test_null_city_uses_settings_default(ctx: ToolContext) -> None:
    seen: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:
        if "geocoding" in request.url.host:
            seen.append(request.url.params["name"])
            return httpx.Response(200, json=_GEOCODE_OK)
        return httpx.Response(200, json=_FORECAST_OK)

    _tool(responder).execute(WeatherParams(city=None), ctx)
    assert seen == [ctx.settings.weather.default_city]


def test_second_call_hits_cache(ctx: ToolContext) -> None:
    calls: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return _ok_responder(request)

    tool = _tool(responder)
    tool.execute(WeatherParams(city="Lagos"), ctx)
    tool.execute(WeatherParams(city="lagos"), ctx)  # case-insensitive cache key
    assert len(calls) == 2  # one geocode + one forecast — not four


def test_city_not_found(ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as excinfo:
        _tool(lambda _r: httpx.Response(200, json={"results": []})).execute(
            WeatherParams(city="Lagoss"), ctx
        )
    assert excinfo.value.code == "city_not_found"


def test_network_error(ctx: ToolContext) -> None:
    def responder(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(ToolError) as excinfo:
        _tool(responder).execute(WeatherParams(city="Lagos"), ctx)
    assert excinfo.value.code == "network_error"


def test_service_error(ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as excinfo:
        _tool(lambda _r: httpx.Response(500)).execute(WeatherParams(city="Lagos"), ctx)
    assert excinfo.value.code == "service_error"


def test_days_bounds_enforced_by_schema() -> None:
    with pytest.raises(ValueError):
        WeatherParams(city="Lagos", days=5)
