"""Parse F1 official standings snapshots into audited structured rows."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from f1predict.domain import Driver, SeasonState, Team, parse_dt, utc_now
from f1predict.storage import RawSnapshotStore


@dataclass(frozen=True)
class OfficialDriverStanding:
    position: int
    official_driver_id: str
    driver_slug: str
    driver_name: str
    nationality: str
    team_name: str
    official_team_slug: str
    points: float
    matched_driver_id: str | None = None
    matched_team_id: str | None = None
    local_team_id: str | None = None
    team_match_status: str = "not_checked"

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


@dataclass(frozen=True)
class OfficialTeamStanding:
    position: int
    official_team_slug: str
    team_name: str
    points: float
    matched_team_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


@dataclass(frozen=True)
class OfficialStandingsReport:
    year: int
    generated_at: str
    knowledge_cutoff: str | None
    source_captured_at: str
    driver_source_path: str
    team_source_path: str
    driver_source_url: str
    team_source_url: str
    driver_rows: tuple[OfficialDriverStanding, ...]
    team_rows: tuple[OfficialTeamStanding, ...]
    roster_status: str
    can_seed_season_points: bool
    matched_driver_count: int
    unmatched_official_drivers: tuple[str, ...]
    unmatched_project_drivers: tuple[str, ...]
    team_mismatch_drivers: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "generated_at": self.generated_at,
            "knowledge_cutoff": self.knowledge_cutoff,
            "source_captured_at": self.source_captured_at,
            "driver_source_path": self.driver_source_path,
            "team_source_path": self.team_source_path,
            "driver_source_url": self.driver_source_url,
            "team_source_url": self.team_source_url,
            "driver_row_count": len(self.driver_rows),
            "team_row_count": len(self.team_rows),
            "driver_rows": [row.to_dict() for row in self.driver_rows],
            "team_rows": [row.to_dict() for row in self.team_rows],
            "roster_status": self.roster_status,
            "can_seed_season_points": self.can_seed_season_points,
            "matched_driver_count": self.matched_driver_count,
            "unmatched_official_drivers": list(self.unmatched_official_drivers),
            "unmatched_project_drivers": list(self.unmatched_project_drivers),
            "team_mismatch_drivers": list(self.team_mismatch_drivers),
            "warnings": list(self.warnings),
        }

    def matched_points(self) -> dict[str, float]:
        return {
            str(row.matched_driver_id): row.points
            for row in self.driver_rows
            if row.matched_driver_id
        }


@dataclass(frozen=True)
class _OfficialPage:
    payload: dict[str, Any]
    path: Path
    captured_at: str


class OfficialStandingsRepository:
    """Reads stored Formula1.com results pages and normalizes standings tables."""

    def __init__(
        self,
        raw_root: Path | str = Path("data/raw"),
        processed_root: Path | str = Path("data/processed"),
    ) -> None:
        self.raw_root = Path(raw_root)
        self.processed_root = Path(processed_root)

    def build(
        self,
        year: int,
        season: SeasonState | None = None,
        knowledge_cutoff: str | datetime | None = None,
    ) -> OfficialStandingsReport:
        cutoff = self._normalize_cutoff(knowledge_cutoff)
        driver_page = self._latest_page(year, "drivers", cutoff)
        team_page = self._latest_page(year, "teams", cutoff)
        driver_rows = self._parse_driver_rows(driver_page.payload, driver_page.path)
        team_rows = self._parse_team_rows(team_page.payload, team_page.path)
        if season is not None:
            driver_rows = self._match_driver_rows(driver_rows, season)
            team_rows = self._match_team_rows(team_rows, season)
        return self._report(year, cutoff, driver_page, team_page, driver_rows, team_rows, season)

    def write(
        self,
        year: int,
        season: SeasonState | None = None,
        knowledge_cutoff: str | datetime | None = None,
    ) -> Path:
        report = self.build(year, season=season, knowledge_cutoff=knowledge_cutoff)
        store = RawSnapshotStore(self.processed_root)
        record = store.write_json(
            "f1_official_standings",
            f"{year}_standings",
            report.to_dict(),
            {
                "year": year,
                "knowledge_cutoff": report.knowledge_cutoff,
                "driver_source_path": report.driver_source_path,
                "team_source_path": report.team_source_path,
                "source_captured_at": report.source_captured_at,
            },
        )
        return record.path

    def _latest_page(self, year: int, page: str, cutoff: datetime | None) -> _OfficialPage:
        dataset_dir = self.raw_root / "f1_official" / f"{year}_{page}"
        if not dataset_dir.exists():
            raise ValueError(
                f"No F1 official {page} snapshot for {year}. "
                f"Run `python -m f1predict.cli ingest-f1-official --year {year} --page {page}` first."
            )
        candidates: list[_OfficialPage] = []
        for meta_path in dataset_dir.rglob("*.meta.json"):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            captured_at = str(meta.get("captured_at") or "")
            captured = parse_dt(captured_at)
            if cutoff is not None and (captured is None or captured > cutoff):
                continue
            payload_path = self._payload_path(meta_path, meta)
            if not payload_path.exists():
                continue
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            candidates.append(_OfficialPage(payload=payload, path=payload_path, captured_at=captured_at))
        if not candidates:
            cutoff_text = cutoff.isoformat() if cutoff else "latest"
            raise ValueError(f"No F1 official {page} snapshot for {year} at or before {cutoff_text}")
        return max(candidates, key=lambda item: item.captured_at)

    @staticmethod
    def _payload_path(meta_path: Path, meta: dict[str, Any]) -> Path:
        path = Path(str(meta.get("data_path", "")))
        if path.exists():
            return path
        return meta_path.with_name(meta_path.name.replace(".meta.json", ".json"))

    def _parse_driver_rows(self, payload: dict[str, Any], path: Path) -> tuple[OfficialDriverStanding, ...]:
        table = self._results_table(payload)
        labels = [str(col.get("label") or "") for col in table.get("cols", [])]
        if labels != ["Pos.", "Driver", "Nationality", "Team", "Pts."]:
            raise ValueError(f"Unsupported official driver standings columns in {path}: {labels}")
        rows: list[OfficialDriverStanding] = []
        for raw_row in table.get("rows", []):
            if not isinstance(raw_row, list) or len(raw_row) < 5:
                continue
            driver_href = self._first_href(raw_row[1])
            team_href = self._first_href(raw_row[3])
            official_driver_id, driver_slug = self._driver_from_href(driver_href)
            team_slug = self._team_slug_from_href(team_href)
            rows.append(
                OfficialDriverStanding(
                    position=self._as_int(self._cell_text(raw_row[0])),
                    official_driver_id=official_driver_id,
                    driver_slug=driver_slug,
                    driver_name=self._name_from_slug(driver_slug),
                    nationality=self._cell_text(raw_row[2]),
                    team_name=self._cell_text(raw_row[3]),
                    official_team_slug=team_slug,
                    points=self._as_float(self._cell_text(raw_row[4])),
                )
            )
        if not rows:
            raise ValueError(f"No official driver standings rows parsed from {path}")
        return tuple(rows)

    def _parse_team_rows(self, payload: dict[str, Any], path: Path) -> tuple[OfficialTeamStanding, ...]:
        table = self._results_table(payload)
        labels = [str(col.get("label") or "") for col in table.get("cols", [])]
        if labels != ["Pos.", "Team", "Pts."]:
            raise ValueError(f"Unsupported official team standings columns in {path}: {labels}")
        rows: list[OfficialTeamStanding] = []
        for raw_row in table.get("rows", []):
            if not isinstance(raw_row, list) or len(raw_row) < 3:
                continue
            team_href = self._first_href(raw_row[1])
            rows.append(
                OfficialTeamStanding(
                    position=self._as_int(self._cell_text(raw_row[0])),
                    official_team_slug=self._team_slug_from_href(team_href),
                    team_name=self._cell_text(raw_row[1]),
                    points=self._as_float(self._cell_text(raw_row[2])),
                )
            )
        if not rows:
            raise ValueError(f"No official team standings rows parsed from {path}")
        return tuple(rows)

    def _results_table(self, payload: dict[str, Any]) -> dict[str, Any]:
        html = str(payload.get("html") or "")
        for match in re.finditer(r"<script>(.*?)</script>", html, flags=re.S):
            script = match.group(1)
            if '\\"tableId\\"' not in script:
                continue
            if not script.startswith("self.__next_f.push("):
                continue
            argument = script[len("self.__next_f.push("):-1]
            pushed = json.loads(argument)
            if len(pushed) < 2 or not isinstance(pushed[1], str) or ":" not in pushed[1]:
                continue
            flight_payload = pushed[1].split(":", 1)[1]
            tree = json.loads(flight_payload)
            table = self._find_results_table(tree)
            if table:
                return table
        raise ValueError(f"No results table found in F1 official {payload.get('url')}")

    def _find_results_table(self, value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            if value.get("tableId") == "results-table":
                return value
            for child in value.values():
                result = self._find_results_table(child)
                if result is not None:
                    return result
        if isinstance(value, list):
            for child in value:
                result = self._find_results_table(child)
                if result is not None:
                    return result
        return None

    def _match_driver_rows(
        self,
        rows: tuple[OfficialDriverStanding, ...],
        season: SeasonState,
    ) -> tuple[OfficialDriverStanding, ...]:
        driver_lookup = self._driver_lookup(season.drivers)
        team_lookup = self._team_lookup(season.teams)
        matched = []
        for row in rows:
            driver_id = self._lookup_driver_id(row, driver_lookup)
            matched_team_id = self._lookup_team_id(row.team_name, row.official_team_slug, team_lookup)
            local_team_id = season.drivers[driver_id].team_id if driver_id in season.drivers else None
            team_status = "matched"
            if driver_id is None:
                team_status = "driver_unmatched"
            elif matched_team_id is None:
                team_status = "official_team_unmatched"
            elif local_team_id != matched_team_id:
                team_status = "local_team_mismatch"
            matched.append(
                OfficialDriverStanding(
                    **{
                        **row.to_dict(),
                        "matched_driver_id": driver_id,
                        "matched_team_id": matched_team_id,
                        "local_team_id": local_team_id,
                        "team_match_status": team_status,
                    }
                )
            )
        return tuple(matched)

    def _match_team_rows(
        self,
        rows: tuple[OfficialTeamStanding, ...],
        season: SeasonState,
    ) -> tuple[OfficialTeamStanding, ...]:
        team_lookup = self._team_lookup(season.teams)
        matched = []
        for row in rows:
            matched.append(
                OfficialTeamStanding(
                    position=row.position,
                    official_team_slug=row.official_team_slug,
                    team_name=row.team_name,
                    points=row.points,
                    matched_team_id=self._lookup_team_id(row.team_name, row.official_team_slug, team_lookup),
                )
            )
        return tuple(matched)

    def _report(
        self,
        year: int,
        cutoff: datetime | None,
        driver_page: _OfficialPage,
        team_page: _OfficialPage,
        driver_rows: tuple[OfficialDriverStanding, ...],
        team_rows: tuple[OfficialTeamStanding, ...],
        season: SeasonState | None,
    ) -> OfficialStandingsReport:
        matched_driver_ids = {row.matched_driver_id for row in driver_rows if row.matched_driver_id}
        project_driver_ids = set(season.drivers) if season else set()
        unmatched_official = tuple(
            row.driver_name
            for row in driver_rows
            if row.matched_driver_id is None and row.points > 0
        )
        unmatched_project = tuple(
            sorted(
                season.drivers[driver_id].name
                for driver_id in project_driver_ids - matched_driver_ids
            )
        ) if season else ()
        team_mismatches = tuple(
            row.driver_name
            for row in driver_rows
            if row.matched_driver_id and row.team_match_status != "matched"
        )
        warnings: list[str] = []
        if driver_page.captured_at != team_page.captured_at:
            warnings.append("driver_and_team_standings_sources_have_different_capture_times")
        if unmatched_official:
            warnings.append("official_point_scoring_drivers_not_in_project_roster")
        if unmatched_project:
            warnings.append("project_roster_drivers_missing_from_official_standings")
        if team_mismatches:
            warnings.append("official_team_assignments_do_not_match_project_roster")
        if not season:
            warnings.append("standings_not_matched_against_project_roster")
        can_seed = bool(season) and not unmatched_official and not unmatched_project and not team_mismatches
        roster_status = "aligned" if can_seed else "mismatch"
        return OfficialStandingsReport(
            year=year,
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            knowledge_cutoff=cutoff.isoformat() if cutoff else None,
            source_captured_at=min(driver_page.captured_at, team_page.captured_at),
            driver_source_path=str(driver_page.path),
            team_source_path=str(team_page.path),
            driver_source_url=str(driver_page.payload.get("url") or ""),
            team_source_url=str(team_page.payload.get("url") or ""),
            driver_rows=driver_rows,
            team_rows=team_rows,
            roster_status=roster_status,
            can_seed_season_points=can_seed,
            matched_driver_count=len(matched_driver_ids),
            unmatched_official_drivers=unmatched_official,
            unmatched_project_drivers=unmatched_project,
            team_mismatch_drivers=team_mismatches,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _cell_text(cell: Any) -> str:
        parts = OfficialStandingsRepository._text_parts(cell.get("content") if isinstance(cell, dict) else cell)
        return " ".join(" ".join(parts).replace("\xa0", " ").split())

    @staticmethod
    def _text_parts(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (int, float)):
            return [str(value)]
        if isinstance(value, str):
            if value in {"$", "$undefined"} or value.startswith("$L"):
                return []
            return [value]
        if isinstance(value, dict):
            if "children" in value:
                return OfficialStandingsRepository._text_parts(value.get("children"))
            if "content" in value:
                return OfficialStandingsRepository._text_parts(value.get("content"))
            return []
        if isinstance(value, list):
            if len(value) >= 4 and value[0] == "$" and isinstance(value[3], dict):
                return OfficialStandingsRepository._text_parts(value[3].get("children"))
            parts: list[str] = []
            for child in value:
                parts.extend(OfficialStandingsRepository._text_parts(child))
            return parts
        return []

    @staticmethod
    def _first_href(value: Any) -> str:
        if isinstance(value, dict):
            href = value.get("href")
            if href:
                return str(href)
            for child in value.values():
                found = OfficialStandingsRepository._first_href(child)
                if found:
                    return found
        if isinstance(value, list):
            for child in value:
                found = OfficialStandingsRepository._first_href(child)
                if found:
                    return found
        return ""

    @staticmethod
    def _driver_from_href(href: str) -> tuple[str, str]:
        match = re.search(r"/drivers/([^/]+)/([^/?#]+)", href)
        if not match:
            return "", ""
        return match.group(1), match.group(2)

    @staticmethod
    def _team_slug_from_href(href: str) -> str:
        match = re.search(r"/team/([^/?#]+)", href)
        return match.group(1) if match else ""

    @staticmethod
    def _name_from_slug(slug: str) -> str:
        return " ".join(part.capitalize() for part in slug.split("-") if part)

    @staticmethod
    def _as_int(value: str) -> int:
        return int(float(value))

    @staticmethod
    def _as_float(value: str) -> float:
        return float(value)

    @staticmethod
    def _lookup_driver_id(row: OfficialDriverStanding, lookup: dict[str, str]) -> str | None:
        candidates = [
            row.official_driver_id,
            row.driver_slug,
            row.driver_name,
            row.driver_name.split()[-1] if row.driver_name.split() else "",
        ]
        return next((lookup[key] for key in map(_compact_key, candidates) if key in lookup), None)

    @staticmethod
    def _lookup_team_id(team_name: str, team_slug: str, lookup: dict[str, str]) -> str | None:
        candidates = [
            team_name,
            team_slug,
            team_slug.replace("-", " "),
            re.sub(r"\b(mercedes|ferrari|honda|ford|aramco|atlassian)\b", "", team_slug.replace("-", " "), flags=re.I),
        ]
        return next((lookup[key] for key in map(_compact_key, candidates) if key in lookup), None)

    @staticmethod
    def _driver_lookup(drivers: dict[str, Driver]) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for driver in drivers.values():
            candidates = [
                driver.driver_id,
                driver.name,
                driver.name.split()[-1] if driver.name.split() else "",
                *driver.external_ids.values(),
            ]
            for candidate in candidates:
                key = _compact_key(str(candidate))
                if key:
                    lookup[key] = driver.driver_id
        return lookup

    @staticmethod
    def _team_lookup(teams: dict[str, Team]) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for team in teams.values():
            candidates = [
                team.team_id,
                team.name,
                team.name.replace("Racing", ""),
                team.name.replace("F1 Team", ""),
            ]
            for candidate in candidates:
                key = _compact_key(str(candidate))
                if key:
                    lookup[key] = team.team_id
        return lookup

    @staticmethod
    def _normalize_cutoff(value: str | datetime | None) -> datetime | None:
        if value is None:
            return None
        parsed = parse_dt(value) if isinstance(value, str) else value
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            from datetime import timezone

            return parsed.replace(tzinfo=timezone.utc)
        from datetime import timezone

        return parsed.astimezone(timezone.utc)


def _compact_key(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", ascii_value.lower())
