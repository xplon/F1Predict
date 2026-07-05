"""Normalized access to stored race result snapshots."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def normalize_event_name(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    value = ascii_name.lower().replace("&", "and")
    value = re.sub(r"\bgrand prix\b", "", value)
    return re.sub(r"[^a-z0-9]+", "", value)


@dataclass(frozen=True)
class NormalizedRaceResult:
    year: int
    event_name: str
    round_number: int | None
    session_name: str
    session_date: str | None
    captured_at: str
    source: str
    path: str
    winner_driver_id: str | None
    winner_name: str | None
    classified: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "event_name": self.event_name,
            "round_number": self.round_number,
            "session_name": self.session_name,
            "session_date": self.session_date,
            "captured_at": self.captured_at,
            "source": self.source,
            "path": self.path,
            "winner_driver_id": self.winner_driver_id,
            "winner_name": self.winner_name,
            "classified": self.classified,
        }


class FastF1ResultRepository:
    """Reads the latest FastF1 raw snapshots and normalizes race results."""

    def __init__(self, raw_root: Path | str = Path("data/raw")) -> None:
        self.raw_root = Path(raw_root)

    def latest_results_by_event(self, year: int) -> dict[str, NormalizedRaceResult]:
        return self.latest_session_results_by_event(year, session_names={"race", "r"})

    def latest_session_results_by_event(
        self,
        year: int,
        session_names: set[str] | None = None,
    ) -> dict[str, NormalizedRaceResult]:
        results: dict[str, NormalizedRaceResult] = {}
        allowed = {self._session_key(name) for name in session_names} if session_names else None
        for meta_path, meta in self._iter_fastf1_meta(year):
            dataset = str(meta.get("dataset", ""))
            if not dataset.endswith("_results"):
                continue
            payload_path = self._payload_path(meta_path, meta)
            if not payload_path.exists():
                continue
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            normalized = self._normalize_payload(payload, meta, payload_path)
            if normalized is None:
                continue
            if allowed is not None and self._session_key(normalized.session_name) not in allowed:
                continue
            key = normalize_event_name(normalized.event_name)
            previous = results.get(key)
            if previous is None or normalized.captured_at > previous.captured_at:
                results[key] = normalized
        return results

    def latest_result_for_event(self, year: int, event_name: str) -> NormalizedRaceResult | None:
        return self.latest_results_by_event(year).get(normalize_event_name(event_name))

    def latest_schedule_by_event(self, year: int) -> dict[str, dict[str, Any]]:
        rows = self.latest_schedule(year)
        by_event: dict[str, dict[str, Any]] = {}
        for row in rows:
            if str(row.get("EventFormat", "")).lower() == "testing":
                continue
            event_name = str(row.get("EventName", ""))
            if event_name:
                by_event[normalize_event_name(event_name)] = row
        return by_event

    def latest_schedule(self, year: int) -> list[dict[str, Any]]:
        dataset_dir = self.raw_root / "fastf1" / f"{year}_schedule"
        files = []
        if dataset_dir.exists():
            files = [path for path in dataset_dir.rglob("*.json") if not path.name.endswith(".meta.json")]
        if not files:
            return []
        latest = max(files, key=lambda path: path.stat().st_mtime)
        return json.loads(latest.read_text(encoding="utf-8"))

    def _iter_fastf1_meta(self, year: int) -> list[tuple[Path, dict[str, Any]]]:
        root = self.raw_root / "fastf1"
        if not root.exists():
            return []
        metas = []
        for meta_path in root.rglob("*.meta.json"):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("source") != "fastf1":
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

    @staticmethod
    def _normalize_payload(
        payload: dict[str, Any],
        meta: dict[str, Any],
        payload_path: Path,
    ) -> NormalizedRaceResult | None:
        rows = payload.get("results")
        if not isinstance(rows, list) or not rows:
            return None

        event = payload.get("resolved_event") or {}
        session = payload.get("session") or {}
        classified = [FastF1ResultRepository._normalize_row(row) for row in rows if isinstance(row, dict)]
        classified = sorted(classified, key=lambda row: row.get("position") or 999)
        winner = next((row for row in classified if row.get("position") == 1), None)
        if winner is None and classified:
            winner = classified[0]

        return NormalizedRaceResult(
            year=int(payload.get("year") or meta.get("params", {}).get("year")),
            event_name=str(event.get("EventName") or meta.get("params", {}).get("event") or ""),
            round_number=FastF1ResultRepository._as_int(event.get("RoundNumber")),
            session_name=str(session.get("name") or payload.get("requested_session") or ""),
            session_date=FastF1ResultRepository._session_date(session),
            captured_at=str(meta.get("captured_at", "")),
            source="fastf1",
            path=str(payload_path),
            winner_driver_id=str(winner.get("driver_id")) if winner and winner.get("driver_id") else None,
            winner_name=str(winner.get("full_name")) if winner and winner.get("full_name") else None,
            classified=classified,
        )

    @staticmethod
    def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "position": FastF1ResultRepository._as_int(row.get("Position")),
            "classified_position": row.get("ClassifiedPosition"),
            "driver_id": row.get("DriverId"),
            "driver_number": row.get("DriverNumber"),
            "abbreviation": row.get("Abbreviation"),
            "full_name": row.get("FullName"),
            "team_id": row.get("TeamId"),
            "team_name": row.get("TeamName"),
            "grid_position": FastF1ResultRepository._as_int(row.get("GridPosition")),
            "status": row.get("Status"),
            "points": FastF1ResultRepository._as_float(row.get("Points")),
            "laps": FastF1ResultRepository._as_int(row.get("Laps")),
        }

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
    def _session_key(value: str) -> str:
        compact = re.sub(r"[^a-z0-9]+", "", str(value).lower())
        aliases = {
            "r": "race",
            "race": "race",
            "s": "sprint",
            "sprint": "sprint",
            "sprints": "sprint",
        }
        return aliases.get(compact, compact)
