"""Plan and apply audited seed-roster updates from official standings."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from f1predict.data_sources.seed_loader import DEFAULT_SEED_PATH, SeedDataSource
from f1predict.domain import utc_now
from f1predict.official_standings import OfficialDriverStanding, OfficialStandingsRepository, OfficialTeamStanding


@dataclass(frozen=True)
class SeedRosterOperation:
    action: str
    target_type: str
    target_id: str
    reason: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    source: dict[str, Any]
    auto_apply: bool
    review_required: bool

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


@dataclass(frozen=True)
class SeedRosterPlan:
    year: int
    generated_at: str
    seed_path: str
    knowledge_cutoff: str | None
    source_captured_at: str
    current_roster_status: str
    status: str
    operation_count: int
    auto_apply_count: int
    review_required_count: int
    operations: tuple[SeedRosterOperation, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "generated_at": self.generated_at,
            "seed_path": self.seed_path,
            "knowledge_cutoff": self.knowledge_cutoff,
            "source_captured_at": self.source_captured_at,
            "current_roster_status": self.current_roster_status,
            "status": self.status,
            "operation_count": self.operation_count,
            "auto_apply_count": self.auto_apply_count,
            "review_required_count": self.review_required_count,
            "operations": [operation.to_dict() for operation in self.operations],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class SeedRosterApplyResult:
    output_path: str
    applied_operation_count: int
    skipped_review_required_count: int
    skipped_actions: tuple[str, ...]
    plan_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_path": self.output_path,
            "applied_operation_count": self.applied_operation_count,
            "skipped_review_required_count": self.skipped_review_required_count,
            "skipped_actions": list(self.skipped_actions),
            "plan_status": self.plan_status,
        }


class SeedRosterSyncPlanner:
    """Builds source-backed roster update plans for the seed season file."""

    def __init__(
        self,
        official_repository: OfficialStandingsRepository | None = None,
    ) -> None:
        self.official_repository = official_repository or OfficialStandingsRepository()

    def plan(
        self,
        year: int,
        seed_path: Path | str = DEFAULT_SEED_PATH,
        knowledge_cutoff: str | None = None,
    ) -> SeedRosterPlan:
        seed_file = Path(seed_path)
        season = SeedDataSource(seed_file).load()
        raw = self._read_seed(seed_file)
        report = self.official_repository.build(year, season=season, knowledge_cutoff=knowledge_cutoff)
        teams_by_id = {str(team.get("team_id")): team for team in raw.get("teams", [])}
        drivers_by_id = {str(driver.get("driver_id")): driver for driver in raw.get("drivers", [])}
        operations: list[SeedRosterOperation] = []

        for row in report.team_rows:
            if row.matched_team_id is None:
                operations.append(self._add_team_operation(row))

        for row in report.driver_rows:
            if row.matched_driver_id:
                driver = drivers_by_id.get(row.matched_driver_id)
                if not driver:
                    continue
                if row.matched_team_id and driver.get("team_id") != row.matched_team_id:
                    after = {**driver, "team_id": row.matched_team_id}
                    operations.append(
                        SeedRosterOperation(
                            action="update_driver_team",
                            target_type="driver",
                            target_id=row.matched_driver_id,
                            reason="Official standings team assignment differs from seed roster.",
                            before={"team_id": driver.get("team_id")},
                            after={"team_id": row.matched_team_id},
                            source=self._driver_source(row),
                            auto_apply=True,
                            review_required=False,
                        )
                    )
                    drivers_by_id[row.matched_driver_id] = after
                current_points = _as_number(driver.get("current_points", 0.0))
                official_points = _json_number(row.points)
                if current_points != official_points:
                    operations.append(
                        SeedRosterOperation(
                            action="update_driver_points",
                            target_type="driver",
                            target_id=row.matched_driver_id,
                            reason="Official standings points differ from seed current_points.",
                            before={"current_points": current_points},
                            after={"current_points": official_points},
                            source=self._driver_source(row),
                            auto_apply=True,
                            review_required=False,
                        )
                    )
                continue

            team_id = row.matched_team_id or self._team_id_for_unmatched_driver(row, report.team_rows, teams_by_id)
            driver_id = self._new_driver_id(row, drivers_by_id)
            after = self._default_driver(row, team_id)
            after["driver_id"] = driver_id
            operations.append(
                SeedRosterOperation(
                    action="add_driver",
                    target_type="driver",
                    target_id=driver_id,
                    reason="Official standings driver is missing from the seed roster. Skill priors need review.",
                    before=None,
                    after=after,
                    source=self._driver_source(row),
                    auto_apply=False,
                    review_required=True,
                )
            )

        matched_driver_ids = {row.matched_driver_id for row in report.driver_rows if row.matched_driver_id}
        for driver_id, driver in drivers_by_id.items():
            if driver_id not in matched_driver_ids:
                operations.append(
                    SeedRosterOperation(
                        action="review_project_driver_missing_from_official",
                        target_type="driver",
                        target_id=driver_id,
                        reason="Seed driver is not present in the latest official standings snapshot.",
                        before={
                            "name": driver.get("name"),
                            "team_id": driver.get("team_id"),
                            "current_points": driver.get("current_points", 0),
                        },
                        after=None,
                        source={"source": "seed_roster", "seed_path": str(seed_file)},
                        auto_apply=False,
                        review_required=True,
                    )
                )

        auto_count = sum(1 for operation in operations if operation.auto_apply)
        review_count = sum(1 for operation in operations if operation.review_required)
        if not operations:
            status = "no_changes"
        elif review_count:
            status = "review_required"
        else:
            status = "auto_applicable_changes"
        warnings = list(report.warnings)
        if review_count:
            warnings.append("review_required_changes_not_auto_applied_by_default")
        return SeedRosterPlan(
            year=year,
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            seed_path=str(seed_file),
            knowledge_cutoff=report.knowledge_cutoff,
            source_captured_at=report.source_captured_at,
            current_roster_status=report.roster_status,
            status=status,
            operation_count=len(operations),
            auto_apply_count=auto_count,
            review_required_count=review_count,
            operations=tuple(operations),
            warnings=tuple(warnings),
        )

    def apply(
        self,
        plan: SeedRosterPlan,
        seed_path: Path | str = DEFAULT_SEED_PATH,
        output_path: Path | str | None = None,
        apply_review_required: bool = False,
    ) -> SeedRosterApplyResult:
        seed_file = Path(seed_path)
        destination = Path(output_path) if output_path else seed_file
        raw = self._read_seed(seed_file)
        teams = raw.setdefault("teams", [])
        drivers = raw.setdefault("drivers", [])
        teams_by_id = {str(team.get("team_id")): team for team in teams}
        drivers_by_id = {str(driver.get("driver_id")): driver for driver in drivers}
        applied = 0
        skipped: list[str] = []

        for operation in plan.operations:
            if operation.review_required and not apply_review_required:
                skipped.append(operation.action)
                continue
            if not operation.auto_apply and not apply_review_required:
                skipped.append(operation.action)
                continue
            if operation.action == "add_team" and operation.after:
                if operation.target_id not in teams_by_id:
                    team = dict(operation.after)
                    teams.append(team)
                    teams_by_id[operation.target_id] = team
                    applied += 1
            elif operation.action == "update_driver_team" and operation.after:
                driver = drivers_by_id.get(operation.target_id)
                if driver is not None:
                    driver["team_id"] = operation.after["team_id"]
                    applied += 1
            elif operation.action == "update_driver_points" and operation.after:
                driver = drivers_by_id.get(operation.target_id)
                if driver is not None:
                    driver["current_points"] = operation.after["current_points"]
                    applied += 1
            elif operation.action == "add_driver" and operation.after:
                if operation.target_id not in drivers_by_id:
                    driver = dict(operation.after)
                    drivers.append(driver)
                    drivers_by_id[operation.target_id] = driver
                    applied += 1
            else:
                skipped.append(operation.action)

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return SeedRosterApplyResult(
            output_path=str(destination),
            applied_operation_count=applied,
            skipped_review_required_count=sum(
                1 for operation in plan.operations if operation.review_required and not apply_review_required
            ),
            skipped_actions=tuple(skipped),
            plan_status=plan.status,
        )

    @staticmethod
    def _read_seed(seed_path: Path) -> dict[str, Any]:
        return json.loads(seed_path.read_text(encoding="utf-8"))

    @staticmethod
    def _add_team_operation(row: OfficialTeamStanding) -> SeedRosterOperation:
        team_id = _stable_id(row.team_name, fallback=row.official_team_slug)
        return SeedRosterOperation(
            action="add_team",
            target_type="team",
            target_id=team_id,
            reason="Official standings team is missing from the seed roster. Model priors need review.",
            before=None,
            after={
                "team_id": team_id,
                "name": row.team_name,
                "base_strength": 0.35,
                "reliability": 0.91,
                "strategy": 0.43,
                "track_affinity": {
                    "high_speed": 0.0,
                    "street": 0.0,
                    "technical": 0.0,
                    "power": 0.0,
                },
            },
            source={
                "source": "f1_official_team_standings",
                "official_team_slug": row.official_team_slug,
                "team_name": row.team_name,
                "points": _json_number(row.points),
            },
            auto_apply=False,
            review_required=True,
        )

    @staticmethod
    def _driver_source(row: OfficialDriverStanding) -> dict[str, Any]:
        return {
            "source": "f1_official_driver_standings",
            "official_driver_id": row.official_driver_id,
            "driver_slug": row.driver_slug,
            "driver_name": row.driver_name,
            "team_name": row.team_name,
            "official_team_slug": row.official_team_slug,
            "points": _json_number(row.points),
        }

    @staticmethod
    def _default_driver(row: OfficialDriverStanding, team_id: str | None) -> dict[str, Any]:
        return {
            "driver_id": _stable_id(row.driver_name, fallback=row.driver_slug, prefer_last_token=True),
            "name": row.driver_name,
            "team_id": team_id or _stable_id(row.team_name, fallback=row.official_team_slug),
            "base_skill": 0.0,
            "qualifying": 0.0,
            "racecraft": 0.0,
            "tyre_management": 0.0,
            "wet_skill": 0.0,
            "reliability_modifier": -0.005,
            "current_points": _json_number(row.points),
            "external_ids": {
                "formula1_official_driver_id": row.official_driver_id,
                "formula1_driver_slug": row.driver_slug,
            },
        }

    @staticmethod
    def _new_driver_id(row: OfficialDriverStanding, drivers_by_id: dict[str, dict[str, Any]]) -> str:
        base = _stable_id(row.driver_name, fallback=row.driver_slug, prefer_last_token=True)
        if base not in drivers_by_id:
            return base
        suffix = _compact_key(row.official_driver_id.lower()) or "official"
        candidate = f"{base}_{suffix}"
        index = 2
        while candidate in drivers_by_id:
            candidate = f"{base}_{suffix}_{index}"
            index += 1
        return candidate

    @staticmethod
    def _team_id_for_unmatched_driver(
        row: OfficialDriverStanding,
        team_rows: tuple[OfficialTeamStanding, ...],
        teams_by_id: dict[str, dict[str, Any]],
    ) -> str | None:
        for team_row in team_rows:
            if team_row.official_team_slug == row.official_team_slug and team_row.matched_team_id:
                return team_row.matched_team_id
        stable = _stable_id(row.team_name, fallback=row.official_team_slug)
        return stable if stable in teams_by_id else None


def _json_number(value: float) -> int | float:
    number = float(value)
    return int(number) if number.is_integer() else number


def _as_number(value: Any) -> int | float:
    try:
        return _json_number(float(value))
    except (TypeError, ValueError):
        return 0


def _stable_id(value: str, fallback: str = "", prefer_last_token: bool = False) -> str:
    source = value or fallback
    normalized = unicodedata.normalize("NFKD", source).encode("ascii", "ignore").decode("ascii")
    tokens = re.findall(r"[a-z0-9]+", normalized.lower())
    if prefer_last_token and tokens:
        tokens = [tokens[-1]]
    if not tokens and fallback and fallback != source:
        return _stable_id(fallback, prefer_last_token=prefer_last_token)
    return "_".join(tokens)


def _compact_key(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", ascii_value.lower())
