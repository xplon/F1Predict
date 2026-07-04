"""FastF1 adapter.

FastF1 is installed in the project virtual environment. This module keeps the
dependency behind a small boundary so data ingestion can fail clearly if a user
has not installed project dependencies yet.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import re
import unicodedata


class FastF1UnavailableError(RuntimeError):
    """Raised when FastF1 is not installed in the active environment."""


class FastF1Client:
    def __init__(self, cache_dir: Path | str = Path("data/cache/fastf1")) -> None:
        self.cache_dir = Path(cache_dir)
        self.fastf1 = self._import_fastf1()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.fastf1.Cache.enable_cache(str(self.cache_dir))

    def event_schedule(self, year: int) -> list[dict[str, Any]]:
        schedule = self.fastf1.get_event_schedule(year)
        return [self._jsonable_row(row) for _, row in schedule.iterrows()]

    def event_metadata(self, year: int, event: str | int, session: str = "R") -> dict[str, Any]:
        session_obj = self.fastf1.get_session(year, event, session)
        return self._jsonable_row(session_obj.event)

    def session_results(self, year: int, event: str | int, session: str = "R") -> dict[str, Any]:
        session_obj = self.fastf1.get_session(year, event, session)
        self._validate_resolved_event(event, self._jsonable_row(session_obj.event))
        session_obj.load(laps=False, telemetry=False, weather=False, messages=False)
        result_rows = [self._jsonable_row(row) for _, row in session_obj.results.iterrows()]
        return {
            "year": year,
            "event_query": event,
            "requested_session": session,
            "resolved_event": self._jsonable_row(session_obj.event),
            "session": {
                "name": getattr(session_obj, "name", session),
                "date": self._jsonable_value(getattr(session_obj, "date", None)),
                "api_path": getattr(session_obj, "api_path", None),
            },
            "results": result_rows,
        }

    def race_results(self, year: int, event: str | int) -> dict[str, Any]:
        return self.session_results(year=year, event=event, session="R")

    @staticmethod
    def _import_fastf1():
        try:
            import fastf1  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise FastF1UnavailableError(
                "FastF1 is not available. Run `.\\.venv\\Scripts\\python.exe -m pip install -e .` "
                "or install project dependencies in your active environment."
            ) from exc
        return fastf1

    @staticmethod
    def _jsonable_row(row) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in row.items():
            result[str(key)] = FastF1Client._jsonable_value(value)
        return result

    @staticmethod
    def _jsonable_value(value: Any) -> Any:
        if value is None:
            return None
        try:
            import pandas as pd  # type: ignore

            if pd.isna(value):
                return None
        except Exception:  # noqa: BLE001
            pass
        if hasattr(value, "item"):
            try:
                value = value.item()
            except Exception:  # noqa: BLE001
                pass
        if hasattr(value, "isoformat"):
            try:
                return value.isoformat()
            except Exception:  # noqa: BLE001
                pass
        if hasattr(value, "total_seconds") and not isinstance(value, (int, float)):
            return str(value)
        return value

    @staticmethod
    def _validate_resolved_event(requested: str | int, resolved_event: dict[str, Any]) -> None:
        if isinstance(requested, int):
            return
        query = FastF1Client._normalize_name(requested)
        fields = [
            str(resolved_event.get("EventName", "")),
            str(resolved_event.get("OfficialEventName", "")),
            str(resolved_event.get("Location", "")),
            str(resolved_event.get("Country", "")),
        ]
        if any(query and query in FastF1Client._normalize_name(field) for field in fields):
            return
        resolved_name = resolved_event.get("EventName", "unknown event")
        raise ValueError(
            f"FastF1 resolved requested event {requested!r} to {resolved_name!r}. "
            "Use the exact FastF1 event name or the round number."
        )

    @staticmethod
    def _normalize_name(value: str) -> str:
        ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        ascii_value = ascii_value.lower().replace("&", "and")
        return re.sub(r"[^a-z0-9]+", "", ascii_value)
