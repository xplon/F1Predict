"""Processed feature provider used by prediction pipelines."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from f1predict.domain import FeatureAdjustment, RaceEvent, SeasonState, parse_dt
from f1predict.features.openf1_summary import OpenF1SummaryBuilder
from f1predict.official_standings import OfficialStandingsRepository
from f1predict.results import FastF1ResultRepository, NormalizedRaceResult, normalize_event_name


class ProcessedFeatureProvider:
    """Loads processed point-in-time features for an event.

    The first MVP supports historical OpenF1 analogue summaries. An event can
    declare:

    ```json
    "feature_refs": {
      "openf1_analogue": {
        "year": 2024,
        "event_query": "Silverstone"
      }
    }
    ```
    """

    def __init__(
        self,
        processed_root: Path | str = Path("data/processed"),
        raw_root: Path | str = Path("data/raw"),
        result_repository: FastF1ResultRepository | None = None,
        official_standings_repository: OfficialStandingsRepository | None = None,
    ) -> None:
        self.processed_root = Path(processed_root)
        self.raw_root = Path(raw_root)
        self.result_repository = result_repository or FastF1ResultRepository(raw_root)
        self.official_standings_repository = official_standings_repository or OfficialStandingsRepository(
            raw_root=raw_root,
            processed_root=processed_root,
        )

    def load_event_features(
        self,
        season: SeasonState,
        event: RaceEvent,
        knowledge_cutoff=None,
    ) -> list[FeatureAdjustment]:
        adjustments: list[FeatureAdjustment] = []
        ref = event.feature_refs.get("openf1_analogue")
        if ref:
            year = int(ref["year"])
            event_query = str(ref["event_query"])
            summary = self._load_or_build_openf1_summary(year, event_query)
            adjustments.extend(self._summary_to_adjustments(season, event, summary))
        adjustments.extend(self._official_standings_adjustments(season, event, knowledge_cutoff))
        adjustments.extend(self._fastf1_form_adjustments(season, event, knowledge_cutoff))
        if knowledge_cutoff is None:
            return adjustments
        return [
            adjustment
            for adjustment in adjustments
            if parse_dt(adjustment.observed_at) is not None and parse_dt(adjustment.observed_at) <= knowledge_cutoff
        ]

    def _load_or_build_openf1_summary(self, year: int, event_query: str) -> dict[str, Any]:
        dataset = f"{year}_{event_query}_summary"
        dataset_dir = self.processed_root / "openf1" / dataset
        files = []
        if dataset_dir.exists():
            files = [path for path in dataset_dir.rglob("*.json") if not path.name.endswith(".meta.json")]
        if files:
            latest = max(files, key=lambda path: path.stat().st_mtime)
            return json.loads(latest.read_text(encoding="utf-8"))
        return OpenF1SummaryBuilder(self.raw_root, self.processed_root).build_event_summary(year, event_query)

    def _summary_to_adjustments(
        self,
        season: SeasonState,
        event: RaceEvent,
        summary: dict[str, Any],
    ) -> list[FeatureAdjustment]:
        by_number = self._driver_by_openf1_number(season)
        adjustments: list[FeatureAdjustment] = []
        observed_at = self._summary_available_at(summary)
        for session_name, session in summary.get("sessions", {}).items():
            laps = session.get("laps")
            if not laps:
                continue
            metric = "qualifying_pace" if "Qualifying" in session_name else "race_pace"
            fastest = laps.get("fastest_drivers", [])
            count = max(1, len(fastest))
            for rank, row in enumerate(fastest, start=1):
                driver_id = by_number.get(str(row.get("driver_number")))
                if driver_id is None:
                    continue
                centered = ((count - rank) / max(1, count - 1)) - 0.5 if count > 1 else 0.0
                value = round(centered * 0.10, 4)
                confidence = 0.28 if metric == "race_pace" else 0.24
                adjustments.append(
                    FeatureAdjustment(
                        feature_id=f"openf1:{summary['year']}:{summary['event_query']}:{session_name}:{driver_id}:{metric}",
                        event_id=event.event_id,
                        source=f"openf1_summary:{summary['year']}:{summary['event_query']}:{session_name}",
                        target_type="driver",
                        target_id=driver_id,
                        metric=metric,
                        value=value,
                        confidence=confidence,
                        observed_at=observed_at,
                        explanation=(
                            f"Historical OpenF1 analogue rank {rank}/{count} in {session_name}; "
                            f"used as low-confidence {metric} prior."
                        ),
                    )
                )

        race_weather = self._race_weather(summary)
        if race_weather and race_weather.get("rainfall_ratio", 0.0) > 0.2:
            for driver in season.drivers.values():
                if driver.wet_skill <= 0:
                    continue
                adjustments.append(
                    FeatureAdjustment(
                        feature_id=f"openf1:{summary['year']}:{summary['event_query']}:wet:{driver.driver_id}",
                        event_id=event.event_id,
                        source=f"openf1_summary:{summary['year']}:{summary['event_query']}:weather",
                        target_type="driver",
                        target_id=driver.driver_id,
                        metric="wet_skill",
                        value=round(driver.wet_skill * 0.03, 4),
                        confidence=0.25,
                        observed_at=observed_at,
                        explanation=(
                            "Historical analogue race had meaningful rainfall; "
                            "driver wet-skill prior gets a small confidence-weighted boost."
                        ),
                    )
                )
        return adjustments

    def _official_standings_adjustments(
        self,
        season: SeasonState,
        event: RaceEvent,
        knowledge_cutoff=None,
    ) -> list[FeatureAdjustment]:
        """Convert audited F1 official standings snapshots into point-in-time form priors."""

        target_cutoff = (
            parse_dt(str(knowledge_cutoff))
            if knowledge_cutoff
            else parse_dt(f"{event.date}T00:00:00+00:00")
        )
        if target_cutoff is None:
            return []
        try:
            report = self.official_standings_repository.build(
                season.season,
                season=season,
                knowledge_cutoff=target_cutoff,
            )
        except ValueError:
            return []

        if report.warnings:
            return []

        completed_events = self._completed_events_before_cutoff(season, target_cutoff)
        if completed_events <= 0:
            return []

        observed_at = report.source_captured_at
        source = f"f1_official_standings:{season.season}:{observed_at}"
        adjustments: list[FeatureAdjustment] = []

        driver_rows = [
            row
            for row in report.driver_rows
            if row.matched_driver_id and row.matched_driver_id in season.drivers
        ]
        if driver_rows:
            driver_points = [row.points for row in driver_rows]
            field_avg_points = mean(driver_points)
            max_points = max(max(driver_points), 1.0)
            driver_count = len(driver_rows)
            confidence = min(0.38, 0.20 + 0.015 * completed_events)
            for row in driver_rows:
                driver_id = str(row.matched_driver_id)
                rank_center = self._rank_center(row.position, driver_count)
                points_component = (row.points - field_avg_points) / max_points * 0.08
                value = round(self._clamp(points_component + rank_center * 0.04, -0.075, 0.075), 4)
                adjustments.append(
                    FeatureAdjustment(
                        feature_id=(
                            f"f1-official-standings:{season.season}:{event.event_id}:"
                            f"{driver_id}:race_pace:{observed_at}"
                        ),
                        event_id=event.event_id,
                        source=source,
                        target_type="driver",
                        target_id=driver_id,
                        metric="race_pace",
                        value=value,
                        confidence=confidence,
                        observed_at=observed_at,
                        explanation=(
                            f"Official driver standings before {event.name}: P{row.position}, "
                            f"{row.points:.1f} points vs field average {field_avg_points:.1f}; "
                            "used as a cutoff-safe season form prior, not a manual team-strength override."
                        ),
                    )
                )
                qualifying_value = round(value * 0.45, 4)
                if qualifying_value:
                    adjustments.append(
                        FeatureAdjustment(
                            feature_id=(
                                f"f1-official-standings:{season.season}:{event.event_id}:"
                                f"{driver_id}:qualifying_pace:{observed_at}"
                            ),
                            event_id=event.event_id,
                            source=source,
                            target_type="driver",
                            target_id=driver_id,
                            metric="qualifying_pace",
                            value=qualifying_value,
                            confidence=max(0.14, confidence - 0.08),
                            observed_at=observed_at,
                            explanation=(
                                f"Official driver standings before {event.name}: P{row.position}, "
                                f"{row.points:.1f} points; converted into a smaller qualifying prior because "
                                "standings primarily reflect race outcomes."
                            ),
                        )
                    )

        team_rows = [
            row
            for row in report.team_rows
            if row.matched_team_id and row.matched_team_id in season.teams
        ]
        if team_rows:
            team_points = [row.points for row in team_rows]
            field_avg_team_points = mean(team_points)
            max_team_points = max(max(team_points), 1.0)
            team_count = len(team_rows)
            confidence = min(0.42, 0.24 + 0.018 * completed_events)
            for row in team_rows:
                team_id = str(row.matched_team_id)
                rank_center = self._rank_center(row.position, team_count)
                points_component = (row.points - field_avg_team_points) / max_team_points * 0.12
                value = round(self._clamp(points_component + rank_center * 0.05, -0.105, 0.105), 4)
                adjustments.append(
                    FeatureAdjustment(
                        feature_id=(
                            f"f1-official-standings:{season.season}:{event.event_id}:"
                            f"{team_id}:race_pace:{observed_at}"
                        ),
                        event_id=event.event_id,
                        source=source,
                        target_type="team",
                        target_id=team_id,
                        metric="race_pace",
                        value=value,
                        confidence=confidence,
                        observed_at=observed_at,
                        explanation=(
                            f"Official constructor standings before {event.name}: P{row.position}, "
                            f"{row.points:.1f} points vs field average {field_avg_team_points:.1f}; "
                            "used as a cutoff-safe team form prior."
                        ),
                    )
                )
                qualifying_value = round(value * 0.40, 4)
                if qualifying_value:
                    adjustments.append(
                        FeatureAdjustment(
                            feature_id=(
                                f"f1-official-standings:{season.season}:{event.event_id}:"
                                f"{team_id}:qualifying_pace:{observed_at}"
                            ),
                            event_id=event.event_id,
                            source=source,
                            target_type="team",
                            target_id=team_id,
                            metric="qualifying_pace",
                            value=qualifying_value,
                            confidence=max(0.16, confidence - 0.09),
                            observed_at=observed_at,
                            explanation=(
                                f"Official constructor standings before {event.name}: P{row.position}, "
                                f"{row.points:.1f} points; converted into a smaller qualifying prior because "
                                "standings primarily reflect race outcomes."
                            ),
                        )
                    )

        return adjustments

    def _fastf1_form_adjustments(
        self,
        season: SeasonState,
        event: RaceEvent,
        knowledge_cutoff=None,
        window: int = 3,
    ) -> list[FeatureAdjustment]:
        """Build point-in-time form priors from previous race results only."""

        target_cutoff = parse_dt(str(knowledge_cutoff)) if knowledge_cutoff else parse_dt(f"{event.date}T00:00:00+00:00")
        if target_cutoff is None:
            return []
        event_dates = self._event_dates(season)
        result_rows: list[tuple[str, NormalizedRaceResult, str]] = []
        for key, result in self.result_repository.latest_results_by_event(season.season).items():
            observed_at = event_dates.get(key)
            observed_dt = parse_dt(observed_at)
            if observed_at is None or observed_dt is None:
                continue
            if observed_dt >= target_cutoff:
                continue
            result_rows.append((key, result, observed_at))
        result_rows.sort(key=lambda item: parse_dt(item[2]) or target_cutoff)
        result_rows = result_rows[-window:]
        if not result_rows:
            return []

        driver_lookup = self._driver_lookup(season)
        driver_results: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        team_points: defaultdict[str, list[float]] = defaultdict(list)
        team_finishes: defaultdict[str, list[int]] = defaultdict(list)
        source_parts = []

        for _, result, observed_at in result_rows:
            source_parts.append(normalize_event_name(result.event_name))
            for row in result.classified:
                driver_id = self._result_driver_id(row, driver_lookup)
                if driver_id is None or driver_id not in season.drivers:
                    continue
                points = float(row.get("points") or 0.0)
                position = int(row.get("position") or 99)
                grid_position = int(row.get("grid_position") or position or 99)
                status = str(row.get("status") or "")
                team_id = season.drivers[driver_id].team_id
                driver_results[driver_id].append(
                    {
                        "points": points,
                        "position": position,
                        "grid_position": grid_position,
                        "status": status,
                    }
                )
                team_points[team_id].append(points)
                team_finishes[team_id].append(position)

        if not driver_results:
            return []

        observed_at = max(item[2] for item in result_rows)
        source = f"fastf1_form:{season.season}:{'+'.join(source_parts)}"
        driver_avg_points = {
            driver_id: mean([item["points"] for item in rows])
            for driver_id, rows in driver_results.items()
        }
        field_avg_points = mean(driver_avg_points.values()) if driver_avg_points else 0.0
        driver_avg_grid = {
            driver_id: mean([item["grid_position"] for item in rows if item["grid_position"] > 0])
            for driver_id, rows in driver_results.items()
        }
        field_avg_grid = mean(driver_avg_grid.values()) if driver_avg_grid else 10.5
        adjustments: list[FeatureAdjustment] = []

        confidence = min(0.36, 0.18 + 0.06 * len(result_rows))
        for driver_id, rows in sorted(driver_results.items()):
            avg_points = driver_avg_points.get(driver_id, 0.0)
            point_delta = avg_points - field_avg_points
            value = round(max(-0.08, min(0.08, point_delta / 25.0 * 0.10)), 4)
            adjustments.append(
                FeatureAdjustment(
                    feature_id=f"fastf1-form:{season.season}:{event.event_id}:{driver_id}:race_pace:{len(result_rows)}",
                    event_id=event.event_id,
                    source=source,
                    target_type="driver",
                    target_id=driver_id,
                    metric="race_pace",
                    value=value,
                    confidence=confidence,
                    observed_at=observed_at,
                    explanation=(
                        f"Previous {len(rows)} race result(s) before {event.name}: "
                        f"average points {avg_points:.2f} vs field {field_avg_points:.2f}; "
                        "used as point-in-time race form prior."
                    ),
                )
            )

            avg_grid = driver_avg_grid.get(driver_id)
            if avg_grid is not None:
                grid_delta = field_avg_grid - avg_grid
                quali_value = round(max(-0.05, min(0.05, grid_delta / 10.0 * 0.05)), 4)
                adjustments.append(
                    FeatureAdjustment(
                        feature_id=f"fastf1-form:{season.season}:{event.event_id}:{driver_id}:qualifying_pace:{len(result_rows)}",
                        event_id=event.event_id,
                        source=source,
                        target_type="driver",
                        target_id=driver_id,
                        metric="qualifying_pace",
                        value=quali_value,
                        confidence=max(0.12, confidence - 0.04),
                        observed_at=observed_at,
                        explanation=(
                            f"Previous {len(rows)} race grid result(s) before {event.name}: "
                            f"average grid {avg_grid:.2f} vs field {field_avg_grid:.2f}; "
                            "used as point-in-time qualifying form prior."
                        ),
                    )
                )

            dnf_count = sum(1 for item in rows if not self._finished_status(str(item.get("status") or "")))
            if dnf_count:
                adjustments.append(
                    FeatureAdjustment(
                        feature_id=f"fastf1-form:{season.season}:{event.event_id}:{driver_id}:reliability:{len(result_rows)}",
                        event_id=event.event_id,
                        source=source,
                        target_type="driver",
                        target_id=driver_id,
                        metric="reliability",
                        value=round(-0.012 * dnf_count, 4),
                        confidence=max(0.16, confidence - 0.05),
                        observed_at=observed_at,
                        explanation=(
                            f"{dnf_count} non-finished classification(s) in previous {len(rows)} race result(s); "
                            "used as a small point-in-time reliability risk prior."
                        ),
                    )
                )

        team_avg_points = {
            team_id: mean(points)
            for team_id, points in team_points.items()
            if points
        }
        field_team_points = mean(team_avg_points.values()) if team_avg_points else 0.0
        for team_id, avg_points in sorted(team_avg_points.items()):
            if team_id not in season.teams:
                continue
            team_delta = avg_points - field_team_points
            team_value = round(max(-0.06, min(0.06, team_delta / 25.0 * 0.08)), 4)
            adjustments.append(
                FeatureAdjustment(
                    feature_id=f"fastf1-form:{season.season}:{event.event_id}:{team_id}:race_pace:{len(result_rows)}",
                    event_id=event.event_id,
                    source=source,
                    target_type="team",
                    target_id=team_id,
                    metric="race_pace",
                    value=team_value,
                    confidence=max(0.16, confidence - 0.03),
                    observed_at=observed_at,
                    explanation=(
                        f"Team average driver points over previous {len(result_rows)} race(s): "
                        f"{avg_points:.2f} vs field {field_team_points:.2f}; "
                        "used as point-in-time team form prior."
                    ),
                )
            )

        return adjustments

    @staticmethod
    def _driver_by_openf1_number(season: SeasonState) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for driver in season.drivers.values():
            number = driver.external_ids.get("openf1_driver_number")
            if number:
                mapping[str(number)] = driver.driver_id
        return mapping

    @staticmethod
    def _event_dates(season: SeasonState) -> dict[str, str]:
        return {
            normalize_event_name(event.name): f"{event.date}T23:59:59+00:00"
            for event in season.events
            if event.date
        }

    @staticmethod
    def _driver_lookup(season: SeasonState) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for driver in season.drivers.values():
            candidates = [
                driver.driver_id,
                driver.name,
                driver.name.split()[-1] if driver.name.split() else "",
            ]
            for value in candidates:
                key = ProcessedFeatureProvider._compact(value)
                if key:
                    mapping[key] = driver.driver_id
        return mapping

    @staticmethod
    def _result_driver_id(row: dict[str, Any], driver_lookup: dict[str, str]) -> str | None:
        candidates = [
            str(row.get("driver_id") or ""),
            str(row.get("full_name") or ""),
            str(row.get("full_name") or "").split()[-1] if str(row.get("full_name") or "").split() else "",
        ]
        for candidate in candidates:
            key = ProcessedFeatureProvider._compact(candidate)
            if key in driver_lookup:
                return driver_lookup[key]
        raw_id = str(row.get("driver_id") or "")
        return raw_id or None

    @staticmethod
    def _compact(value: str) -> str:
        return "".join(ch for ch in value.lower() if ch.isalnum())

    @staticmethod
    def _finished_status(status: str) -> bool:
        value = status.strip().lower()
        return value in {"finished", "+1 lap", "+2 laps", "+3 laps", "+4 laps", "+5 laps"}

    @staticmethod
    def _completed_events_before_cutoff(season: SeasonState, cutoff) -> int:
        count = 0
        for race_event in season.events:
            event_dt = parse_dt(f"{race_event.date}T00:00:00+00:00")
            if event_dt is None or event_dt >= cutoff:
                continue
            if race_event.completed and race_event.actual_result:
                count += 1
        return count

    @staticmethod
    def _rank_center(position: int, count: int) -> float:
        if count <= 1:
            return 0.0
        return ((count - position) / (count - 1)) - 0.5

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))

    @staticmethod
    def _race_weather(summary: dict[str, Any]) -> dict[str, Any] | None:
        for session_name, session in summary.get("sessions", {}).items():
            if session_name.startswith("Race_"):
                return session.get("weather")
        return None

    @staticmethod
    def _summary_available_at(summary: dict[str, Any]) -> str:
        dates = [
            str(session.get("date_end"))
            for session in summary.get("session_metadata", [])
            if session.get("date_end")
        ]
        if dates:
            return max(dates)
        return f"{summary.get('year', 1970)}-12-31T00:00:00+00:00"
