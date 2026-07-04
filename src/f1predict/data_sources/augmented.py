"""Season data source that augments seed data with stored live snapshots."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from typing import Any

from f1predict.circuit_profiles import CircuitProfile, CircuitProfileProvider
from f1predict.data_sources.seed_loader import SeedDataSource
from f1predict.domain import Driver, MarketSnapshot, RaceEvent, SeasonState, parse_dt
from f1predict.features.calendar import CalendarBuilder
from f1predict.market_store import MarketSnapshotStore
from f1predict.race_profiles import F1OfficialRaceProfileProvider, RaceProfile
from f1predict.results import FastF1ResultRepository, NormalizedRaceResult, normalize_event_name
from f1predict.track_assets import TrackMapAsset, TrackMapAssetProvider
from f1predict.weather_profiles import (
    WeatherProfile,
    WeatherProfileProvider,
    safety_car_probability_from_track_type,
)


def _compact_key(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", ascii_value.lower())


class CalendarAugmentedDataSource:
    """Builds a replayable season from seed rosters plus calendar/result snapshots.

    Seed data remains the source for teams, drivers, handcrafted future events,
    and seed market snapshots. OpenF1 calendar rows fill missing events, while
    FastF1 result snapshots provide canonical completed-race order when present.
    """

    def __init__(
        self,
        seed_source: SeedDataSource | None = None,
        calendar_builder: CalendarBuilder | None = None,
        result_repository: FastF1ResultRepository | None = None,
        market_store: MarketSnapshotStore | None = None,
        circuit_profile_provider: CircuitProfileProvider | None = None,
        race_profile_provider: F1OfficialRaceProfileProvider | None = None,
        weather_profile_provider: WeatherProfileProvider | None = None,
        track_asset_provider: TrackMapAssetProvider | None = None,
        year: int | None = None,
    ) -> None:
        self.seed_source = seed_source or SeedDataSource()
        self.calendar_builder = calendar_builder or CalendarBuilder()
        self.result_repository = result_repository or FastF1ResultRepository()
        self.market_store = market_store or MarketSnapshotStore()
        self.circuit_profile_provider = circuit_profile_provider or CircuitProfileProvider()
        self.race_profile_provider = race_profile_provider or F1OfficialRaceProfileProvider()
        self.weather_profile_provider = weather_profile_provider or WeatherProfileProvider()
        self.track_asset_provider = track_asset_provider or TrackMapAssetProvider()
        self.year = year

    def load(self) -> SeasonState:
        base = self.seed_source.load()
        year = self.year or base.season
        results = self.result_repository.latest_results_by_event(year)
        driver_lookup = self._driver_lookup(base.drivers)
        try:
            calendar = self.calendar_builder.build_from_openf1(year)
        except ValueError:
            calendar = []
        calendar_by_key = {
            normalize_event_name(str(item.get("event_name", ""))): item
            for item in calendar
            if not bool(item.get("is_cancelled", False))
        }

        events = [
            self._canonicalize_seed_event(
                event,
                results,
                calendar_by_key.get(normalize_event_name(event.name)),
                driver_lookup,
            )
            for event in base.events
        ]
        known = {normalize_event_name(event.name) for event in events}

        for item in calendar:
            if bool(item.get("is_cancelled", False)):
                continue
            key = normalize_event_name(str(item.get("event_name", "")))
            if not key or key in known:
                continue
            events.append(self._event_from_calendar(item, results.get(key), driver_lookup))
            known.add(key)

        events.sort(key=lambda event: (event.round_number, event.date, event.event_id))
        return SeasonState(
            season=base.season,
            teams=base.teams,
            drivers=base.drivers,
            events=events,
            markets=self._merge_markets(base.markets, self.market_store.load_all()),
        )

    @staticmethod
    def _merge_markets(*groups: list[MarketSnapshot]) -> list[MarketSnapshot]:
        merged: dict[tuple[str, str], MarketSnapshot] = {}
        for group in groups:
            for market in group:
                merged[(market.market_id, market.captured_at)] = market
        return sorted(
            merged.values(),
            key=lambda market: (market.event_id, market.market_type, market.market_id, market.captured_at),
        )

    def _canonicalize_seed_event(
        self,
        event: RaceEvent,
        results: dict[str, NormalizedRaceResult],
        calendar_item: dict[str, Any] | None,
        driver_lookup: dict[str, str],
    ) -> RaceEvent:
        event = self._event_with_calendar_profile(event, calendar_item)
        result = results.get(normalize_event_name(event.name))
        round_number = int(calendar_item.get("round_number")) if calendar_item else event.round_number
        date = self._event_date(calendar_item) if calendar_item else event.date
        if result is None:
            return replace(event, round_number=round_number, date=date)

        actual_result = self._actual_result(result, driver_lookup)
        if not actual_result:
            return replace(event, round_number=round_number, date=date)

        feature_refs = dict(event.feature_refs)
        if event.actual_result and event.actual_result != actual_result:
            feature_refs["source_actual_result"] = {
                "seed": event.actual_result,
                "fastf1": actual_result,
                "fastf1_path": result.path,
            }
        feature_refs.setdefault("result_source", {"source": "fastf1", "path": result.path})
        return replace(
            event,
            round_number=round_number,
            date=date,
            completed=True,
            actual_result=actual_result,
            feature_refs=feature_refs,
        )

    def _event_with_calendar_profile(
        self,
        event: RaceEvent,
        calendar_item: dict[str, Any] | None,
    ) -> RaceEvent:
        if calendar_item is None:
            return event
        key = normalize_event_name(str(calendar_item.get("event_name") or event.name))
        circuit_profile = self.circuit_profile_provider.load_for_calendar_item(calendar_item)
        race_profile = self.race_profile_provider.load_for_calendar_item(calendar_item)
        weather_profile = self.weather_profile_provider.load_for_calendar_item(calendar_item)
        track_asset = self.track_asset_provider.load_for_event_id(self._event_id(str(calendar_item.get("event_name") or event.name)))
        track_type, track_type_provenance = self._track_type_profile(calendar_item, key, circuit_profile)
        laps, laps_provenance = self._laps_profile(key, race_profile)
        weather_prior, weather_provenance = self._weather_profile(key, track_type, weather_profile)
        feature_refs = dict(event.feature_refs)
        feature_refs.setdefault("calendar_source", "openf1")
        provenance = feature_refs.get("event_input_provenance")
        if not isinstance(provenance, dict):
            provenance = {}
        provenance.update(
            self._event_input_provenance(
                calendar_item,
                key,
                None,
                circuit_profile,
                track_asset,
                track_type_provenance,
                laps_provenance,
                weather_provenance,
            )
        )
        feature_refs["event_input_provenance"] = provenance
        if circuit_profile:
            feature_refs["circuit_profile"] = circuit_profile.provenance()
        if track_asset:
            feature_refs["track_map_asset"] = track_asset.provenance()
        if race_profile:
            feature_refs["race_profile"] = race_profile.laps_provenance()
        if weather_profile:
            feature_refs["weather_profile"] = weather_profile.provenance(track_type)
        return replace(
            event,
            round_number=int(calendar_item.get("round_number") or event.round_number),
            date=self._event_date(calendar_item),
            track_type=track_type,
            laps=laps,
            weather_prior=weather_prior,
            track_map=circuit_profile.track_map if circuit_profile else event.track_map,
            feature_refs=feature_refs,
        )

    def _event_from_calendar(
        self,
        item: dict[str, Any],
        result: NormalizedRaceResult | None,
        driver_lookup: dict[str, str],
    ) -> RaceEvent:
        event_name = str(item.get("event_name", "Unknown Grand Prix"))
        key = normalize_event_name(event_name)
        circuit_profile = self.circuit_profile_provider.load_for_calendar_item(item)
        race_profile = self.race_profile_provider.load_for_calendar_item(item)
        track_asset = self.track_asset_provider.load_for_event_id(self._event_id(event_name))
        track_type, track_type_provenance = self._track_type_profile(item, key, circuit_profile)
        laps, laps_provenance = self._laps_profile(key, race_profile)
        weather_profile = self.weather_profile_provider.load_for_calendar_item(item)
        weather_prior, weather_provenance = self._weather_profile(key, track_type, weather_profile)
        actual_result = self._actual_result(result, driver_lookup) if result else []
        feature_refs: dict[str, Any] = {
            "event_source": "openf1_calendar_generated",
            "calendar_source": "openf1",
            "event_input_provenance": self._event_input_provenance(
                item,
                key,
                result,
                circuit_profile,
                track_asset,
                track_type_provenance,
                laps_provenance,
                weather_provenance,
            ),
        }
        if circuit_profile:
            feature_refs["circuit_profile"] = circuit_profile.provenance()
        if track_asset:
            feature_refs["track_map_asset"] = track_asset.provenance()
        if race_profile:
            feature_refs["race_profile"] = race_profile.laps_provenance()
        if weather_profile:
            feature_refs["weather_profile"] = weather_profile.provenance(track_type)
        if result:
            feature_refs["result_source"] = {"source": "fastf1", "path": result.path}

        return RaceEvent(
            event_id=self._event_id(event_name),
            name=event_name,
            round_number=int(item.get("round_number") or result.round_number if result else item.get("round_number") or 0),
            date=self._event_date(item),
            track_type=track_type,
            laps=laps,
            completed=bool(actual_result),
            weather_prior=weather_prior,
            track_map=circuit_profile.track_map if circuit_profile else self._track_map(track_type),
            actual_result=actual_result,
            feature_refs=feature_refs,
        )

    @staticmethod
    def _event_input_provenance(
        item: dict[str, Any],
        key: str,
        result: NormalizedRaceResult | None,
        circuit_profile: CircuitProfile | None,
        track_asset: TrackMapAsset | None,
        track_type_provenance: dict[str, Any],
        laps_provenance: dict[str, Any],
        weather_provenance: dict[str, Any],
    ) -> dict[str, Any]:
        calendar_fields = {
            "event_name": "event_name",
            "round_number": "round_number",
            "date_start": "date_start",
            "date_end": "date_end",
        }
        provenance: dict[str, Any] = {
            field: {
                "source": "openf1_calendar",
                "source_field": source_field,
                "quality": "verified",
            }
            for field, source_field in calendar_fields.items()
            if item.get(source_field)
        }
        if result:
            provenance["actual_result"] = {
                "source": "fastf1_result_snapshot",
                "path": result.path,
                "quality": "verified",
            }

        provenance["track_type"] = track_type_provenance
        provenance["laps"] = laps_provenance
        provenance["weather_prior"] = weather_provenance
        if circuit_profile:
            provenance["circuit_geometry"] = circuit_profile.provenance()
            provenance["track_map"] = circuit_profile.provenance()
        else:
            provenance["track_map"] = {
                "source": "generic_track_type_template",
                "quality": "placeholder",
            }
        if track_asset:
            provenance["track_map_asset"] = track_asset.provenance()
        return provenance

    def _laps_profile(self, key: str, race_profile: RaceProfile | None) -> tuple[int, dict[str, Any]]:
        if race_profile and race_profile.planned_laps is not None:
            return race_profile.planned_laps, race_profile.laps_provenance()
        return self._laps(key), {
            "source": "static_event_lookup",
            "quality": "heuristic",
        }

    def _weather_profile(
        self,
        key: str,
        track_type: str,
        weather_profile: WeatherProfile | None,
    ) -> tuple[dict[str, float], dict[str, Any]]:
        if weather_profile:
            return weather_profile.weather_prior(track_type), weather_profile.provenance(track_type)
        return self._weather_prior(key, track_type), {
            "source": "static_event_lookup",
            "quality": "heuristic",
        }

    def _track_type_profile(
        self,
        item: dict[str, Any],
        key: str,
        circuit_profile: CircuitProfile | None,
    ) -> tuple[str, dict[str, Any]]:
        circuit_type = str(item.get("circuit_type") or "")
        if circuit_profile:
            return circuit_profile.track_type_cluster(circuit_type)
        return self._track_type(item, key), {
            "source": "openf1_circuit_type_plus_event_alias"
            if circuit_type
            else "event_alias_heuristic",
            "source_field": "circuit_type" if circuit_type else key,
            "quality": "heuristic",
        }

    @staticmethod
    def _actual_result(result: NormalizedRaceResult | None, driver_lookup: dict[str, str]) -> list[str]:
        if result is None:
            return []
        mapped = []
        for row in result.classified:
            raw_id = str(row.get("driver_id") or "")
            full_name = str(row.get("full_name") or "")
            candidates = [
                raw_id,
                full_name,
                full_name.split()[-1] if full_name.split() else "",
            ]
            driver_id = next((driver_lookup[key] for key in map(_compact_key, candidates) if key in driver_lookup), raw_id)
            if driver_id:
                mapped.append(driver_id)
        return mapped

    @staticmethod
    def _driver_lookup(drivers: dict[str, Driver]) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for driver in drivers.values():
            names = [
                driver.driver_id,
                driver.name,
                driver.name.split()[-1] if driver.name.split() else "",
            ]
            for name in names:
                key = _compact_key(name)
                if key:
                    lookup[key] = driver.driver_id
        return lookup

    @staticmethod
    def _event_id(event_name: str) -> str:
        ascii_name = unicodedata.normalize("NFKD", event_name).encode("ascii", "ignore").decode("ascii")
        name = re.sub(r"\bgrand prix\b", "", ascii_name, flags=re.IGNORECASE)
        words = re.findall(r"[A-Za-z0-9]+", name.lower())
        return "_".join(words + ["gp"]) if words else "generated_gp"

    @staticmethod
    def _event_date(item: dict[str, Any] | None) -> str:
        if item is None:
            return ""
        for field in ("date_end", "date_start"):
            parsed = parse_dt(str(item.get(field) or ""))
            if parsed is not None:
                return parsed.date().isoformat()
        return str(item.get("date_end") or item.get("date_start") or "")[:10]

    @staticmethod
    def _track_type(item: dict[str, Any], key: str) -> str:
        circuit_type = str(item.get("circuit_type", "")).lower()
        street_events = {
            "australian",
            "miami",
            "monaco",
            "azerbaijan",
            "singapore",
            "lasvegas",
            "spanish",
        }
        high_speed_events = {"british", "belgian", "italian", "austrian", "saudiarabian"}
        technical_events = {"japanese", "barcelona", "hungarian", "dutch"}
        power_events = {"bahrain", "chinese", "canadian", "mexicocity", "qatar", "abudhabi"}

        if "street" in circuit_type or key in street_events:
            return "street"
        if key in high_speed_events:
            return "high_speed"
        if key in technical_events:
            return "technical"
        if key in power_events:
            return "power"
        return "technical" if "permanent" in circuit_type else "power"

    @staticmethod
    def _laps(key: str) -> int:
        laps_by_event = {
            "australian": 58,
            "chinese": 56,
            "japanese": 53,
            "bahrain": 57,
            "saudiarabian": 50,
            "miami": 57,
            "canadian": 70,
            "monaco": 78,
            "barcelona": 66,
            "austrian": 71,
            "british": 52,
            "belgian": 44,
            "hungarian": 70,
            "dutch": 72,
            "italian": 53,
            "spanish": 57,
            "azerbaijan": 51,
            "singapore": 62,
            "unitedstates": 56,
            "mexicocity": 71,
            "saopaulo": 71,
            "lasvegas": 50,
            "qatar": 57,
            "abudhabi": 58,
        }
        return laps_by_event.get(key, 57)

    @staticmethod
    def _weather_prior(key: str, track_type: str) -> dict[str, float]:
        wet_by_event = {
            "australian": 0.18,
            "chinese": 0.10,
            "japanese": 0.26,
            "miami": 0.20,
            "canadian": 0.22,
            "monaco": 0.12,
            "barcelona": 0.16,
            "austrian": 0.21,
            "british": 0.34,
            "belgian": 0.39,
            "dutch": 0.28,
            "singapore": 0.30,
            "saopaulo": 0.32,
        }
        return {
            "wet_probability": wet_by_event.get(key, 0.18),
            "safety_car_probability": safety_car_probability_from_track_type(track_type),
        }

    @staticmethod
    def _track_map(track_type: str) -> list[tuple[float, float]]:
        maps = {
            "street": [
                (0.10, 0.64),
                (0.18, 0.38),
                (0.36, 0.30),
                (0.58, 0.35),
                (0.78, 0.50),
                (0.72, 0.74),
                (0.48, 0.82),
                (0.22, 0.76),
                (0.10, 0.64),
            ],
            "high_speed": [
                (0.08, 0.58),
                (0.22, 0.42),
                (0.44, 0.30),
                (0.70, 0.36),
                (0.86, 0.54),
                (0.70, 0.76),
                (0.42, 0.80),
                (0.18, 0.70),
                (0.08, 0.58),
            ],
            "power": [
                (0.14, 0.56),
                (0.22, 0.34),
                (0.48, 0.28),
                (0.78, 0.42),
                (0.82, 0.62),
                (0.60, 0.76),
                (0.32, 0.72),
                (0.14, 0.56),
            ],
            "technical": [
                (0.08, 0.56),
                (0.20, 0.44),
                (0.32, 0.56),
                (0.46, 0.40),
                (0.62, 0.52),
                (0.76, 0.34),
                (0.88, 0.50),
                (0.74, 0.72),
                (0.50, 0.82),
                (0.26, 0.72),
                (0.08, 0.56),
            ],
        }
        return maps.get(track_type, maps["technical"])
