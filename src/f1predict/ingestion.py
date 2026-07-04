"""Live ingestion orchestration for raw point-in-time snapshots."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timezone
from typing import Any

from f1predict.data_sources.fastf1_client import FastF1Client
from f1predict.data_sources.http_clients import (
    CircuitInfoClient,
    F1OfficialClient,
    OpenF1Client,
    OpenMeteoClient,
    PolymarketMarketClient,
)
from f1predict.domain import parse_dt
from f1predict.storage import RawSnapshotStore, SnapshotRecord
from f1predict.weather_profiles import (
    open_meteo_archive_url,
    open_meteo_forecast_url,
    open_meteo_geocoding_url,
    select_geocoding_result,
    weather_baseline_range,
    weather_location_queries,
)


@dataclass(frozen=True)
class IngestionResult:
    records: list[SnapshotRecord]
    failures: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": [record.to_dict() for record in self.records],
            "failures": self.failures,
        }


class LiveIngestor:
    def __init__(
        self,
        store: RawSnapshotStore | None = None,
        openf1: OpenF1Client | None = None,
        polymarket: PolymarketMarketClient | None = None,
        fastf1: FastF1Client | None = None,
        f1_official: F1OfficialClient | None = None,
        circuit_info: CircuitInfoClient | None = None,
        open_meteo: OpenMeteoClient | None = None,
    ) -> None:
        self.store = store or RawSnapshotStore()
        self.openf1 = openf1 or OpenF1Client()
        self.polymarket = polymarket or PolymarketMarketClient()
        self.fastf1 = fastf1
        self.f1_official = f1_official or F1OfficialClient()
        self.circuit_info = circuit_info or CircuitInfoClient()
        self.open_meteo = open_meteo or OpenMeteoClient()

    def ingest_openf1_event(
        self,
        year: int,
        event_query: str,
        include_session_data: bool = False,
    ) -> IngestionResult:
        meetings = self.openf1.meetings(year=year)
        matches = [item for item in meetings if self._matches_event(item, event_query)]
        if not matches:
            raise ValueError(f"No OpenF1 meeting matched {event_query!r} for year {year}")
        meeting = matches[0]
        meeting_key = meeting["meeting_key"]
        sessions = self.openf1.sessions(meeting_key=meeting_key)

        records = [
            self.store.write_json(
                "openf1",
                f"{year}_{event_query}_meetings",
                matches,
                {"year": year, "event_query": event_query},
            ),
            self.store.write_json(
                "openf1",
                f"{year}_{event_query}_sessions",
                sessions,
                {"meeting_key": meeting_key},
            ),
        ]

        if include_session_data:
            for session in sessions:
                session_key = session["session_key"]
                label = f"{year}_{event_query}_{session['session_name']}_{session_key}"
                for endpoint, loader in (
                    ("laps", self.openf1.laps),
                    ("weather", self.openf1.weather),
                    ("race_control", self.openf1.race_control),
                    ("stints", self.openf1.stints),
                ):
                    payload = loader(session_key=session_key)
                    records.append(
                        self.store.write_json(
                            "openf1",
                            f"{label}_{endpoint}",
                            payload,
                            {"session_key": session_key, "endpoint": endpoint},
                        )
                    )
        return IngestionResult(records)

    def ingest_openf1_calendar(self, year: int) -> IngestionResult:
        meetings = self.openf1.meetings(year=year)
        records = [
            self.store.write_json(
                "openf1",
                f"{year}_meetings",
                meetings,
                {"year": year},
            )
        ]
        return IngestionResult(records)

    def ingest_circuit_profiles(
        self,
        year: int,
        event_queries: list[str] | None = None,
    ) -> IngestionResult:
        meetings = self.openf1.meetings(year=year)
        queries = [query.lower() for query in event_queries or [] if query]
        records: list[SnapshotRecord] = []
        failures: list[dict[str, Any]] = []

        for meeting in meetings:
            name = str(meeting.get("meeting_name", ""))
            if "testing" in name.lower():
                continue
            if queries and not any(self._matches_event(meeting, query) for query in queries):
                continue
            url = str(meeting.get("circuit_info_url") or "")
            if not url:
                failures.append(
                    {
                        "year": year,
                        "event_name": name,
                        "meeting_key": meeting.get("meeting_key"),
                        "error": "missing_circuit_info_url",
                    }
                )
                continue
            try:
                payload = self.circuit_info.circuit_info(url)
                records.append(
                    self.store.write_json(
                        "circuit_profiles",
                        f"{year}_{name}_{meeting.get('circuit_key')}",
                        payload,
                        {
                            "year": year,
                            "event_name": name,
                            "meeting_key": meeting.get("meeting_key"),
                            "circuit_key": meeting.get("circuit_key"),
                            "circuit_info_url": url,
                            "source": "openf1_circuit_info_url",
                        },
                    )
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    {
                        "year": year,
                        "event_name": name,
                        "meeting_key": meeting.get("meeting_key"),
                        "circuit_key": meeting.get("circuit_key"),
                        "circuit_info_url": url,
                        "error": str(exc),
                    }
                )
        return IngestionResult(records, failures)

    def ingest_polymarket_f1_events(self, limit: int = 20) -> IngestionResult:
        events = self.polymarket.f1_events(limit=limit)
        records = [
            self.store.write_json(
                "polymarket",
                "f1_events",
                events,
                {"tag_slug": "f1", "limit": limit},
            )
        ]
        return IngestionResult(records)

    def ingest_fastf1_schedule(self, year: int) -> IngestionResult:
        client = self.fastf1 or FastF1Client()
        schedule = client.event_schedule(year)
        records = [
            self.store.write_json(
                "fastf1",
                f"{year}_schedule",
                schedule,
                {"year": year},
            )
        ]
        return IngestionResult(records)

    def ingest_fastf1_results(
        self,
        year: int,
        event: str | int,
        session: str = "R",
    ) -> IngestionResult:
        client = self.fastf1 or FastF1Client()
        payload = client.session_results(year=year, event=event, session=session)
        record = self._write_fastf1_result_payload(payload, year, event, session)
        return IngestionResult([record])

    def ingest_fastf1_due_results(
        self,
        year: int,
        as_of: str,
        session: str = "R",
    ) -> IngestionResult:
        client = self.fastf1 or FastF1Client()
        cutoff = self._parse_fastf1_utc(as_of)
        if cutoff is None:
            raise ValueError(f"Invalid as_of datetime: {as_of}")

        records: list[SnapshotRecord] = []
        failures: list[dict[str, Any]] = []
        for item in client.event_schedule(year):
            if str(item.get("EventFormat", "")).lower() == "testing":
                continue
            round_number = item.get("RoundNumber")
            event_date = self._parse_fastf1_utc(str(item.get("Session5DateUtc") or item.get("EventDate") or ""))
            if event_date is None or event_date > cutoff:
                continue
            try:
                payload = client.session_results(year=year, event=int(round_number), session=session)
                records.append(self._write_fastf1_result_payload(payload, year, int(round_number), session))
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    {
                        "year": year,
                        "round_number": round_number,
                        "event_name": item.get("EventName"),
                        "session": session,
                        "error": str(exc),
                    }
                )
        return IngestionResult(records, failures)

    def ingest_f1_official_page(self, page: str, year: int) -> IngestionResult:
        payload = self.f1_official.page_snapshot(page=page, year=year)
        records = [
            self.store.write_json(
                "f1_official",
                f"{year}_{page}",
                payload,
                {"page": page, "year": year},
            )
        ]
        return IngestionResult(records)

    def ingest_f1_official_race_profiles(
        self,
        year: int,
        slugs: list[str] | None = None,
    ) -> IngestionResult:
        race_slugs = list(dict.fromkeys(slugs or self._race_slugs_from_official_calendar(year)))
        records: list[SnapshotRecord] = []
        failures: list[dict[str, Any]] = []
        for slug in race_slugs:
            if "testing" in slug.lower():
                continue
            try:
                payload = self.f1_official.race_page_snapshot(year=year, slug=slug)
                records.append(
                    self.store.write_json(
                        "f1_official_race_profiles",
                        f"{year}_{slug}",
                        payload,
                        {
                            "year": year,
                            "slug": slug,
                            "url": payload.get("url"),
                        },
                    )
                )
            except Exception as exc:  # noqa: BLE001
                failures.append({"year": year, "slug": slug, "error": str(exc)})
        return IngestionResult(records, failures)

    def ingest_weather_profiles(
        self,
        year: int,
        event_queries: list[str] | None = None,
        baseline_start_year: int | None = None,
        baseline_end_year: int | None = None,
        window_days: int = 3,
    ) -> IngestionResult:
        meetings = self.openf1.meetings(year=year)
        queries = [query.lower() for query in event_queries or [] if query]
        start_year = baseline_start_year or year - 10
        end_year = baseline_end_year or year - 1
        records: list[SnapshotRecord] = []
        failures: list[dict[str, Any]] = []

        for meeting in meetings:
            name = str(meeting.get("meeting_name", ""))
            if "testing" in name.lower() or bool(meeting.get("is_cancelled", False)):
                continue
            if queries and not any(self._matches_event(meeting, query) for query in queries):
                continue
            event_date = str(meeting.get("date_end") or meeting.get("date_start") or "")
            try:
                start_date, end_date = weather_baseline_range(
                    event_date,
                    baseline_start_year=start_year,
                    baseline_end_year=end_year,
                    window_days=window_days,
                )
            except ValueError as exc:
                failures.append({"year": year, "event_name": name, "error": str(exc)})
                continue

            geocoded = None
            geocoding_payload = None
            location_query = None
            geocoding_url = None
            for query in weather_location_queries(
                {
                    "event_name": name,
                    "location": meeting.get("location"),
                    "circuit_short_name": meeting.get("circuit_short_name"),
                    "country_name": meeting.get("country_name"),
                }
            ):
                try:
                    payload = self.open_meteo.geocode(query)
                except Exception as exc:  # noqa: BLE001
                    failures.append(
                        {
                            "year": year,
                            "event_name": name,
                            "location_query": query,
                            "error": f"geocoding_failed: {exc}",
                        }
                    )
                    continue
                selected = select_geocoding_result(payload, str(meeting.get("country_name") or ""))
                if selected:
                    geocoded = selected
                    geocoding_payload = payload
                    location_query = query
                    geocoding_url = open_meteo_geocoding_url(query)
                    break
            if not geocoded:
                failures.append(
                    {
                        "year": year,
                        "event_name": name,
                        "location": meeting.get("location"),
                        "country_name": meeting.get("country_name"),
                        "error": "no_geocoding_match",
                    }
                )
                continue

            try:
                latitude = float(geocoded["latitude"])
                longitude = float(geocoded["longitude"])
                archive = self.open_meteo.historical_weather(
                    latitude=latitude,
                    longitude=longitude,
                    start_date=start_date,
                    end_date=end_date,
                    daily=["precipitation_sum", "rain_sum", "weather_code"],
                )
                archive_url = open_meteo_archive_url(latitude, longitude, start_date, end_date)
                payload = {
                    "year": year,
                    "event_name": name,
                    "official_name": meeting.get("meeting_official_name"),
                    "event_date": event_date,
                    "country_name": meeting.get("country_name"),
                    "location": meeting.get("location"),
                    "circuit_short_name": meeting.get("circuit_short_name"),
                    "location_query": location_query,
                    "geocoding_url": geocoding_url,
                    "geocoding_result": geocoded,
                    "geocoding_payload": geocoding_payload,
                    "archive_url": archive_url,
                    "archive": archive,
                    "baseline_start_year": start_year,
                    "baseline_end_year": end_year,
                    "window_days": window_days,
                    "target_year_weather_excluded": True,
                    "race_week_forecast": False,
                    "method": "same-week historical precipitation climate prior",
                }
                records.append(
                    self.store.write_json(
                        "weather_profiles",
                        f"{year}_{name}_open_meteo_climate",
                        payload,
                        {
                            "year": year,
                            "event_name": name,
                            "event_date": event_date,
                            "baseline_start_year": start_year,
                            "baseline_end_year": end_year,
                            "window_days": window_days,
                            "location_query": location_query,
                            "archive_url": archive_url,
                            "geocoding_url": geocoding_url,
                            "source": "open_meteo_archive_api",
                        },
                    )
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    {
                        "year": year,
                        "event_name": name,
                        "location_query": location_query,
                        "geocoding_result": geocoded,
                        "error": str(exc),
                    }
                )
        return IngestionResult(records, failures)

    def ingest_weather_forecasts(
        self,
        year: int,
        event_queries: list[str] | None = None,
        forecast_days: int = 16,
    ) -> IngestionResult:
        meetings = self.openf1.meetings(year=year)
        queries = [query.lower() for query in event_queries or [] if query]
        records: list[SnapshotRecord] = []
        failures: list[dict[str, Any]] = []

        for meeting in meetings:
            name = str(meeting.get("meeting_name", ""))
            if "testing" in name.lower() or bool(meeting.get("is_cancelled", False)):
                continue
            if queries and not any(self._matches_event(meeting, query) for query in queries):
                continue
            event_date = str(meeting.get("date_end") or meeting.get("date_start") or "")[:10]
            if not event_date:
                failures.append({"year": year, "event_name": name, "error": "missing_event_date"})
                continue

            geocoded, geocoding_payload, location_query, geocoding_url = self._geocode_weather_location(
                meeting,
                failures,
                year,
                name,
            )
            if not geocoded:
                continue

            try:
                latitude = float(geocoded["latitude"])
                longitude = float(geocoded["longitude"])
                forecast = self.open_meteo.forecast_weather(
                    latitude=latitude,
                    longitude=longitude,
                    daily=[
                        "precipitation_probability_max",
                        "precipitation_sum",
                        "rain_sum",
                        "weather_code",
                    ],
                    forecast_days=forecast_days,
                )
                daily = forecast.get("daily") if isinstance(forecast, dict) else None
                days = daily.get("time") if isinstance(daily, dict) else None
                if not isinstance(days, list) or event_date not in {str(day) for day in days}:
                    failures.append(
                        {
                            "year": year,
                            "event_name": name,
                            "event_date": event_date,
                            "location_query": location_query,
                            "error": "forecast_date_not_available",
                        }
                    )
                    continue
                forecast_url = open_meteo_forecast_url(latitude, longitude, forecast_days=forecast_days)
                payload = {
                    "year": year,
                    "event_name": name,
                    "official_name": meeting.get("meeting_official_name"),
                    "event_date": event_date,
                    "country_name": meeting.get("country_name"),
                    "location": meeting.get("location"),
                    "circuit_short_name": meeting.get("circuit_short_name"),
                    "location_query": location_query,
                    "geocoding_url": geocoding_url,
                    "geocoding_result": geocoded,
                    "geocoding_payload": geocoding_payload,
                    "forecast_url": forecast_url,
                    "forecast": forecast,
                    "forecast_days": forecast_days,
                    "target_year_weather_included": True,
                    "race_week_forecast": True,
                    "method": "Open-Meteo daily race-week precipitation forecast",
                }
                records.append(
                    self.store.write_json(
                        "weather_forecasts",
                        f"{year}_{name}_open_meteo_forecast",
                        payload,
                        {
                            "year": year,
                            "event_name": name,
                            "event_date": event_date,
                            "location_query": location_query,
                            "forecast_url": forecast_url,
                            "geocoding_url": geocoding_url,
                            "source": "open_meteo_forecast_api",
                            "forecast_days": forecast_days,
                        },
                    )
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    {
                        "year": year,
                        "event_name": name,
                        "location_query": location_query,
                        "geocoding_result": geocoded,
                        "error": str(exc),
                    }
                )
        return IngestionResult(records, failures)

    def _geocode_weather_location(
        self,
        meeting: dict[str, Any],
        failures: list[dict[str, Any]],
        year: int,
        name: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None, str | None]:
        for query in weather_location_queries(
            {
                "event_name": name,
                "location": meeting.get("location"),
                "circuit_short_name": meeting.get("circuit_short_name"),
                "country_name": meeting.get("country_name"),
            }
        ):
            try:
                payload = self.open_meteo.geocode(query)
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    {
                        "year": year,
                        "event_name": name,
                        "location_query": query,
                        "error": f"geocoding_failed: {exc}",
                    }
                )
                continue
            selected = select_geocoding_result(payload, str(meeting.get("country_name") or ""))
            if selected:
                return selected, payload, query, open_meteo_geocoding_url(query)
        failures.append(
            {
                "year": year,
                "event_name": name,
                "location": meeting.get("location"),
                "country_name": meeting.get("country_name"),
                "error": "no_geocoding_match",
            }
        )
        return None, None, None, None

    def _write_fastf1_result_payload(
        self,
        payload: dict[str, Any],
        year: int,
        event: str | int,
        session: str,
    ) -> SnapshotRecord:
        resolved_event = payload.get("resolved_event") or {}
        session_info = payload.get("session") or {}
        event_name = resolved_event.get("EventName") or str(event)
        session_name = session_info.get("name") or session
        return self.store.write_json(
            "fastf1",
            f"{year}_{event_name}_{session_name}_results",
            payload,
            {
                "year": year,
                "event": event,
                "resolved_event": event_name,
                "session": session,
                "session_name": session_name,
            },
        )

    def _race_slugs_from_official_calendar(self, year: int) -> list[str]:
        payload = self.f1_official.page_snapshot(page="calendar", year=year)
        html = str(payload.get("html") or "")
        return sorted(
            {
                match
                for match in re.findall(rf"/en/racing/{year}/([a-z0-9-]+)", html)
                if match
            }
        )

    @staticmethod
    def _matches_event(meeting: dict[str, Any], query: str) -> bool:
        needle = query.lower()
        fields = [
            str(meeting.get("meeting_name", "")),
            str(meeting.get("meeting_official_name", "")),
            str(meeting.get("location", "")),
            str(meeting.get("country_name", "")),
            str(meeting.get("circuit_short_name", "")),
        ]
        return any(needle in field.lower() for field in fields)

    @staticmethod
    def _parse_fastf1_utc(value: str):
        parsed = parse_dt(value)
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
