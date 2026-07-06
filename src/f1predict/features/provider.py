"""Processed feature provider used by prediction pipelines."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

from f1predict.domain import FeatureAdjustment, RaceEvent, SeasonState, parse_dt
from f1predict.features.openf1_summary import OpenF1SummaryBuilder
from f1predict.official_standings import OfficialStandingsRepository
from f1predict.results import FastF1ResultRepository, NormalizedRaceResult, normalize_event_name
from f1predict.session_laps import FastF1SessionLapRepository, NormalizedSessionLapSummary


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
        session_lap_repository: FastF1SessionLapRepository | None = None,
        official_standings_repository: OfficialStandingsRepository | None = None,
    ) -> None:
        self.processed_root = Path(processed_root)
        self.raw_root = Path(raw_root)
        self.result_repository = result_repository or FastF1ResultRepository(raw_root)
        self.session_lap_repository = session_lap_repository or FastF1SessionLapRepository(raw_root)
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
        adjustments.extend(self._fastf1_session_lap_adjustments(season, event, knowledge_cutoff))
        adjustments.extend(self._fastf1_qualifying_session_adjustments(season, event, knowledge_cutoff))
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
        summary_year = int(summary.get("year") or 0)
        cross_season_analogue = summary_year != season.season
        for session_name, session in summary.get("sessions", {}).items():
            if cross_season_analogue:
                # Cross-season OpenF1 summaries lack historical team context; driver pace would leak old-car performance.
                continue
            laps = session.get("laps")
            if not laps:
                continue
            metric = "qualifying_pace" if "Qualifying" in session_name else "race_pace"
            lap_rows = laps.get("driver_stats") or laps.get("fastest_drivers", [])
            if metric == "race_pace":
                lap_rows = sorted(
                    lap_rows,
                    key=lambda row: row.get("long_run_proxy") or row.get("fast_10_avg") or row.get("fastest_lap") or 999.0,
                )
            else:
                lap_rows = sorted(lap_rows, key=lambda row: row.get("fastest_lap") or 999.0)
            count = max(1, len(lap_rows))
            for rank, row in enumerate(lap_rows, start=1):
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

    def _fastf1_qualifying_session_adjustments(
        self,
        season: SeasonState,
        event: RaceEvent,
        knowledge_cutoff=None,
    ) -> list[FeatureAdjustment]:
        """Convert same-event FastF1 qualifying classification into qualifying priors."""

        target_cutoff = (
            parse_dt(str(knowledge_cutoff))
            if knowledge_cutoff
            else parse_dt(f"{event.date}T00:00:00+00:00")
        )
        if target_cutoff is None:
            return []
        result = self.result_repository.latest_session_results_by_event(
            season.season,
            session_names={"q", "qualifying"},
        ).get(normalize_event_name(event.name))
        if result is None:
            return []
        observed_at = self._session_observed_at(result)
        observed_dt = parse_dt(observed_at)
        if observed_dt is None or observed_dt > target_cutoff:
            return []

        driver_lookup = self._driver_lookup(season)
        rows = [
            row
            for row in result.classified
            if row.get("position") and self._result_driver_id(row, driver_lookup) in season.drivers
        ]
        if not rows:
            return []

        driver_count = len(rows)
        source = (
            f"fastf1_qualifying_result:{season.season}:{normalize_event_name(result.event_name)}:"
            f"{observed_at}:captured_at={result.captured_at}"
        )
        adjustments: list[FeatureAdjustment] = []
        positions_by_team: defaultdict[str, list[int]] = defaultdict(list)
        for row in rows:
            driver_id = self._result_driver_id(row, driver_lookup)
            if driver_id is None or driver_id not in season.drivers:
                continue
            position = int(row.get("position") or 0)
            if position <= 0:
                continue
            centered = self._rank_center(position, driver_count)
            value = round(self._clamp(centered * 0.46, -0.23, 0.23), 4)
            confidence = 0.78
            team_id = season.drivers[driver_id].team_id
            positions_by_team[team_id].append(position)
            adjustments.append(
                FeatureAdjustment(
                    feature_id=(
                        f"fastf1-qualifying-result:{season.season}:{event.event_id}:"
                        f"{driver_id}:qualifying_pace:{observed_at}"
                    ),
                    event_id=event.event_id,
                    source=source,
                    target_type="driver",
                    target_id=driver_id,
                    metric="qualifying_pace",
                    value=value,
                    confidence=confidence,
                    observed_at=observed_at,
                    explanation=(
                        f"Same-event FastF1 qualifying classification before {event.name}: "
                        f"P{position}/{driver_count}; used as a strong cutoff-valid qualifying/grid signal. "
                        "It primarily affects sampled grid order and is not treated as direct race pace."
                    ),
                )
            )
            track_position_value = round(self._clamp(centered * 0.055, -0.0275, 0.0275), 4)
            adjustments.append(
                FeatureAdjustment(
                    feature_id=(
                        f"fastf1-qualifying-result:{season.season}:{event.event_id}:"
                        f"{driver_id}:race_execution:{observed_at}"
                    ),
                    event_id=event.event_id,
                    source=source,
                    target_type="driver",
                    target_id=driver_id,
                    metric="race_execution",
                    value=track_position_value,
                    confidence=0.66,
                    observed_at=observed_at,
                    explanation=(
                        f"Same-event FastF1 qualifying classification before {event.name}: "
                        f"P{position}/{driver_count}; used as a cutoff-valid starting-position and "
                        "traffic/clean-air conversion signal for the race. It is not treated as raw car race pace."
                    ),
                )
            )

        team_average_position = {
            team_id: mean(positions)
            for team_id, positions in positions_by_team.items()
            if positions and team_id in season.teams
        }
        if team_average_position:
            team_count = len(team_average_position)
            ranked_team_ids = sorted(team_average_position, key=lambda team_id: team_average_position[team_id])
            for team_rank, team_id in enumerate(ranked_team_ids, start=1):
                centered = self._rank_center(team_rank, team_count)
                value = round(self._clamp(centered * 0.20, -0.10, 0.10), 4)
                if not value:
                    continue
                adjustments.append(
                    FeatureAdjustment(
                        feature_id=(
                            f"fastf1-qualifying-result:{season.season}:{event.event_id}:"
                            f"{team_id}:qualifying_pace:{observed_at}"
                        ),
                        event_id=event.event_id,
                        source=source,
                        target_type="team",
                        target_id=team_id,
                        metric="qualifying_pace",
                        value=value,
                        confidence=0.58,
                        observed_at=observed_at,
                        explanation=(
                            f"Same-event FastF1 qualifying team average position before {event.name}: "
                            f"{team_average_position[team_id]:.2f}; used as a team-level qualifying form signal."
                        ),
                    )
                )
        return adjustments

    def _fastf1_session_lap_adjustments(
        self,
        season: SeasonState,
        event: RaceEvent,
        knowledge_cutoff=None,
    ) -> list[FeatureAdjustment]:
        """Convert same-event FastF1 lap summaries into cutoff-safe pace inputs."""

        target_cutoff = (
            parse_dt(str(knowledge_cutoff))
            if knowledge_cutoff
            else parse_dt(f"{event.date}T00:00:00+00:00")
        )
        if target_cutoff is None:
            return []

        summaries = self.session_lap_repository.latest_for_event(
            season.season,
            event.name,
            session_names={"FP1", "FP2", "FP3", "Q", "SQ", "S"},
        )
        if not summaries:
            return []

        driver_lookup = self._driver_lookup(season)
        by_number = self._driver_by_openf1_number(season)
        adjustments: list[FeatureAdjustment] = []
        for summary in summaries:
            observed_at = summary.session_date or summary.captured_at
            observed_dt = parse_dt(observed_at)
            if observed_dt is None or observed_dt > target_cutoff:
                continue
            if summary.session_key in {"qualifying", "sprintqualifying"}:
                adjustments.extend(
                    self._fastf1_qualifying_lap_adjustments(
                        season,
                        event,
                        summary,
                        observed_at,
                        driver_lookup,
                        by_number,
                    )
                )
                continue
            adjustments.extend(
                self._fastf1_practice_lap_adjustments(
                    season,
                    event,
                    summary,
                    observed_at,
                    driver_lookup,
                    by_number,
                )
            )
        return adjustments

    def _fastf1_practice_lap_adjustments(
        self,
        season: SeasonState,
        event: RaceEvent,
        summary: NormalizedSessionLapSummary,
        observed_at: str,
        driver_lookup: dict[str, str],
        by_number: dict[str, str],
    ) -> list[FeatureAdjustment]:
        rows = self._mapped_session_rows(season, summary, driver_lookup, by_number)
        long_run_rows = [
            row for row in rows
            if row.get("long_run_proxy_seconds") is not None
            and int(row.get("long_run_lap_count") or 0) >= 3
        ]
        long_run_rows = self._session_inlier_rows(long_run_rows, "long_run_proxy_seconds", max_from_median=6.0)
        if not long_run_rows:
            return []

        source = self._fastf1_session_source(summary, observed_at)
        confidence_base = self._session_lap_confidence(summary.session_key, "race_pace")
        field_long_run, long_run_scale = self._center_scale_values(
            [float(row["long_run_proxy_seconds"]) for row in long_run_rows],
            minimum_scale=0.85,
        )
        adjustments: list[FeatureAdjustment] = []
        team_long_runs: defaultdict[str, list[float]] = defaultdict(list)
        for row in long_run_rows:
            driver_id = str(row["mapped_driver_id"])
            driver = season.drivers[driver_id]
            team_long_runs[driver.team_id].append(float(row["long_run_proxy_seconds"]))
            clean_laps = int(row.get("clean_lap_count") or 0)
            session_weight = min(1.0, max(0.45, clean_laps / 10.0))
            delta = field_long_run - float(row["long_run_proxy_seconds"])
            value = round(self._clamp(delta / long_run_scale * 0.085, -0.085, 0.085), 4)
            adjustments.append(
                FeatureAdjustment(
                    feature_id=(
                        f"fastf1-session-laps:{summary.year}:{event.event_id}:{summary.session_key}:"
                        f"{driver_id}:race_pace:{observed_at}"
                    ),
                    event_id=event.event_id,
                    source=source,
                    target_type="driver",
                    target_id=driver_id,
                    metric="race_pace",
                    value=value,
                    confidence=round(confidence_base * session_weight, 4),
                    observed_at=observed_at,
                    explanation=(
                        f"{summary.session_name} long-run proxy before {event.name}: "
                        f"{row['long_run_proxy_seconds']:.3f}s vs field {field_long_run:.3f}s "
                        f"over {row.get('long_run_lap_count')} clean lap(s); used as a same-weekend race-pace signal."
                    ),
                )
            )

        tyre_deg_rows = [
            row for row in long_run_rows
            if row.get("tyre_deg_proxy_seconds_per_lap") is not None
            and int(row.get("long_run_lap_count") or 0) >= 4
        ]
        tyre_deg_rows = self._session_inlier_rows(
            tyre_deg_rows,
            "tyre_deg_proxy_seconds_per_lap",
            max_from_median=4.0,
        )
        if tyre_deg_rows:
            field_deg, deg_scale = self._center_scale_values(
                [float(row["tyre_deg_proxy_seconds_per_lap"]) for row in tyre_deg_rows],
                minimum_scale=0.45,
            )
            for row in tyre_deg_rows:
                driver_id = str(row["mapped_driver_id"])
                deg = float(row["tyre_deg_proxy_seconds_per_lap"])
                value = round(self._clamp((field_deg - deg) / deg_scale * 0.045, -0.045, 0.045), 4)
                if not value:
                    continue
                adjustments.append(
                    FeatureAdjustment(
                        feature_id=(
                            f"fastf1-session-laps:{summary.year}:{event.event_id}:{summary.session_key}:"
                            f"{driver_id}:tyre_deg:{observed_at}"
                        ),
                        event_id=event.event_id,
                        source=source,
                        target_type="driver",
                        target_id=driver_id,
                        metric="tyre_deg",
                        value=value,
                        confidence=round(self._session_lap_confidence(summary.session_key, "tyre_deg"), 4),
                        observed_at=observed_at,
                        explanation=(
                            f"{summary.session_name} tyre-degradation proxy before {event.name}: "
                            f"{deg:+.4f}s/lap vs field {field_deg:+.4f}s/lap; lower degradation improves strategy pace."
                        ),
                    )
                )

        speed_rows = [row for row in rows if row.get("speed_st_avg_kph") is not None]
        if len(speed_rows) >= 3:
            field_speed, speed_scale = self._center_scale_values(
                [float(row["speed_st_avg_kph"]) for row in speed_rows],
                minimum_scale=8.0,
            )
            for row in speed_rows:
                driver_id = str(row["mapped_driver_id"])
                speed = float(row["speed_st_avg_kph"])
                value = round(self._clamp((speed - field_speed) / speed_scale * 0.04, -0.035, 0.035), 4)
                if not value:
                    continue
                adjustments.append(
                    FeatureAdjustment(
                        feature_id=(
                            f"fastf1-session-laps:{summary.year}:{event.event_id}:{summary.session_key}:"
                            f"{driver_id}:straight_line_speed:{observed_at}"
                        ),
                        event_id=event.event_id,
                        source=source,
                        target_type="driver",
                        target_id=driver_id,
                        metric="straight_line_speed",
                        value=value,
                        confidence=round(self._session_lap_confidence(summary.session_key, "straight_line_speed"), 4),
                        observed_at=observed_at,
                        explanation=(
                            f"{summary.session_name} speed-trap average before {event.name}: "
                            f"{speed:.1f} kph vs field {field_speed:.1f} kph; used as a small straight-line signal."
                        ),
                    )
                )

        adjustments.extend(
            self._session_team_pace_adjustments(
                season,
                event,
                team_long_runs,
                source,
                observed_at,
                summary,
            )
        )
        return adjustments

    def _fastf1_qualifying_lap_adjustments(
        self,
        season: SeasonState,
        event: RaceEvent,
        summary: NormalizedSessionLapSummary,
        observed_at: str,
        driver_lookup: dict[str, str],
        by_number: dict[str, str],
    ) -> list[FeatureAdjustment]:
        rows = [
            row for row in self._mapped_session_rows(season, summary, driver_lookup, by_number)
            if row.get("fastest_lap_seconds") is not None
        ]
        if len(rows) < 3:
            return []
        field_fastest, fastest_scale = self._center_scale_values(
            [float(row["fastest_lap_seconds"]) for row in rows],
            minimum_scale=0.55,
        )
        source = self._fastf1_session_source(summary, observed_at)
        confidence = self._session_lap_confidence(summary.session_key, "qualifying_pace")
        adjustments: list[FeatureAdjustment] = []
        team_fastest: defaultdict[str, list[float]] = defaultdict(list)
        for row in rows:
            driver_id = str(row["mapped_driver_id"])
            driver = season.drivers[driver_id]
            lap_time = float(row["fastest_lap_seconds"])
            team_fastest[driver.team_id].append(lap_time)
            value = round(self._clamp((field_fastest - lap_time) / fastest_scale * 0.105, -0.105, 0.105), 4)
            adjustments.append(
                FeatureAdjustment(
                    feature_id=(
                        f"fastf1-session-laps:{summary.year}:{event.event_id}:{summary.session_key}:"
                        f"{driver_id}:qualifying_pace:{observed_at}"
                    ),
                    event_id=event.event_id,
                    source=source,
                    target_type="driver",
                    target_id=driver_id,
                    metric="qualifying_pace",
                    value=value,
                    confidence=confidence,
                    observed_at=observed_at,
                    explanation=(
                        f"{summary.session_name} best valid lap before {event.name}: "
                        f"{lap_time:.3f}s vs field {field_fastest:.3f}s; used as gap-aware qualifying pace, "
                        "separate from the qualifying classification/grid-order feature."
                    ),
                )
            )
        adjustments.extend(
            self._session_team_qualifying_adjustments(
                season,
                event,
                team_fastest,
                source,
                observed_at,
                summary,
            )
        )
        return adjustments

    def _session_team_pace_adjustments(
        self,
        season: SeasonState,
        event: RaceEvent,
        team_long_runs: defaultdict[str, list[float]],
        source: str,
        observed_at: str,
        summary: NormalizedSessionLapSummary,
    ) -> list[FeatureAdjustment]:
        team_avg = {
            team_id: mean(values)
            for team_id, values in team_long_runs.items()
            if values and team_id in season.teams
        }
        if len(team_avg) < 2:
            return []
        field_avg, team_scale = self._center_scale_values(list(team_avg.values()), minimum_scale=0.85)
        confidence = self._session_lap_confidence(summary.session_key, "team_race_pace")
        adjustments: list[FeatureAdjustment] = []
        for team_id, lap_time in sorted(team_avg.items()):
            value = round(self._clamp((field_avg - lap_time) / team_scale * 0.065, -0.065, 0.065), 4)
            if not value:
                continue
            adjustments.append(
                FeatureAdjustment(
                    feature_id=(
                        f"fastf1-session-laps:{summary.year}:{event.event_id}:{summary.session_key}:"
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
                        f"{summary.session_name} team long-run proxy before {event.name}: "
                        f"{lap_time:.3f}s vs team field {field_avg:.3f}s; used as same-weekend car race pace."
                    ),
                )
            )
        return adjustments

    def _session_team_qualifying_adjustments(
        self,
        season: SeasonState,
        event: RaceEvent,
        team_fastest: defaultdict[str, list[float]],
        source: str,
        observed_at: str,
        summary: NormalizedSessionLapSummary,
    ) -> list[FeatureAdjustment]:
        team_avg = {
            team_id: mean(values)
            for team_id, values in team_fastest.items()
            if values and team_id in season.teams
        }
        if len(team_avg) < 2:
            return []
        field_avg, team_scale = self._center_scale_values(list(team_avg.values()), minimum_scale=0.55)
        confidence = self._session_lap_confidence(summary.session_key, "team_qualifying_pace")
        adjustments: list[FeatureAdjustment] = []
        for team_id, lap_time in sorted(team_avg.items()):
            value = round(self._clamp((field_avg - lap_time) / team_scale * 0.075, -0.075, 0.075), 4)
            if not value:
                continue
            adjustments.append(
                FeatureAdjustment(
                    feature_id=(
                        f"fastf1-session-laps:{summary.year}:{event.event_id}:{summary.session_key}:"
                        f"{team_id}:qualifying_pace:{observed_at}"
                    ),
                    event_id=event.event_id,
                    source=source,
                    target_type="team",
                    target_id=team_id,
                    metric="qualifying_pace",
                    value=value,
                    confidence=confidence,
                    observed_at=observed_at,
                    explanation=(
                        f"{summary.session_name} team best-lap proxy before {event.name}: "
                        f"{lap_time:.3f}s vs team field {field_avg:.3f}s; used as same-weekend car qualifying pace."
                    ),
                )
            )
        return adjustments

    def _mapped_session_rows(
        self,
        season: SeasonState,
        summary: NormalizedSessionLapSummary,
        driver_lookup: dict[str, str],
        by_number: dict[str, str],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in summary.driver_stats:
            driver_id = self._session_lap_driver_id(row, driver_lookup, by_number)
            if driver_id is None or driver_id not in season.drivers:
                continue
            rows.append({**row, "mapped_driver_id": driver_id})
        return rows

    @staticmethod
    def _session_lap_driver_id(
        row: dict[str, Any],
        driver_lookup: dict[str, str],
        by_number: dict[str, str],
    ) -> str | None:
        full_name = str(row.get("full_name") or "")
        candidates = [
            str(row.get("driver_id") or ""),
            full_name,
            full_name.split()[-1] if full_name.split() else "",
        ]
        for candidate in candidates:
            key = ProcessedFeatureProvider._compact(candidate)
            if key in driver_lookup:
                return driver_lookup[key]
        driver_number = str(row.get("driver_number") or "")
        if driver_number in by_number:
            return by_number[driver_number]
        return None

    @staticmethod
    def _fastf1_session_source(summary: NormalizedSessionLapSummary, observed_at: str) -> str:
        quality = "retrospective_snapshot" if summary.captured_at > observed_at else "source_backed"
        return (
            f"fastf1_session_laps:{summary.year}:{normalize_event_name(summary.event_name)}:"
            f"{summary.session_key}:{observed_at}:captured_at={summary.captured_at}:quality={quality}:path={summary.path}"
        )

    @staticmethod
    def _session_lap_confidence(session_key: str, metric: str) -> float:
        session_weights = {
            "practice1": 0.68,
            "practice2": 1.00,
            "practice3": 0.82,
            "qualifying": 1.00,
            "sprintqualifying": 0.86,
            "sprint": 0.88,
        }
        metric_base = {
            "race_pace": 0.42,
            "team_race_pace": 0.34,
            "tyre_deg": 0.30,
            "straight_line_speed": 0.24,
            "qualifying_pace": 0.44,
            "team_qualifying_pace": 0.34,
        }
        return round(metric_base.get(metric, 0.25) * session_weights.get(session_key, 0.55), 4)

    @classmethod
    def _session_inlier_rows(
        cls,
        rows: list[dict[str, Any]],
        key: str,
        max_from_median: float,
    ) -> list[dict[str, Any]]:
        values = [float(row[key]) for row in rows if row.get(key) is not None]
        if len(values) < 4:
            return rows
        center = median(values)
        return [
            row for row in rows
            if row.get(key) is not None and abs(float(row[key]) - center) <= max_from_median
        ]

    @staticmethod
    def _center_scale_values(values: list[float], minimum_scale: float) -> tuple[float, float]:
        if not values:
            return 0.0, minimum_scale
        ordered = sorted(values)
        center = median(ordered)
        if len(ordered) < 4:
            return center, max(minimum_scale, max(ordered) - min(ordered), minimum_scale)
        q1 = ordered[max(0, len(ordered) // 4)]
        q3 = ordered[min(len(ordered) - 1, (len(ordered) * 3) // 4)]
        iqr = max(0.0, q3 - q1)
        return center, max(minimum_scale, iqr * 1.35)

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
        all_result_rows = list(result_rows)
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
        driver_avg_conversion = self._average_grid_conversion(driver_results)
        field_avg_conversion = mean(driver_avg_conversion.values()) if driver_avg_conversion else 0.0
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

            avg_conversion = driver_avg_conversion.get(driver_id)
            if avg_conversion is not None:
                execution_delta = avg_conversion - field_avg_conversion
                execution_value = round(self._clamp(execution_delta / 8.0 * 0.04, -0.035, 0.035), 4)
                if execution_value:
                    adjustments.append(
                        FeatureAdjustment(
                            feature_id=(
                                f"fastf1-form:{season.season}:{event.event_id}:"
                                f"{driver_id}:race_execution:{len(result_rows)}"
                            ),
                            event_id=event.event_id,
                            source=source,
                            target_type="driver",
                            target_id=driver_id,
                            metric="race_execution",
                            value=execution_value,
                            confidence=max(0.12, confidence - 0.06),
                            observed_at=observed_at,
                            explanation=(
                                f"Previous {len(rows)} finished race result(s) before {event.name}: "
                                f"average opportunity-normalized grid-to-finish conversion {avg_conversion:+.2f} vs field "
                                f"{field_avg_conversion:+.2f}; used as point-in-time race execution prior."
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

        team_avg_conversion = self._team_average_grid_conversion(season, driver_results)
        field_team_conversion = mean(team_avg_conversion.values()) if team_avg_conversion else 0.0
        for team_id, avg_conversion in sorted(team_avg_conversion.items()):
            if team_id not in season.teams:
                continue
            execution_delta = avg_conversion - field_team_conversion
            team_execution_value = round(self._clamp(execution_delta / 8.0 * 0.03, -0.03, 0.03), 4)
            if not team_execution_value:
                continue
            adjustments.append(
                FeatureAdjustment(
                    feature_id=(
                        f"fastf1-form:{season.season}:{event.event_id}:"
                        f"{team_id}:race_execution:{len(result_rows)}"
                    ),
                    event_id=event.event_id,
                    source=source,
                    target_type="team",
                    target_id=team_id,
                    metric="race_execution",
                    value=team_execution_value,
                    confidence=max(0.12, confidence - 0.07),
                    observed_at=observed_at,
                    explanation=(
                        f"Team opportunity-normalized finished-race grid-to-finish conversion over previous {len(result_rows)} race(s): "
                        f"{avg_conversion:+.2f} vs field {field_team_conversion:+.2f}; "
                        "used as point-in-time team race execution prior."
                    ),
                )
            )

        adjustments.extend(
            self._fastf1_season_trend_adjustments(
                season,
                event,
                all_result_rows,
                result_rows,
                driver_lookup,
                target_cutoff,
            )
        )
        return adjustments

    def _fastf1_season_trend_adjustments(
        self,
        season: SeasonState,
        event: RaceEvent,
        all_result_rows: list[tuple[str, NormalizedRaceResult, str]],
        recent_result_rows: list[tuple[str, NormalizedRaceResult, str]],
        driver_lookup: dict[str, str],
        target_cutoff,
    ) -> list[FeatureAdjustment]:
        if len(all_result_rows) < 2:
            return []

        all_driver_results, all_team_points, all_source_parts = self._collect_fastf1_form_inputs(
            season,
            all_result_rows,
            driver_lookup,
        )
        recent_driver_results, recent_team_points, recent_source_parts = self._collect_fastf1_form_inputs(
            season,
            recent_result_rows,
            driver_lookup,
        )
        older_result_rows = all_result_rows[: -len(recent_result_rows)] if recent_result_rows else []
        older_driver_results, older_team_points, _ = self._collect_fastf1_form_inputs(
            season,
            older_result_rows,
            driver_lookup,
        )
        if not all_driver_results:
            return []

        observed_at = max(item[2] for item in all_result_rows)
        race_count = len(all_result_rows)
        source = (
            f"fastf1_season_form:{season.season}:"
            f"{self._source_span(all_source_parts)}:{race_count}_races"
        )
        adjustments: list[FeatureAdjustment] = []

        driver_avg_points = {
            driver_id: mean([item["points"] for item in rows])
            for driver_id, rows in all_driver_results.items()
        }
        field_avg_points = mean(driver_avg_points.values()) if driver_avg_points else 0.0
        driver_avg_grid = {
            driver_id: mean([item["grid_position"] for item in rows if item["grid_position"] > 0])
            for driver_id, rows in all_driver_results.items()
            if any(item["grid_position"] > 0 for item in rows)
        }
        field_avg_grid = mean(driver_avg_grid.values()) if driver_avg_grid else 10.5
        driver_avg_conversion = self._average_grid_conversion(all_driver_results)
        field_avg_conversion = mean(driver_avg_conversion.values()) if driver_avg_conversion else 0.0
        season_confidence = min(0.34, 0.14 + 0.025 * race_count)

        for driver_id, rows in sorted(all_driver_results.items()):
            avg_points = driver_avg_points.get(driver_id, 0.0)
            value = round(self._clamp((avg_points - field_avg_points) / 25.0 * 0.075, -0.06, 0.06), 4)
            adjustments.append(
                FeatureAdjustment(
                    feature_id=(
                        f"fastf1-season-form:{season.season}:{event.event_id}:"
                        f"{driver_id}:race_pace:{race_count}"
                    ),
                    event_id=event.event_id,
                    source=source,
                    target_type="driver",
                    target_id=driver_id,
                    metric="race_pace",
                    value=value,
                    confidence=season_confidence,
                    observed_at=observed_at,
                    explanation=(
                        f"Season-to-date FastF1 race results before {event.name}: "
                        f"{race_count} race(s), driver average points {avg_points:.2f} vs field "
                        f"{field_avg_points:.2f}; used as a broader form prior than the recent-window signal."
                    ),
                )
            )

            avg_grid = driver_avg_grid.get(driver_id)
            if avg_grid is not None:
                qualifying_value = round(
                    self._clamp((field_avg_grid - avg_grid) / 10.0 * 0.04, -0.04, 0.04),
                    4,
                )
                adjustments.append(
                    FeatureAdjustment(
                        feature_id=(
                            f"fastf1-season-form:{season.season}:{event.event_id}:"
                            f"{driver_id}:qualifying_pace:{race_count}"
                        ),
                        event_id=event.event_id,
                        source=source,
                        target_type="driver",
                        target_id=driver_id,
                        metric="qualifying_pace",
                        value=qualifying_value,
                        confidence=max(0.12, season_confidence - 0.05),
                        observed_at=observed_at,
                        explanation=(
                            f"Season-to-date FastF1 grid results before {event.name}: "
                            f"average grid {avg_grid:.2f} vs field {field_avg_grid:.2f}; "
                            "used as a broader qualifying-form prior."
                        ),
                    )
                )

            avg_conversion = driver_avg_conversion.get(driver_id)
            if avg_conversion is not None:
                execution_value = round(
                    self._clamp((avg_conversion - field_avg_conversion) / 8.0 * 0.035, -0.03, 0.03),
                    4,
                )
                if execution_value:
                    adjustments.append(
                        FeatureAdjustment(
                            feature_id=(
                                f"fastf1-season-form:{season.season}:{event.event_id}:"
                                f"{driver_id}:race_execution:{race_count}"
                            ),
                            event_id=event.event_id,
                            source=source,
                            target_type="driver",
                            target_id=driver_id,
                            metric="race_execution",
                            value=execution_value,
                            confidence=max(0.11, season_confidence - 0.06),
                            observed_at=observed_at,
                            explanation=(
                                f"Season-to-date FastF1 finished races before {event.name}: "
                                f"average opportunity-normalized grid-to-finish conversion {avg_conversion:+.2f} vs field "
                                f"{field_avg_conversion:+.2f}; used as a broader race execution prior."
                            ),
                        )
                    )

            dnf_count = sum(1 for item in rows if not self._finished_status(str(item.get("status") or "")))
            if dnf_count:
                adjustments.append(
                    FeatureAdjustment(
                        feature_id=(
                            f"fastf1-season-form:{season.season}:{event.event_id}:"
                            f"{driver_id}:reliability:{race_count}"
                        ),
                        event_id=event.event_id,
                        source=source,
                        target_type="driver",
                        target_id=driver_id,
                        metric="reliability",
                        value=round(-0.006 * dnf_count, 4),
                        confidence=max(0.12, season_confidence - 0.07),
                        observed_at=observed_at,
                        explanation=(
                            f"{dnf_count} non-finished classification(s) across {race_count} "
                            "cutoff-valid FastF1 result(s); used as a season reliability risk prior."
                        ),
                    )
                )

        adjustments.extend(
            self._fastf1_momentum_adjustments(
                season,
                event,
                recent_driver_results,
                older_driver_results,
                recent_team_points,
                older_team_points,
                recent_source_parts,
                observed_at,
                race_count,
                target_cutoff,
            )
        )
        adjustments.extend(
            self._fastf1_team_season_adjustments(
                season,
                event,
                all_team_points,
                field_label=f"{race_count} race(s)",
                source=source,
                observed_at=observed_at,
                confidence=max(0.14, season_confidence - 0.02),
                feature_namespace="fastf1-season-form",
            )
        )
        adjustments.extend(
            self._fastf1_team_execution_adjustments(
                season,
                event,
                all_driver_results,
                field_label=f"{race_count} race(s)",
                source=source,
                observed_at=observed_at,
                confidence=max(0.11, season_confidence - 0.07),
                feature_namespace="fastf1-season-form",
            )
        )
        adjustments.extend(
            self._fastf1_team_strength_reestimate_adjustments(
                season,
                event,
                all_result_rows,
                recent_result_rows,
                driver_lookup,
                observed_at,
            )
        )
        adjustments.extend(
            self._fastf1_team_finish_position_adjustments(
                season,
                event,
                all_result_rows,
                recent_result_rows,
                driver_lookup,
                observed_at,
            )
        )
        return adjustments

    def _fastf1_momentum_adjustments(
        self,
        season: SeasonState,
        event: RaceEvent,
        recent_driver_results: defaultdict[str, list[dict[str, Any]]],
        older_driver_results: defaultdict[str, list[dict[str, Any]]],
        recent_team_points: defaultdict[str, list[float]],
        older_team_points: defaultdict[str, list[float]],
        recent_source_parts: list[str],
        observed_at: str,
        race_count: int,
        target_cutoff,
    ) -> list[FeatureAdjustment]:
        if not older_driver_results or not recent_driver_results:
            return []

        source = (
            f"fastf1_momentum:{season.season}:"
            f"{self._source_span(recent_source_parts)}:cutoff_{target_cutoff.isoformat()}"
        )
        confidence = min(0.28, 0.12 + 0.02 * race_count)
        adjustments: list[FeatureAdjustment] = []

        recent_avg_points = self._average_metric(recent_driver_results, "points")
        older_avg_points = self._average_metric(older_driver_results, "points")
        recent_field_points = mean(recent_avg_points.values()) if recent_avg_points else 0.0
        older_field_points = mean(older_avg_points.values()) if older_avg_points else 0.0
        recent_avg_grid = self._average_positive_metric(recent_driver_results, "grid_position")
        older_avg_grid = self._average_positive_metric(older_driver_results, "grid_position")
        recent_field_grid = mean(recent_avg_grid.values()) if recent_avg_grid else 10.5
        older_field_grid = mean(older_avg_grid.values()) if older_avg_grid else 10.5
        recent_avg_conversion = self._average_grid_conversion(recent_driver_results)
        older_avg_conversion = self._average_grid_conversion(older_driver_results)
        recent_field_conversion = mean(recent_avg_conversion.values()) if recent_avg_conversion else 0.0
        older_field_conversion = mean(older_avg_conversion.values()) if older_avg_conversion else 0.0

        for driver_id in sorted(set(recent_driver_results) & set(older_driver_results)):
            recent_relative = recent_avg_points.get(driver_id, 0.0) - recent_field_points
            older_relative = older_avg_points.get(driver_id, 0.0) - older_field_points
            momentum_delta = recent_relative - older_relative
            value = round(self._clamp(momentum_delta / 25.0 * 0.06, -0.045, 0.045), 4)
            adjustments.append(
                FeatureAdjustment(
                    feature_id=(
                        f"fastf1-momentum:{season.season}:{event.event_id}:"
                        f"{driver_id}:race_pace:{race_count}"
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
                        f"FastF1 recent-vs-older form before {event.name}: relative points delta "
                        f"{momentum_delta:.2f}; used as momentum signal so late-season improvement or decline "
                        "can move the race-pace prior."
                    ),
                )
            )

            if driver_id in recent_avg_grid and driver_id in older_avg_grid:
                recent_grid_relative = recent_field_grid - recent_avg_grid[driver_id]
                older_grid_relative = older_field_grid - older_avg_grid[driver_id]
                grid_delta = recent_grid_relative - older_grid_relative
                qualifying_value = round(self._clamp(grid_delta / 10.0 * 0.035, -0.035, 0.035), 4)
                adjustments.append(
                    FeatureAdjustment(
                        feature_id=(
                            f"fastf1-momentum:{season.season}:{event.event_id}:"
                            f"{driver_id}:qualifying_pace:{race_count}"
                        ),
                        event_id=event.event_id,
                        source=source,
                        target_type="driver",
                        target_id=driver_id,
                        metric="qualifying_pace",
                        value=qualifying_value,
                        confidence=max(0.10, confidence - 0.05),
                        observed_at=observed_at,
                        explanation=(
                            f"FastF1 recent-vs-older grid form before {event.name}: relative grid delta "
                            f"{grid_delta:.2f}; used as qualifying momentum signal."
                        ),
                    )
                )

            if driver_id in recent_avg_conversion and driver_id in older_avg_conversion:
                recent_conversion_relative = recent_avg_conversion[driver_id] - recent_field_conversion
                older_conversion_relative = older_avg_conversion[driver_id] - older_field_conversion
                conversion_delta = recent_conversion_relative - older_conversion_relative
                execution_value = round(self._clamp(conversion_delta / 8.0 * 0.035, -0.03, 0.03), 4)
                if execution_value:
                    adjustments.append(
                        FeatureAdjustment(
                            feature_id=(
                                f"fastf1-momentum:{season.season}:{event.event_id}:"
                                f"{driver_id}:race_execution:{race_count}"
                            ),
                            event_id=event.event_id,
                            source=source,
                            target_type="driver",
                            target_id=driver_id,
                            metric="race_execution",
                            value=execution_value,
                            confidence=max(0.10, confidence - 0.06),
                            observed_at=observed_at,
                            explanation=(
                                f"FastF1 recent-vs-older finished-race grid conversion before {event.name}: "
                                f"relative conversion delta {conversion_delta:+.2f}; used as race execution momentum."
                            ),
                        )
                    )

        recent_team_avg = {
            team_id: mean(points)
            for team_id, points in recent_team_points.items()
            if points
        }
        older_team_avg = {
            team_id: mean(points)
            for team_id, points in older_team_points.items()
            if points
        }
        recent_team_field = mean(recent_team_avg.values()) if recent_team_avg else 0.0
        older_team_field = mean(older_team_avg.values()) if older_team_avg else 0.0
        for team_id in sorted(set(recent_team_avg) & set(older_team_avg)):
            if team_id not in season.teams:
                continue
            recent_relative = recent_team_avg[team_id] - recent_team_field
            older_relative = older_team_avg[team_id] - older_team_field
            team_delta = recent_relative - older_relative
            value = round(self._clamp(team_delta / 25.0 * 0.05, -0.04, 0.04), 4)
            adjustments.append(
                FeatureAdjustment(
                    feature_id=(
                        f"fastf1-momentum:{season.season}:{event.event_id}:"
                        f"{team_id}:race_pace:{race_count}"
                    ),
                    event_id=event.event_id,
                    source=source,
                    target_type="team",
                    target_id=team_id,
                    metric="race_pace",
                    value=value,
                    confidence=max(0.12, confidence - 0.03),
                    observed_at=observed_at,
                    explanation=(
                        f"FastF1 recent-vs-older team form before {event.name}: relative points delta "
                        f"{team_delta:.2f}; used as team momentum signal."
                    ),
                )
            )

        recent_team_conversion = self._team_average_grid_conversion(season, recent_driver_results)
        older_team_conversion = self._team_average_grid_conversion(season, older_driver_results)
        recent_team_field_conversion = mean(recent_team_conversion.values()) if recent_team_conversion else 0.0
        older_team_field_conversion = mean(older_team_conversion.values()) if older_team_conversion else 0.0
        for team_id in sorted(set(recent_team_conversion) & set(older_team_conversion)):
            if team_id not in season.teams:
                continue
            recent_relative = recent_team_conversion[team_id] - recent_team_field_conversion
            older_relative = older_team_conversion[team_id] - older_team_field_conversion
            conversion_delta = recent_relative - older_relative
            value = round(self._clamp(conversion_delta / 8.0 * 0.03, -0.025, 0.025), 4)
            if not value:
                continue
            adjustments.append(
                FeatureAdjustment(
                    feature_id=(
                        f"fastf1-momentum:{season.season}:{event.event_id}:"
                        f"{team_id}:race_execution:{race_count}"
                    ),
                    event_id=event.event_id,
                    source=source,
                    target_type="team",
                    target_id=team_id,
                    metric="race_execution",
                    value=value,
                    confidence=max(0.10, confidence - 0.07),
                    observed_at=observed_at,
                    explanation=(
                        f"FastF1 recent-vs-older team grid conversion before {event.name}: "
                        f"relative conversion delta {conversion_delta:+.2f}; used as team race execution momentum."
                    ),
                )
            )

        return adjustments

    def _fastf1_team_season_adjustments(
        self,
        season: SeasonState,
        event: RaceEvent,
        team_points: defaultdict[str, list[float]],
        field_label: str,
        source: str,
        observed_at: str,
        confidence: float,
        feature_namespace: str,
    ) -> list[FeatureAdjustment]:
        team_avg_points = {
            team_id: mean(points)
            for team_id, points in team_points.items()
            if points
        }
        field_team_points = mean(team_avg_points.values()) if team_avg_points else 0.0
        adjustments: list[FeatureAdjustment] = []
        for team_id, avg_points in sorted(team_avg_points.items()):
            if team_id not in season.teams:
                continue
            value = round(self._clamp((avg_points - field_team_points) / 25.0 * 0.06, -0.05, 0.05), 4)
            adjustments.append(
                FeatureAdjustment(
                    feature_id=(
                        f"{feature_namespace}:{season.season}:{event.event_id}:"
                        f"{team_id}:race_pace:{field_label.replace(' ', '_')}"
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
                        f"Team average driver points across {field_label} before {event.name}: "
                        f"{avg_points:.2f} vs field {field_team_points:.2f}; "
                        "used as a season-to-date team form prior."
                    ),
                )
            )
        return adjustments

    def _fastf1_team_execution_adjustments(
        self,
        season: SeasonState,
        event: RaceEvent,
        driver_results: defaultdict[str, list[dict[str, Any]]],
        field_label: str,
        source: str,
        observed_at: str,
        confidence: float,
        feature_namespace: str,
    ) -> list[FeatureAdjustment]:
        team_avg_conversion = self._team_average_grid_conversion(season, driver_results)
        field_team_conversion = mean(team_avg_conversion.values()) if team_avg_conversion else 0.0
        adjustments: list[FeatureAdjustment] = []
        for team_id, avg_conversion in sorted(team_avg_conversion.items()):
            if team_id not in season.teams:
                continue
            value = round(self._clamp((avg_conversion - field_team_conversion) / 8.0 * 0.025, -0.025, 0.025), 4)
            if not value:
                continue
            adjustments.append(
                FeatureAdjustment(
                    feature_id=(
                        f"{feature_namespace}:{season.season}:{event.event_id}:"
                        f"{team_id}:race_execution:{field_label.replace(' ', '_')}"
                    ),
                    event_id=event.event_id,
                    source=source,
                    target_type="team",
                    target_id=team_id,
                    metric="race_execution",
                    value=value,
                    confidence=confidence,
                    observed_at=observed_at,
                    explanation=(
                        f"Team average opportunity-normalized finished-race grid-to-finish conversion across {field_label} before "
                        f"{event.name}: {avg_conversion:+.2f} vs field {field_team_conversion:+.2f}; "
                        "used as a season-to-date team race execution prior."
                    ),
                )
            )
        return adjustments

    def _fastf1_team_strength_reestimate_adjustments(
        self,
        season: SeasonState,
        event: RaceEvent,
        all_result_rows: list[tuple[str, NormalizedRaceResult, str]],
        recent_result_rows: list[tuple[str, NormalizedRaceResult, str]],
        driver_lookup: dict[str, str],
        observed_at: str,
    ) -> list[FeatureAdjustment]:
        if len(all_result_rows) < 2:
            return []
        all_team_totals = self._team_event_point_totals(season, all_result_rows, driver_lookup)
        recent_team_totals = self._team_event_point_totals(season, recent_result_rows, driver_lookup)
        if not all_team_totals:
            return []

        all_team_avg = {
            team_id: mean(points)
            for team_id, points in all_team_totals.items()
            if points and team_id in season.teams
        }
        recent_team_avg = {
            team_id: mean(points)
            for team_id, points in recent_team_totals.items()
            if points and team_id in season.teams
        }
        team_ids = sorted(team_id for team_id in all_team_avg if team_id in season.teams)
        if not team_ids:
            return []

        field_all_avg = mean(all_team_avg[team_id] for team_id in team_ids)
        field_recent_avg = mean(recent_team_avg.get(team_id, all_team_avg[team_id]) for team_id in team_ids)
        recent_count = len(recent_result_rows)
        recent_weight = min(0.45, 0.15 + 0.10 * recent_count) if recent_count >= 2 else 0.0
        finish_value_by_team = self._team_strength_finish_moderators(
            season,
            all_result_rows,
            recent_result_rows,
            driver_lookup,
            team_ids,
            recent_weight,
        )
        confidence = min(0.62, 0.34 + 0.035 * len(all_result_rows))
        source = (
            f"fastf1_team_strength_reestimate:{season.season}:"
            f"{self._source_span([normalize_event_name(result.event_name) for _, result, _ in all_result_rows])}:"
            f"{len(all_result_rows)}_races_recent_{recent_count}"
        )
        adjustments: list[FeatureAdjustment] = []
        for team_id in team_ids:
            season_delta = all_team_avg[team_id] - field_all_avg
            recent_delta = recent_team_avg.get(team_id, all_team_avg[team_id]) - field_recent_avg
            blended_delta = (1.0 - recent_weight) * season_delta + recent_weight * recent_delta
            points_value = self._clamp(blended_delta / 35.0 * 0.22, -0.16, 0.16)
            finish_value = finish_value_by_team.get(team_id)
            value = round(self._points_censoring_adjusted_value(points_value, finish_value), 4)
            if not value:
                continue
            moderation_note = ""
            if finish_value is not None and value > round(points_value, 4):
                moderation_note = (
                    " Because points are top-ten-censored, the negative points signal was moderated by "
                    f"the same FastF1 full-field finish classification signal ({finish_value:+.4f})."
                )
            adjustments.append(
                FeatureAdjustment(
                    feature_id=(
                        f"fastf1-team-strength-reestimate:{season.season}:{event.event_id}:"
                        f"{team_id}:race_pace:{len(all_result_rows)}"
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
                        f"Cutoff-valid FastF1 race results before {event.name}: team total points per race "
                        f"{all_team_avg[team_id]:.2f} vs field {field_all_avg:.2f}; recent window "
                        f"{recent_team_avg.get(team_id, all_team_avg[team_id]):.2f} vs field {field_recent_avg:.2f}. "
                        "Used as a bounded team/car strength reestimate so current-season results can move the "
                        "race-pace prior without hand-writing a team order."
                        f"{moderation_note}"
                    ),
                )
            )
        return adjustments

    def _team_strength_finish_moderators(
        self,
        season: SeasonState,
        all_result_rows: list[tuple[str, NormalizedRaceResult, str]],
        recent_result_rows: list[tuple[str, NormalizedRaceResult, str]],
        driver_lookup: dict[str, str],
        team_ids: list[str],
        recent_weight: float,
    ) -> dict[str, float]:
        all_team_finishes = self._team_event_average_finishes(season, all_result_rows, driver_lookup)
        recent_team_finishes = self._team_event_average_finishes(season, recent_result_rows, driver_lookup)
        teams_with_finishes = [team_id for team_id in team_ids if all_team_finishes.get(team_id)]
        if not teams_with_finishes:
            return {}

        field_all_finish = mean(mean(all_team_finishes[team_id]) for team_id in teams_with_finishes)
        field_recent_finish = mean(
            mean(recent_team_finishes.get(team_id, all_team_finishes[team_id]))
            for team_id in teams_with_finishes
        )
        output: dict[str, float] = {}
        for team_id in teams_with_finishes:
            all_avg_finish = mean(all_team_finishes[team_id])
            recent_avg_finish = mean(recent_team_finishes.get(team_id, all_team_finishes[team_id]))
            season_delta = field_all_finish - all_avg_finish
            recent_delta = field_recent_finish - recent_avg_finish
            blended_delta = (1.0 - recent_weight) * season_delta + recent_weight * recent_delta
            output[team_id] = self._clamp(blended_delta / 8.0 * 0.10, -0.10, 0.10)
        return output

    @staticmethod
    def _points_censoring_adjusted_value(points_value: float, finish_value: float | None) -> float:
        if finish_value is None or points_value >= 0.0 or finish_value <= points_value:
            return points_value
        return points_value * 0.58 + finish_value * 0.42

    def _team_event_point_totals(
        self,
        season: SeasonState,
        result_rows: list[tuple[str, NormalizedRaceResult, str]],
        driver_lookup: dict[str, str],
    ) -> defaultdict[str, list[float]]:
        totals: defaultdict[str, list[float]] = defaultdict(list)
        for _, result, _ in result_rows:
            event_totals: defaultdict[str, float] = defaultdict(float)
            for row in result.classified:
                driver_id = self._result_driver_id(row, driver_lookup)
                if driver_id is None or driver_id not in season.drivers:
                    continue
                team_id = season.drivers[driver_id].team_id
                event_totals[team_id] += float(row.get("points") or 0.0)
            for team_id in season.teams:
                totals[team_id].append(event_totals.get(team_id, 0.0))
        return totals

    def _fastf1_team_finish_position_adjustments(
        self,
        season: SeasonState,
        event: RaceEvent,
        all_result_rows: list[tuple[str, NormalizedRaceResult, str]],
        recent_result_rows: list[tuple[str, NormalizedRaceResult, str]],
        driver_lookup: dict[str, str],
        observed_at: str,
    ) -> list[FeatureAdjustment]:
        if len(all_result_rows) < 2:
            return []
        all_team_finishes = self._team_event_average_finishes(season, all_result_rows, driver_lookup)
        recent_team_finishes = self._team_event_average_finishes(season, recent_result_rows, driver_lookup)
        team_ids = sorted(team_id for team_id, finishes in all_team_finishes.items() if finishes and team_id in season.teams)
        if not team_ids:
            return []

        field_all_finish = mean(mean(all_team_finishes[team_id]) for team_id in team_ids)
        field_recent_finish = mean(
            mean(recent_team_finishes.get(team_id, all_team_finishes[team_id]))
            for team_id in team_ids
        )
        recent_count = len(recent_result_rows)
        recent_weight = min(0.48, 0.18 + 0.10 * recent_count) if recent_count >= 2 else 0.0
        confidence = min(0.58, 0.30 + 0.03 * len(all_result_rows))
        source = (
            f"fastf1_finish_position_reestimate:{season.season}:"
            f"{self._source_span([normalize_event_name(result.event_name) for _, result, _ in all_result_rows])}:"
            f"{len(all_result_rows)}_races_recent_{recent_count}"
        )
        adjustments: list[FeatureAdjustment] = []
        for team_id in team_ids:
            all_avg_finish = mean(all_team_finishes[team_id])
            recent_avg_finish = mean(recent_team_finishes.get(team_id, all_team_finishes[team_id]))
            season_delta = field_all_finish - all_avg_finish
            recent_delta = field_recent_finish - recent_avg_finish
            blended_delta = (1.0 - recent_weight) * season_delta + recent_weight * recent_delta
            value = round(self._clamp(blended_delta / 8.0 * 0.10, -0.10, 0.10), 4)
            if not value:
                continue
            adjustments.append(
                FeatureAdjustment(
                    feature_id=(
                        f"fastf1-finish-position-reestimate:{season.season}:{event.event_id}:"
                        f"{team_id}:race_pace:{len(all_result_rows)}"
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
                        f"Cutoff-valid FastF1 full-field race classifications before {event.name}: "
                        f"team average finish {all_avg_finish:.2f} vs field {field_all_finish:.2f}; "
                        f"recent window {recent_avg_finish:.2f} vs field {field_recent_finish:.2f}. "
                        "Used as a bounded car race-pace reestimate so midfield/backfield ordering is not inferred "
                        "from points alone."
                    ),
                )
            )
        return adjustments

    def _team_event_average_finishes(
        self,
        season: SeasonState,
        result_rows: list[tuple[str, NormalizedRaceResult, str]],
        driver_lookup: dict[str, str],
    ) -> defaultdict[str, list[float]]:
        finishes: defaultdict[str, list[float]] = defaultdict(list)
        for _, result, _ in result_rows:
            event_finishes: defaultdict[str, list[int]] = defaultdict(list)
            for row in result.classified:
                driver_id = self._result_driver_id(row, driver_lookup)
                if driver_id is None or driver_id not in season.drivers:
                    continue
                try:
                    position = int(row.get("position") or 0)
                except (TypeError, ValueError):
                    position = 0
                if position <= 0:
                    continue
                team_id = season.drivers[driver_id].team_id
                event_finishes[team_id].append(position)
            for team_id, positions in event_finishes.items():
                if positions:
                    finishes[team_id].append(mean(positions))
        return finishes

    def _collect_fastf1_form_inputs(
        self,
        season: SeasonState,
        result_rows: list[tuple[str, NormalizedRaceResult, str]],
        driver_lookup: dict[str, str],
    ) -> tuple[defaultdict[str, list[dict[str, Any]]], defaultdict[str, list[float]], list[str]]:
        driver_results: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        team_points: defaultdict[str, list[float]] = defaultdict(list)
        source_parts: list[str] = []
        for _, result, _ in result_rows:
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
        return driver_results, team_points, source_parts

    @staticmethod
    def _average_metric(
        rows_by_id: defaultdict[str, list[dict[str, Any]]],
        metric: str,
    ) -> dict[str, float]:
        return {
            item_id: mean([float(row.get(metric) or 0.0) for row in rows])
            for item_id, rows in rows_by_id.items()
            if rows
        }

    @staticmethod
    def _average_positive_metric(
        rows_by_id: defaultdict[str, list[dict[str, Any]]],
        metric: str,
    ) -> dict[str, float]:
        output: dict[str, float] = {}
        for item_id, rows in rows_by_id.items():
            values = [float(row.get(metric) or 0.0) for row in rows if float(row.get(metric) or 0.0) > 0]
            if values:
                output[item_id] = mean(values)
        return output

    @classmethod
    def _average_grid_conversion(
        cls,
        rows_by_id: defaultdict[str, list[dict[str, Any]]],
    ) -> dict[str, float]:
        output: dict[str, float] = {}
        for item_id, rows in rows_by_id.items():
            values = []
            for row in rows:
                grid_position = float(row.get("grid_position") or 0.0)
                finish_position = float(row.get("position") or 0.0)
                status = str(row.get("status") or "")
                if grid_position <= 0 or finish_position <= 0:
                    continue
                if not cls._finished_status(status):
                    continue
                values.append(cls._normalized_grid_conversion(grid_position, finish_position))
            if values:
                output[item_id] = mean(values)
        return output

    @classmethod
    def _team_average_grid_conversion(
        cls,
        season: SeasonState,
        driver_results: defaultdict[str, list[dict[str, Any]]],
    ) -> dict[str, float]:
        values_by_team: defaultdict[str, list[float]] = defaultdict(list)
        for driver_id, rows in driver_results.items():
            driver = season.drivers.get(driver_id)
            if driver is None:
                continue
            for row in rows:
                grid_position = float(row.get("grid_position") or 0.0)
                finish_position = float(row.get("position") or 0.0)
                status = str(row.get("status") or "")
                if grid_position <= 0 or finish_position <= 0:
                    continue
                if not cls._finished_status(status):
                    continue
                values_by_team[driver.team_id].append(cls._normalized_grid_conversion(grid_position, finish_position))
        return {
            team_id: mean(values)
            for team_id, values in values_by_team.items()
            if values
        }

    @staticmethod
    def _normalized_grid_conversion(grid_position: float, finish_position: float) -> float:
        delta = grid_position - finish_position
        if delta > 0:
            return delta / max(grid_position - 1.0, 1.0)
        if delta < 0:
            return delta / max(22.0 - grid_position, 1.0)
        return 0.0

    @staticmethod
    def _source_span(source_parts: list[str]) -> str:
        unique = list(dict.fromkeys(source_parts))
        if not unique:
            return "none"
        if len(unique) <= 3:
            return "+".join(unique)
        return f"{unique[0]}+...+{unique[-1]}"

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

    @staticmethod
    def _session_observed_at(result: NormalizedRaceResult) -> str:
        if result.session_date:
            return result.session_date
        return result.captured_at
