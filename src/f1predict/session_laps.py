"""Normalized FastF1 session lap summaries for point-in-time features."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any

from f1predict.results import normalize_event_name


@dataclass(frozen=True)
class NormalizedSessionLapSummary:
    year: int
    event_name: str
    round_number: int | None
    session_name: str
    session_key: str
    session_date: str | None
    captured_at: str
    source: str
    path: str
    driver_stats: list[dict[str, Any]]
    weather_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "event_name": self.event_name,
            "round_number": self.round_number,
            "session_name": self.session_name,
            "session_key": self.session_key,
            "session_date": self.session_date,
            "captured_at": self.captured_at,
            "source": self.source,
            "path": self.path,
            "driver_stats": self.driver_stats,
            "weather_summary": self.weather_summary,
        }


class FastF1SessionLapRepository:
    """Reads stored FastF1 lap snapshots and builds compact driver summaries."""

    def __init__(self, raw_root: Path | str = Path("data/raw")) -> None:
        self.raw_root = Path(raw_root)

    def latest_summaries_by_event(
        self,
        year: int,
        session_names: set[str] | None = None,
    ) -> dict[str, list[NormalizedSessionLapSummary]]:
        allowed = {self._session_key(name) for name in session_names} if session_names else None
        summaries: dict[tuple[str, str], NormalizedSessionLapSummary] = {}
        for meta_path, meta in self._iter_fastf1_lap_meta(year):
            payload_path = self._payload_path(meta_path, meta)
            if not payload_path.exists():
                continue
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            normalized = self._normalize_payload(payload, meta, payload_path)
            if normalized is None:
                continue
            if allowed is not None and normalized.session_key not in allowed:
                continue
            event_key = normalize_event_name(normalized.event_name)
            key = (event_key, normalized.session_key)
            previous = summaries.get(key)
            if previous is None or normalized.captured_at > previous.captured_at:
                summaries[key] = normalized

        by_event: dict[str, list[NormalizedSessionLapSummary]] = defaultdict(list)
        for (event_key, _), summary in summaries.items():
            by_event[event_key].append(summary)
        for rows in by_event.values():
            rows.sort(key=lambda row: (row.session_date or "", row.captured_at, row.session_key))
        return dict(by_event)

    def latest_for_event(
        self,
        year: int,
        event_name: str,
        session_names: set[str] | None = None,
    ) -> list[NormalizedSessionLapSummary]:
        return self.latest_summaries_by_event(year, session_names=session_names).get(
            normalize_event_name(event_name),
            [],
        )

    def _iter_fastf1_lap_meta(self, year: int) -> list[tuple[Path, dict[str, Any]]]:
        root = self.raw_root / "fastf1"
        if not root.exists():
            return []
        metas = []
        for meta_path in root.rglob("*.meta.json"):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("source") != "fastf1":
                continue
            dataset = str(meta.get("dataset", ""))
            if not dataset.endswith("_laps"):
                continue
            params = meta.get("params", {})
            if int(params.get("year", 0) or 0) != year:
                continue
            metas.append((meta_path, meta))
        return metas

    @staticmethod
    def _payload_path(meta_path: Path, meta: dict[str, Any]) -> Path:
        path = Path(str(meta.get("data_path", "")))
        if path.exists():
            return path
        return meta_path.with_name(meta_path.name.replace(".meta.json", ".json"))

    @classmethod
    def _normalize_payload(
        cls,
        payload: dict[str, Any],
        meta: dict[str, Any],
        payload_path: Path,
    ) -> NormalizedSessionLapSummary | None:
        rows = payload.get("laps")
        if not isinstance(rows, list) or not rows:
            return None

        event = payload.get("resolved_event") or {}
        session = payload.get("session") or {}
        session_name = str(session.get("name") or payload.get("requested_session") or "")
        driver_rows = payload.get("drivers") if isinstance(payload.get("drivers"), list) else []
        weather_rows = payload.get("weather") if isinstance(payload.get("weather"), list) else []
        driver_stats = cls._summarize_driver_laps(rows, driver_rows)
        if not driver_stats:
            return None
        return NormalizedSessionLapSummary(
            year=int(payload.get("year") or meta.get("params", {}).get("year")),
            event_name=str(event.get("EventName") or meta.get("params", {}).get("event") or ""),
            round_number=cls._as_int(event.get("RoundNumber")),
            session_name=session_name,
            session_key=cls._session_key(session_name),
            session_date=cls._session_date(session),
            captured_at=str(meta.get("captured_at", "")),
            source="fastf1",
            path=str(payload_path),
            driver_stats=driver_stats,
            weather_summary=cls._summarize_weather(weather_rows),
        )

    @classmethod
    def _summarize_driver_laps(
        cls,
        rows: list[dict[str, Any]],
        driver_rows: list[Any],
    ) -> list[dict[str, Any]]:
        driver_info = cls._driver_info_by_number(driver_rows)
        laps_by_driver: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            if not isinstance(row, dict):
                continue
            driver_number = str(row.get("DriverNumber") or "")
            if not driver_number:
                continue
            lap_time = cls._duration_seconds(row.get("LapTime"))
            if lap_time is None or lap_time < 45.0 or lap_time > 180.0:
                continue
            if cls._truthy(row.get("Deleted")):
                continue
            laps_by_driver[driver_number].append(
                {
                    "lap_time": lap_time,
                    "stint": cls._as_int(row.get("Stint")),
                    "compound": str(row.get("Compound") or ""),
                    "tyre_life": cls._as_float(row.get("TyreLife")),
                    "speed_st": cls._as_float(row.get("SpeedST")),
                    "is_accurate": bool(row.get("IsAccurate")),
                    "lap_number": cls._as_float(row.get("LapNumber")),
                }
            )

        output: list[dict[str, Any]] = []
        for driver_number, laps in sorted(laps_by_driver.items(), key=lambda item: int(item[0]) if item[0].isdigit() else 999):
            clean_laps = [lap for lap in laps if lap["is_accurate"]]
            if not clean_laps:
                continue
            lap_times = sorted(lap["lap_time"] for lap in clean_laps)
            long_run = cls._long_run_summary(clean_laps)
            speeds = [float(lap["speed_st"]) for lap in clean_laps if cls._as_float(lap.get("speed_st"))]
            info = driver_info.get(driver_number, {})
            output.append(
                {
                    "driver_number": driver_number,
                    "driver_id": info.get("driver_id"),
                    "abbreviation": info.get("abbreviation") or cls._driver_abbreviation(rows, driver_number),
                    "full_name": info.get("full_name"),
                    "team_id": info.get("team_id"),
                    "team_name": info.get("team_name"),
                    "lap_count": len(laps),
                    "clean_lap_count": len(clean_laps),
                    "fastest_lap_seconds": round(min(lap_times), 3),
                    "median_clean_lap_seconds": round(median(lap_times), 3),
                    "fast_5_avg_seconds": round(mean(lap_times[: min(5, len(lap_times))]), 3),
                    "long_run_lap_count": long_run["lap_count"],
                    "long_run_proxy_seconds": long_run["proxy_seconds"],
                    "long_run_compound": long_run["compound"],
                    "tyre_deg_proxy_seconds_per_lap": long_run["tyre_deg_proxy"],
                    "speed_st_avg_kph": round(mean(speeds), 2) if speeds else None,
                }
            )
        return output

    @staticmethod
    def _driver_info_by_number(driver_rows: list[Any]) -> dict[str, dict[str, Any]]:
        output: dict[str, dict[str, Any]] = {}
        for row in driver_rows:
            if not isinstance(row, dict):
                continue
            driver_number = str(row.get("DriverNumber") or "")
            if not driver_number:
                continue
            output[driver_number] = {
                "driver_id": row.get("DriverId"),
                "abbreviation": row.get("Abbreviation"),
                "full_name": row.get("FullName"),
                "team_id": row.get("TeamId"),
                "team_name": row.get("TeamName"),
            }
        return output

    @classmethod
    def _long_run_summary(cls, clean_laps: list[dict[str, Any]]) -> dict[str, Any]:
        stints: defaultdict[tuple[int | None, str], list[dict[str, Any]]] = defaultdict(list)
        for lap in clean_laps:
            compound = str(lap.get("compound") or "")
            if not compound or compound.upper() == "UNKNOWN":
                continue
            stints[(lap.get("stint"), compound)].append(lap)
        candidates = [laps for laps in stints.values() if len(laps) >= 3]
        if not candidates:
            return {"lap_count": 0, "proxy_seconds": None, "compound": None, "tyre_deg_proxy": None}
        selected = max(
            candidates,
            key=lambda laps: (len(laps), -median(lap["lap_time"] for lap in laps)),
        )
        selected = sorted(selected, key=lambda lap: lap.get("lap_number") or 0.0)
        times = [lap["lap_time"] for lap in selected]
        midpoint = max(1, len(times) // 2)
        early = times[:midpoint]
        late = times[midpoint:]
        deg = None
        if len(late) >= 2:
            deg = (mean(late) - mean(early)) / max(1, len(times) - 1)
        return {
            "lap_count": len(selected),
            "proxy_seconds": round(median(times), 3),
            "compound": selected[0].get("compound"),
            "tyre_deg_proxy": round(deg, 4) if deg is not None else None,
        }

    @staticmethod
    def _driver_abbreviation(rows: list[dict[str, Any]], driver_number: str) -> str | None:
        for row in rows:
            if str(row.get("DriverNumber") or "") == driver_number and row.get("Driver"):
                return str(row.get("Driver"))
        return None

    @classmethod
    def _summarize_weather(cls, rows: list[Any]) -> dict[str, Any]:
        if not rows:
            return {"sample_count": 0}

        def values(key: str) -> list[float]:
            return [
                float(row[key])
                for row in rows
                if isinstance(row, dict) and cls._as_float(row.get(key)) is not None
            ]

        rainfall_values = [
            row.get("Rainfall")
            for row in rows
            if isinstance(row, dict) and row.get("Rainfall") is not None
        ]
        rainfall_count = sum(1 for value in rainfall_values if bool(value))
        return {
            "sample_count": len(rows),
            "air_temp_avg": round(mean(values("AirTemp")), 2) if values("AirTemp") else None,
            "track_temp_avg": round(mean(values("TrackTemp")), 2) if values("TrackTemp") else None,
            "humidity_avg": round(mean(values("Humidity")), 2) if values("Humidity") else None,
            "rainfall_samples": rainfall_count,
            "rainfall_ratio": round(rainfall_count / len(rainfall_values), 3) if rainfall_values else 0.0,
        }

    @staticmethod
    def _duration_seconds(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text or text.lower() in {"nat", "nan", "none"}:
            return None
        iso_match = re.match(
            r"P(?P<days>-?\d+(?:\.\d+)?)D"
            r"T(?P<hours>\d+(?:\.\d+)?)H(?P<minutes>\d+(?:\.\d+)?)M(?P<seconds>\d+(?:\.\d+)?)S$",
            text,
        )
        if iso_match:
            return (
                float(iso_match.group("days")) * 86400.0
                + float(iso_match.group("hours")) * 3600.0
                + float(iso_match.group("minutes")) * 60.0
                + float(iso_match.group("seconds"))
            )
        match = re.match(
            r"(?:(?P<days>-?\d+)\s+days?\s+)?(?P<hours>\d+):(?P<minutes>\d+):(?P<seconds>\d+(?:\.\d+)?)$",
            text,
        )
        if not match:
            return None
        days = int(match.group("days") or 0)
        hours = int(match.group("hours"))
        minutes = int(match.group("minutes"))
        seconds = float(match.group("seconds"))
        return days * 86400.0 + hours * 3600.0 + minutes * 60.0 + seconds

    @staticmethod
    def _session_date(session: dict[str, Any]) -> str | None:
        raw = session.get("date")
        if raw is None:
            return None
        text = str(raw)
        if not text:
            return None
        if text.endswith("Z") or "+" in text:
            return text
        return f"{text}+00:00"

    @staticmethod
    def _session_key(value: str) -> str:
        compact = re.sub(r"[^a-z0-9]+", "", str(value).lower())
        aliases = {
            "fp1": "practice1",
            "practice1": "practice1",
            "p1": "practice1",
            "fp2": "practice2",
            "practice2": "practice2",
            "p2": "practice2",
            "fp3": "practice3",
            "practice3": "practice3",
            "p3": "practice3",
            "q": "qualifying",
            "qualifying": "qualifying",
            "sq": "sprintqualifying",
            "sprintqualifying": "sprintqualifying",
            "sprintshootout": "sprintqualifying",
            "s": "sprint",
            "sprint": "sprint",
            "r": "race",
            "race": "race",
        }
        return aliases.get(compact, compact)

    @staticmethod
    def _as_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _as_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _truthy(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes", "y"}
        return bool(value)
