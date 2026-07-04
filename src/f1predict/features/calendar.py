"""Calendar normalization for chronological replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from f1predict.storage import RawSnapshotStore


class CalendarBuilder:
    def __init__(
        self,
        raw_root: Path | str = Path("data/raw"),
        processed_root: Path | str = Path("data/processed"),
    ) -> None:
        self.raw_root = Path(raw_root)
        self.processed_root = Path(processed_root)

    def build_from_openf1(self, year: int) -> list[dict[str, Any]]:
        meetings = self._latest_openf1_year_meetings(year)
        races = []
        round_number = 1
        for meeting in sorted(meetings, key=lambda item: item.get("date_start", "")):
            name = str(meeting.get("meeting_name", ""))
            if "testing" in name.lower():
                continue
            races.append(
                {
                    "round_number": round_number,
                    "meeting_key": meeting.get("meeting_key"),
                    "event_name": name,
                    "official_name": meeting.get("meeting_official_name"),
                    "country_name": meeting.get("country_name"),
                    "country_code": meeting.get("country_code"),
                    "location": meeting.get("location"),
                    "circuit_key": meeting.get("circuit_key"),
                    "circuit_short_name": meeting.get("circuit_short_name"),
                    "circuit_type": meeting.get("circuit_type"),
                    "circuit_info_url": meeting.get("circuit_info_url"),
                    "circuit_image": meeting.get("circuit_image"),
                    "gmt_offset": meeting.get("gmt_offset"),
                    "date_start": meeting.get("date_start"),
                    "date_end": meeting.get("date_end"),
                    "year": year,
                    "is_cancelled": meeting.get("is_cancelled", False),
                }
            )
            round_number += 1
        return races

    def write_openf1_calendar(self, year: int) -> Path:
        calendar = self.build_from_openf1(year)
        store = RawSnapshotStore(self.processed_root)
        record = store.write_json("calendar", f"{year}_openf1_calendar", calendar, {"year": year})
        return record.path

    def _latest_openf1_year_meetings(self, year: int) -> list[dict[str, Any]]:
        dataset_dir = self.raw_root / "openf1" / f"{year}_meetings"
        files = []
        if dataset_dir.exists():
            files = [path for path in dataset_dir.rglob("*.json") if not path.name.endswith(".meta.json")]
        if not files:
            raise ValueError(
                f"No OpenF1 yearly meetings snapshot for {year}. "
                f"Run `python -m f1predict.cli ingest-openf1-calendar --year {year}` first."
            )
        latest = max(files, key=lambda path: path.stat().st_mtime)
        return json.loads(latest.read_text(encoding="utf-8"))
