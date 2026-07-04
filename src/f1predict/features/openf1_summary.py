"""Feature summaries from stored OpenF1 raw snapshots."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

from f1predict.storage import RawSnapshotStore


class OpenF1SummaryBuilder:
    def __init__(
        self,
        raw_root: Path | str = Path("data/raw"),
        processed_root: Path | str = Path("data/processed"),
    ) -> None:
        self.raw_root = Path(raw_root)
        self.processed_root = Path(processed_root)

    def build_event_summary(self, year: int, event_query: str) -> dict[str, Any]:
        prefix = f"{year}_{event_query}"
        source_root = self.raw_root / "openf1"
        if not source_root.exists():
            raise ValueError(f"No OpenF1 raw root found: {source_root}")

        summary: dict[str, Any] = {
            "year": year,
            "event_query": event_query,
            "sessions": {},
            "source_files": [],
        }

        for dataset_dir in sorted(source_root.iterdir()):
            if not dataset_dir.is_dir() or not dataset_dir.name.startswith(prefix):
                continue
            latest = self._latest_json(dataset_dir)
            if latest is None or latest.name.endswith(".meta.json"):
                continue
            payload = json.loads(latest.read_text(encoding="utf-8"))
            summary["source_files"].append(str(latest))
            dataset = dataset_dir.name
            if dataset.endswith("_laps"):
                session = self._session_name(dataset, prefix, "_laps")
                summary["sessions"].setdefault(session, {})["laps"] = self._summarize_laps(payload)
            elif dataset.endswith("_weather"):
                session = self._session_name(dataset, prefix, "_weather")
                summary["sessions"].setdefault(session, {})["weather"] = self._summarize_weather(payload)
            elif dataset.endswith("_race_control"):
                session = self._session_name(dataset, prefix, "_race_control")
                summary["sessions"].setdefault(session, {})["race_control"] = self._summarize_race_control(payload)
            elif dataset.endswith("_stints"):
                session = self._session_name(dataset, prefix, "_stints")
                summary["sessions"].setdefault(session, {})["stints"] = self._summarize_stints(payload)
            elif dataset.endswith("_sessions"):
                summary["session_metadata"] = payload
            elif dataset.endswith("_meetings"):
                summary["meeting_metadata"] = payload

        if not summary["sessions"]:
            raise ValueError(f"No OpenF1 session snapshots matched {prefix!r}")
        return summary

    def write_event_summary(self, year: int, event_query: str) -> Path:
        summary = self.build_event_summary(year, event_query)
        store = RawSnapshotStore(self.processed_root)
        record = store.write_json("openf1", f"{year}_{event_query}_summary", summary)
        return record.path

    @staticmethod
    def _latest_json(dataset_dir: Path) -> Path | None:
        files = [path for path in dataset_dir.rglob("*.json") if not path.name.endswith(".meta.json")]
        if not files:
            return None
        return max(files, key=lambda path: path.stat().st_mtime)

    @staticmethod
    def _session_name(dataset: str, prefix: str, suffix: str) -> str:
        value = dataset.removeprefix(prefix).removesuffix(suffix).strip("_")
        return value or "session"

    @staticmethod
    def _summarize_laps(rows: list[dict[str, Any]]) -> dict[str, Any]:
        by_driver: defaultdict[str, list[float]] = defaultdict(list)
        for row in rows:
            duration = row.get("lap_duration")
            driver_number = row.get("driver_number")
            if duration is None or driver_number is None:
                continue
            by_driver[str(driver_number)].append(float(duration))

        drivers = {}
        for driver_number, laps in by_driver.items():
            clean = sorted(laps)
            drivers[driver_number] = {
                "lap_count": len(clean),
                "fastest_lap": round(min(clean), 3),
                "median_lap": round(median(clean), 3),
                "fast_10_avg": round(mean(clean[: min(len(clean), 10)]), 3),
            }
        fastest = sorted(
            (
                {"driver_number": driver, **stats}
                for driver, stats in drivers.items()
            ),
            key=lambda item: item["fastest_lap"],
        )
        return {
            "lap_count": len(rows),
            "driver_count": len(drivers),
            "fastest_drivers": fastest[:10],
        }

    @staticmethod
    def _summarize_weather(rows: list[dict[str, Any]]) -> dict[str, Any]:
        def values(key: str) -> list[float]:
            return [float(row[key]) for row in rows if row.get(key) is not None]

        rainfall = values("rainfall")
        return {
            "sample_count": len(rows),
            "air_temp_avg": round(mean(values("air_temperature")), 2) if values("air_temperature") else None,
            "track_temp_avg": round(mean(values("track_temperature")), 2) if values("track_temperature") else None,
            "rainfall_samples": sum(1 for value in rainfall if value > 0),
            "rainfall_ratio": round(sum(1 for value in rainfall if value > 0) / len(rainfall), 3) if rainfall else 0.0,
            "humidity_avg": round(mean(values("humidity")), 2) if values("humidity") else None,
        }

    @staticmethod
    def _summarize_race_control(rows: list[dict[str, Any]]) -> dict[str, Any]:
        categories = Counter(str(row.get("category", "unknown")) for row in rows)
        flags = Counter(str(row.get("flag", "none")) for row in rows if row.get("flag"))
        return {
            "message_count": len(rows),
            "categories": dict(categories.most_common()),
            "flags": dict(flags.most_common()),
        }

    @staticmethod
    def _summarize_stints(rows: list[dict[str, Any]]) -> dict[str, Any]:
        compounds = Counter(str(row.get("compound", "unknown")) for row in rows)
        return {
            "stint_count": len(rows),
            "compounds": dict(compounds.most_common()),
        }
