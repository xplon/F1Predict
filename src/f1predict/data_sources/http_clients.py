"""Small HTTP adapters for future live ingestion.

The MVP uses seed data by default. These clients define the live-data boundary
without forcing external dependencies into the first runnable version.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class HttpJsonClient:
    timeout_seconds: int = 20
    user_agent: str = "F1Predict-MVP/0.1"

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        target = url
        if params:
            target = f"{url}?{urlencode(params)}"
        request = Request(target, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - user-controlled URLs are not passed here.
            return json.loads(response.read().decode("utf-8"))


@dataclass(frozen=True)
class HttpTextClient:
    timeout_seconds: int = 20
    user_agent: str = "F1Predict-MVP/0.1"

    def get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        target = url
        if params:
            target = f"{url}?{urlencode(params)}"
        request = Request(target, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - fixed project URLs.
            return response.read().decode("utf-8", errors="replace")


class F1OfficialClient:
    base_url = "https://www.formula1.com/en"

    def __init__(self, http: HttpTextClient | None = None) -> None:
        self.http = http or HttpTextClient()

    def page_snapshot(self, page: str, year: int) -> dict[str, Any]:
        paths = {
            "calendar": f"racing/{year}",
            "drivers": f"results/{year}/drivers",
            "teams": f"results/{year}/team",
        }
        if page not in paths:
            raise ValueError(f"Unsupported F1 official page: {page}")
        url = f"{self.base_url}/{paths[page]}"
        html = self.http.get_text(url)
        return {
            "url": url,
            "page": page,
            "year": year,
            "html": html,
            "length": len(html),
        }

    def race_page_snapshot(self, year: int, slug: str) -> dict[str, Any]:
        safe_slug = quote(slug.strip("/"), safe="-")
        if not safe_slug or "/" in safe_slug:
            raise ValueError(f"Unsupported F1 race slug: {slug}")
        url = f"{self.base_url}/racing/{year}/{safe_slug}"
        html = self.http.get_text(url)
        return {
            "url": url,
            "page": "race",
            "slug": safe_slug,
            "year": year,
            "html": html,
            "length": len(html),
        }


class OpenF1Client:
    base_url = "https://api.openf1.org/v1"

    def __init__(self, http: HttpJsonClient | None = None) -> None:
        self.http = http or HttpJsonClient()

    def sessions(self, **params: Any) -> Any:
        return self.http.get_json(f"{self.base_url}/sessions", params)

    def meetings(self, **params: Any) -> Any:
        return self.http.get_json(f"{self.base_url}/meetings", params)

    def laps(self, **params: Any) -> Any:
        return self.http.get_json(f"{self.base_url}/laps", params)

    def stints(self, **params: Any) -> Any:
        return self.http.get_json(f"{self.base_url}/stints", params)

    def weather(self, **params: Any) -> Any:
        return self.http.get_json(f"{self.base_url}/weather", params)

    def race_control(self, **params: Any) -> Any:
        return self.http.get_json(f"{self.base_url}/race_control", params)


class OpenMeteoClient:
    """Read-only Open-Meteo adapters for geocoding, forecasts, and historical weather."""

    geocoding_url = "https://geocoding-api.open-meteo.com/v1"
    archive_url = "https://archive-api.open-meteo.com/v1"
    forecast_url = "https://api.open-meteo.com/v1"

    def __init__(self, http: HttpJsonClient | None = None) -> None:
        self.http = http or HttpJsonClient()

    def geocode(
        self,
        name: str,
        count: int = 10,
        country_code: str | None = None,
        language: str = "en",
    ) -> Any:
        params: dict[str, Any] = {
            "name": name,
            "count": count,
            "language": language,
            "format": "json",
        }
        if country_code:
            params["countryCode"] = country_code
        return self.http.get_json(f"{self.geocoding_url}/search", params)

    def historical_weather(
        self,
        latitude: float,
        longitude: float,
        start_date: str,
        end_date: str,
        daily: list[str] | None = None,
        timezone: str = "UTC",
    ) -> Any:
        return self.http.get_json(
            f"{self.archive_url}/archive",
            {
                "latitude": latitude,
                "longitude": longitude,
                "start_date": start_date,
                "end_date": end_date,
                "daily": ",".join(daily or ["precipitation_sum", "rain_sum", "weather_code"]),
                "timezone": timezone,
            },
        )

    def forecast_weather(
        self,
        latitude: float,
        longitude: float,
        daily: list[str] | None = None,
        timezone: str = "UTC",
        forecast_days: int = 16,
    ) -> Any:
        return self.http.get_json(
            f"{self.forecast_url}/forecast",
            {
                "latitude": latitude,
                "longitude": longitude,
                "daily": ",".join(
                    daily
                    or [
                        "precipitation_probability_max",
                        "precipitation_sum",
                        "rain_sum",
                        "weather_code",
                    ]
                ),
                "forecast_days": forecast_days,
                "timezone": timezone,
            },
        )


class CircuitInfoClient:
    """Read structured circuit geometry from trusted URLs carried by OpenF1."""

    allowed_hosts = {"api.multiviewer.app"}

    def __init__(self, http: HttpJsonClient | None = None) -> None:
        self.http = http or HttpJsonClient()

    def circuit_info(self, url: str) -> Any:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in self.allowed_hosts:
            raise ValueError(f"Unsupported circuit info URL: {url}")
        return self.http.get_json(url)


class PolymarketMarketClient:
    """Read-only market-data client for future price snapshots."""

    gamma_url = "https://gamma-api.polymarket.com"
    clob_url = "https://clob.polymarket.com"

    def __init__(self, http: HttpJsonClient | None = None) -> None:
        self.http = http or HttpJsonClient()

    def search_markets(self, query: str, limit: int = 20, include_closed: bool = False) -> Any:
        return self.http.get_json(
            f"{self.gamma_url}/public-search",
            {
                "q": query,
                "limit_per_type": limit,
                "keep_closed_markets": int(include_closed),
            },
        )

    def f1_events(self, limit: int = 20) -> Any:
        return self.http.get_json(
            f"{self.gamma_url}/events",
            {"tag_slug": "f1", "limit": limit},
        )

    def order_book(self, token_id: str) -> Any:
        return self.http.get_json(
            f"{self.clob_url}/book",
            {"token_id": token_id},
        )

    def price_history(
        self,
        token_id: str,
        start_ts: int | None = None,
        end_ts: int | None = None,
        interval: str | None = None,
        fidelity: int | None = None,
    ) -> Any:
        params: dict[str, Any] = {"market": token_id}
        if start_ts is not None:
            params["startTs"] = start_ts
        if end_ts is not None:
            params["endTs"] = end_ts
        if interval is not None:
            params["interval"] = interval
        if fidelity is not None:
            params["fidelity"] = fidelity
        return self.http.get_json(
            f"{self.clob_url}/prices-history",
            params,
        )
