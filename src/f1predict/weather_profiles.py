"""Source-backed weather profile loading for event inputs."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from f1predict.domain import parse_dt
from f1predict.domain import RaceEvent
from f1predict.results import normalize_event_name


LOCATION_QUERY_ALIASES = {
    "australian": ["Melbourne"],
    "chinese": ["Shanghai"],
    "japanese": ["Suzuka"],
    "miami": ["Miami Gardens"],
    "canadian": ["Montreal"],
    "monaco": ["Monaco"],
    "barcelona": ["Barcelona"],
    "austrian": ["Spielberg"],
    "british": ["Silverstone"],
    "belgian": ["Spa", "Francorchamps", "Stavelot"],
    "hungarian": ["Budapest"],
    "dutch": ["Zandvoort"],
    "italian": ["Monza"],
    "spanish": ["Madrid"],
    "azerbaijan": ["Baku"],
    "singapore": ["Singapore", "Marina Bay"],
    "unitedstates": ["Austin"],
    "mexicocity": ["Mexico City"],
    "saopaulo": ["Sao Paulo"],
    "lasvegas": ["Las Vegas"],
    "qatar": ["Lusail"],
    "abudhabi": ["Yas Island", "Abu Dhabi"],
}


@dataclass(frozen=True)
class WeatherProfile:
    event_key: str | None
    event_name: str | None
    event_date: str | None
    location_query: str | None
    country_name: str | None
    latitude: float | None
    longitude: float | None
    elevation_m: float | None
    source_path: str
    captured_at: str | None
    baseline_start_year: int
    baseline_end_year: int
    window_days: int
    sample_day_count: int
    wet_day_count: int
    wet_probability: float
    precipitation_mean_mm: float
    precipitation_p90_mm: float
    archive_url: str | None
    geocoding_url: str | None

    def weather_prior(self, track_type: str) -> dict[str, float]:
        return {
            "wet_probability": self.wet_probability,
            "safety_car_probability": safety_car_probability_from_track_type(track_type),
        }

    def provenance(self, track_type: str) -> dict[str, Any]:
        return {
            "source": "open_meteo_historical_climate_profile",
            "archive_url": self.archive_url,
            "geocoding_url": self.geocoding_url,
            "path": self.source_path,
            "captured_at": self.captured_at,
            "event_name": self.event_name,
            "event_date": self.event_date,
            "location_query": self.location_query,
            "country_name": self.country_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "elevation_m": self.elevation_m,
            "baseline_start_year": self.baseline_start_year,
            "baseline_end_year": self.baseline_end_year,
            "window_days": self.window_days,
            "target_year_weather_excluded": True,
            "race_week_forecast": False,
            "sample_day_count": self.sample_day_count,
            "wet_day_count": self.wet_day_count,
            "precipitation_mean_mm": self.precipitation_mean_mm,
            "precipitation_p90_mm": self.precipitation_p90_mm,
            "track_type": track_type,
            "components": {
                "wet_probability": {
                    "method": "same-week historical precipitation frequency",
                    "wet_threshold_mm": 0.5,
                    "quality": "derived",
                },
                "safety_car_probability": {
                    "method": "track-type prior derived from sourced circuit profile when available",
                    "quality": "derived",
                },
            },
            "quality": "derived",
        }


@dataclass(frozen=True)
class WeatherForecast:
    event_key: str | None
    event_name: str | None
    event_date: str | None
    location_query: str | None
    country_name: str | None
    latitude: float | None
    longitude: float | None
    elevation_m: float | None
    source_path: str
    captured_at: str | None
    forecast_url: str | None
    geocoding_url: str | None
    forecast_day_count: int
    precipitation_probability_max: float | None
    precipitation_sum_mm: float | None
    rain_sum_mm: float | None
    weather_code: int | None
    wet_probability: float

    def is_available(self, cutoff: Any | None) -> bool:
        if cutoff is None:
            return True
        cutoff_dt = cutoff if isinstance(cutoff, datetime) else parse_dt(str(cutoff))
        if cutoff_dt is None:
            return False
        captured = parse_dt(self.captured_at)
        return captured is not None and captured <= cutoff_dt

    def weather_prior(self, track_type: str) -> dict[str, float]:
        return {
            "wet_probability": self.wet_probability,
            "safety_car_probability": safety_car_probability_from_track_type(track_type),
        }

    def provenance(self, track_type: str) -> dict[str, Any]:
        return {
            "source": "open_meteo_race_week_forecast",
            "forecast_url": self.forecast_url,
            "geocoding_url": self.geocoding_url,
            "path": self.source_path,
            "captured_at": self.captured_at,
            "event_name": self.event_name,
            "event_date": self.event_date,
            "location_query": self.location_query,
            "country_name": self.country_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "elevation_m": self.elevation_m,
            "race_week_forecast": True,
            "forecast_day_count": self.forecast_day_count,
            "precipitation_probability_max": self.precipitation_probability_max,
            "precipitation_sum_mm": self.precipitation_sum_mm,
            "rain_sum_mm": self.rain_sum_mm,
            "weather_code": self.weather_code,
            "track_type": track_type,
            "components": {
                "wet_probability": {
                    "method": "Open-Meteo daily precipitation probability for the event date",
                    "quality": "verified",
                },
                "safety_car_probability": {
                    "method": "track-type prior derived from sourced circuit profile when available",
                    "quality": "derived",
                },
            },
            "quality": "verified",
        }


class WeatherProfileProvider:
    """Reads stored Open-Meteo climate profiles.

    These profiles are not race-week forecasts. They are source-backed climate
    priors derived from years before the target season, so they can be used in
    replay without leaking the target race's actual weather.
    """

    def __init__(self, raw_root: Path | str = Path("data/raw")) -> None:
        self.raw_root = Path(raw_root)
        self._profiles: list[WeatherProfile] | None = None

    def load_for_calendar_item(self, item: dict[str, Any]) -> WeatherProfile | None:
        profiles = self._load_profiles()
        lookups = [
            normalize_event_name(str(item.get("event_name") or "")),
            normalize_event_name(str(item.get("official_name") or "")),
        ]
        for lookup in [value for value in lookups if value]:
            for profile in profiles:
                if lookup in self._profile_keys(profile):
                    return profile
        return None

    def _load_profiles(self) -> list[WeatherProfile]:
        if self._profiles is not None:
            return self._profiles
        root = self.raw_root / "weather_profiles"
        files = []
        if root.exists():
            files = [path for path in root.rglob("*.json") if not path.name.endswith(".meta.json")]
        profiles = []
        for path in sorted(files, key=lambda item: item.stat().st_mtime, reverse=True):
            profile = self._load_file(path)
            if profile is not None:
                profiles.append(profile)
        self._profiles = profiles
        return profiles

    def _load_file(self, path: Path) -> WeatherProfile | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        stats = self._weather_stats(raw)
        if stats is None:
            return None
        meta = self._meta(path)
        event_name = self._string_value(raw.get("event_name") or raw.get("meeting_name"))
        event_date = self._string_value(raw.get("event_date"))
        geocoding_result = raw.get("geocoding_result") if isinstance(raw.get("geocoding_result"), dict) else {}
        return WeatherProfile(
            event_key=normalize_event_name(event_name or "") if event_name else None,
            event_name=event_name,
            event_date=event_date,
            location_query=self._string_value(raw.get("location_query")),
            country_name=self._string_value(raw.get("country_name")),
            latitude=self._float_value(geocoding_result.get("latitude")),
            longitude=self._float_value(geocoding_result.get("longitude")),
            elevation_m=self._float_value(geocoding_result.get("elevation")),
            source_path=str(path),
            captured_at=self._string_value(meta.get("captured_at")),
            baseline_start_year=int(raw.get("baseline_start_year") or 0),
            baseline_end_year=int(raw.get("baseline_end_year") or 0),
            window_days=int(raw.get("window_days") or 0),
            sample_day_count=stats["sample_day_count"],
            wet_day_count=stats["wet_day_count"],
            wet_probability=stats["wet_probability"],
            precipitation_mean_mm=stats["precipitation_mean_mm"],
            precipitation_p90_mm=stats["precipitation_p90_mm"],
            archive_url=self._string_value(raw.get("archive_url")),
            geocoding_url=self._string_value(raw.get("geocoding_url")),
        )

    @staticmethod
    def _profile_keys(profile: WeatherProfile) -> set[str]:
        values = {
            profile.event_key,
            normalize_event_name(profile.event_name or ""),
        }
        return {value for value in values if value}

    @classmethod
    def _weather_stats(cls, raw: dict[str, Any]) -> dict[str, Any] | None:
        event_dt = parse_dt(str(raw.get("event_date") or ""))
        if event_dt is None:
            return None
        baseline_start_year = int(raw.get("baseline_start_year") or 0)
        baseline_end_year = int(raw.get("baseline_end_year") or 0)
        window_days = int(raw.get("window_days") or 0)
        target_dates = cls._target_dates(
            event_dt.date(),
            baseline_start_year,
            baseline_end_year,
            window_days,
        )
        archive = raw.get("archive")
        if not isinstance(archive, dict):
            return None
        daily = archive.get("daily")
        if not isinstance(daily, dict):
            return None
        times = daily.get("time")
        precipitation = daily.get("precipitation_sum")
        if not isinstance(times, list) or not isinstance(precipitation, list):
            return None

        samples = []
        for day, amount in zip(times, precipitation):
            if str(day) not in target_dates:
                continue
            value = cls._float_value(amount)
            if value is not None:
                samples.append(value)
        if not samples:
            return None
        ordered = sorted(samples)
        p90_index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.9)))
        wet_day_count = sum(1 for value in samples if value >= 0.5)
        return {
            "sample_day_count": len(samples),
            "wet_day_count": wet_day_count,
            "wet_probability": round(wet_day_count / len(samples), 4),
            "precipitation_mean_mm": round(sum(samples) / len(samples), 4),
            "precipitation_p90_mm": round(ordered[p90_index], 4),
        }

    @staticmethod
    def _target_dates(event_date: date, start_year: int, end_year: int, window_days: int) -> set[str]:
        dates = set()
        for year in range(start_year, end_year + 1):
            try:
                center = event_date.replace(year=year)
            except ValueError:
                center = date(year, 2, 28)
            for offset in range(-window_days, window_days + 1):
                dates.add((center + timedelta(days=offset)).isoformat())
        return dates

    @staticmethod
    def _meta(path: Path) -> dict[str, Any]:
        meta_path = path.with_name(f"{path.stem}.meta.json")
        if not meta_path.exists():
            return {}
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _string_value(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text if text else None

    @staticmethod
    def _float_value(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


class WeatherForecastProvider:
    """Reads cutoff-valid Open-Meteo race-week forecast snapshots."""

    def __init__(self, raw_root: Path | str = Path("data/raw")) -> None:
        self.raw_root = Path(raw_root)
        self._forecasts: list[WeatherForecast] | None = None

    def load_for_event(self, event: RaceEvent, cutoff: Any | None = None) -> WeatherForecast | None:
        event_key = normalize_event_name(event.name)
        candidates = [
            forecast
            for forecast in self._load_forecasts()
            if event_key in self._forecast_keys(forecast) and forecast.event_date == event.date
        ]
        candidates = [forecast for forecast in candidates if forecast.is_available(cutoff)]
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda forecast: parse_dt(forecast.captured_at) or parse_dt("1900-01-01T00:00:00+00:00"),
            reverse=True,
        )[0]

    def _load_forecasts(self) -> list[WeatherForecast]:
        if self._forecasts is not None:
            return self._forecasts
        root = self.raw_root / "weather_forecasts"
        files = []
        if root.exists():
            files = [path for path in root.rglob("*.json") if not path.name.endswith(".meta.json")]
        forecasts = []
        for path in sorted(files, key=lambda item: item.stat().st_mtime, reverse=True):
            forecast = self._load_file(path)
            if forecast is not None:
                forecasts.append(forecast)
        self._forecasts = forecasts
        return forecasts

    def _load_file(self, path: Path) -> WeatherForecast | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        event_date = self._string_value(raw.get("event_date"))
        if not event_date:
            return None
        daily = raw.get("forecast", {}).get("daily") if isinstance(raw.get("forecast"), dict) else None
        if not isinstance(daily, dict):
            return None
        day_index = self._day_index(daily, event_date)
        if day_index is None:
            return None
        probability = self._list_float(daily.get("precipitation_probability_max"), day_index)
        precipitation = self._list_float(daily.get("precipitation_sum"), day_index)
        rain = self._list_float(daily.get("rain_sum"), day_index)
        wet_probability = self._wet_probability(probability, precipitation, rain)
        meta = WeatherProfileProvider._meta(path)
        event_name = self._string_value(raw.get("event_name") or raw.get("meeting_name"))
        geocoding_result = raw.get("geocoding_result") if isinstance(raw.get("geocoding_result"), dict) else {}
        return WeatherForecast(
            event_key=normalize_event_name(event_name or "") if event_name else None,
            event_name=event_name,
            event_date=event_date,
            location_query=self._string_value(raw.get("location_query")),
            country_name=self._string_value(raw.get("country_name")),
            latitude=WeatherProfileProvider._float_value(geocoding_result.get("latitude")),
            longitude=WeatherProfileProvider._float_value(geocoding_result.get("longitude")),
            elevation_m=WeatherProfileProvider._float_value(geocoding_result.get("elevation")),
            source_path=str(path),
            captured_at=self._string_value(meta.get("captured_at")),
            forecast_url=self._string_value(raw.get("forecast_url")),
            geocoding_url=self._string_value(raw.get("geocoding_url")),
            forecast_day_count=len(daily.get("time", [])) if isinstance(daily.get("time"), list) else 0,
            precipitation_probability_max=probability,
            precipitation_sum_mm=precipitation,
            rain_sum_mm=rain,
            weather_code=self._list_int(daily.get("weather_code"), day_index),
            wet_probability=wet_probability,
        )

    @staticmethod
    def _forecast_keys(forecast: WeatherForecast) -> set[str]:
        values = {
            forecast.event_key,
            normalize_event_name(forecast.event_name or ""),
        }
        return {value for value in values if value}

    @staticmethod
    def _day_index(daily: dict[str, Any], event_date: str) -> int | None:
        days = daily.get("time")
        if not isinstance(days, list):
            return None
        for index, day in enumerate(days):
            if str(day) == event_date:
                return index
        return None

    @staticmethod
    def _list_float(values: Any, index: int) -> float | None:
        if not isinstance(values, list) or index >= len(values):
            return None
        return WeatherProfileProvider._float_value(values[index])

    @staticmethod
    def _list_int(values: Any, index: int) -> int | None:
        if not isinstance(values, list) or index >= len(values):
            return None
        try:
            return int(float(values[index]))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _wet_probability(probability_percent: float | None, precipitation: float | None, rain: float | None) -> float:
        if probability_percent is not None:
            return round(min(1.0, max(0.0, probability_percent / 100.0)), 4)
        amount = max(value for value in (precipitation, rain, 0.0) if value is not None)
        return 1.0 if amount >= 0.5 else 0.0

    @staticmethod
    def _string_value(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text if text else None


def weather_location_queries(item: dict[str, Any]) -> list[str]:
    event_key = normalize_event_name(str(item.get("event_name") or ""))
    candidates = list(LOCATION_QUERY_ALIASES.get(event_key, []))
    candidates.extend(
        [
            str(item.get("location") or ""),
            str(item.get("circuit_short_name") or ""),
            str(item.get("country_name") or ""),
        ]
    )
    normalized = []
    seen = set()
    for candidate in candidates:
        text = _ascii(candidate).strip()
        if text and text.lower() not in seen:
            normalized.append(text)
            seen.add(text.lower())
    return normalized


def select_geocoding_result(payload: dict[str, Any], country_name: str | None) -> dict[str, Any] | None:
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return None
    if not country_name:
        return results[0] if results else None
    country_key = _country_key(country_name)
    for result in results:
        if not isinstance(result, dict):
            continue
        if _country_key(str(result.get("country") or "")) == country_key:
            return result
    return None


def open_meteo_geocoding_url(query: str) -> str:
    return "https://geocoding-api.open-meteo.com/v1/search?" + urlencode(
        {
            "name": query,
            "count": 10,
            "language": "en",
            "format": "json",
        }
    )


def open_meteo_archive_url(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
) -> str:
    return "https://archive-api.open-meteo.com/v1/archive?" + urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_date,
            "end_date": end_date,
            "daily": "precipitation_sum,rain_sum,weather_code",
            "timezone": "UTC",
        }
    )


def open_meteo_forecast_url(
    latitude: float,
    longitude: float,
    forecast_days: int = 16,
) -> str:
    return "https://api.open-meteo.com/v1/forecast?" + urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "daily": "precipitation_probability_max,precipitation_sum,rain_sum,weather_code",
            "forecast_days": forecast_days,
            "timezone": "UTC",
        }
    )


def weather_baseline_range(event_date: str, baseline_start_year: int, baseline_end_year: int, window_days: int) -> tuple[str, str]:
    event_dt = parse_dt(event_date)
    if event_dt is None:
        raise ValueError(f"Invalid event date: {event_date}")
    month = event_dt.date().month
    day = event_dt.date().day
    start_center = _safe_date(baseline_start_year, month, day)
    end_center = _safe_date(baseline_end_year, month, day)
    return (
        (start_center - timedelta(days=window_days)).isoformat(),
        (end_center + timedelta(days=window_days)).isoformat(),
    )


def safety_car_probability_from_track_type(track_type: str) -> float:
    priors = {
        "street": 0.62,
        "technical": 0.44,
        "power": 0.40,
        "high_speed": 0.38,
    }
    return priors.get(track_type, 0.42)


def _safe_date(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError:
        return date(year, 2, 28)


def _ascii(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def _country_key(value: str) -> str:
    compact = normalize_event_name(_ascii(value))
    return compact.removeprefix("the")
