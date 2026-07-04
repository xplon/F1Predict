"""End-to-end prediction orchestration."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Protocol

from f1predict.data_sources.augmented import CalendarAugmentedDataSource
from f1predict.domain import DriverRaceProbability, EvidenceClaim, EvidenceImpact, EvidenceQuality
from f1predict.domain import PredictionReport, RaceEvent, SeasonState, parse_dt, race_event_to_dict, utc_now
from f1predict.features.provider import ProcessedFeatureProvider
from f1predict.intelligence.codex import CodexEvidenceProvider
from f1predict.intelligence.evidence_quality import EvidenceQualityScorer
from f1predict.intelligence.factor_trace import FactorTraceBuilder
from f1predict.market import MarketAnalyzer, event_market_snapshots
from f1predict.market_outcomes import CONSTRUCTOR_DOUBLE_PODIUM, DRIVER_H2H, WINNER
from f1predict.models.pace import PaceModel
from f1predict.models.season import SeasonForecastReport, SeasonForecastSimulator
from f1predict.models.simulator import SimulatorConfig, SingleRaceSimulator
from f1predict.models.simulator import POINTS
from f1predict.official_standings import OfficialStandingsRepository
from f1predict.results import FastF1ResultRepository, normalize_event_name
from f1predict.weather_profiles import WeatherForecastProvider


class SeasonDataSource(Protocol):
    def load(self) -> SeasonState: ...


class PredictionPipeline:
    def __init__(
        self,
        data_source: SeasonDataSource | None = None,
        evidence_provider: CodexEvidenceProvider | None = None,
        feature_provider: ProcessedFeatureProvider | None = None,
        result_repository: FastF1ResultRepository | None = None,
        official_standings_repository: OfficialStandingsRepository | None = None,
        evidence_quality_scorer: EvidenceQualityScorer | None = None,
        factor_trace_builder: FactorTraceBuilder | None = None,
        weather_forecast_provider: WeatherForecastProvider | None = None,
        iterations: int = 5000,
        simulator_config: SimulatorConfig | None = None,
    ) -> None:
        self.data_source = data_source or CalendarAugmentedDataSource()
        self.evidence_provider = evidence_provider or CodexEvidenceProvider()
        self.feature_provider = feature_provider or ProcessedFeatureProvider()
        self.result_repository = result_repository or FastF1ResultRepository()
        self.official_standings_repository = official_standings_repository or OfficialStandingsRepository()
        self.evidence_quality_scorer = evidence_quality_scorer or EvidenceQualityScorer()
        self.factor_trace_builder = factor_trace_builder or FactorTraceBuilder()
        self.weather_forecast_provider = weather_forecast_provider or WeatherForecastProvider()
        self.iterations = iterations
        self.simulator_config = simulator_config or SimulatorConfig()

    def list_events(self) -> list[dict[str, object]]:
        season = self.data_source.load()
        return [race_event_to_dict(event) for event in season.events]

    def predict_event(
        self,
        event_id: str,
        knowledge_cutoff: str | None = None,
    ) -> PredictionReport:
        season = self.data_source.load()
        event = next((item for item in season.events if item.event_id == event_id), None)
        if event is None:
            raise ValueError(f"Unknown event_id: {event_id}")

        cutoff_dt = self._normalize_cutoff(parse_dt(knowledge_cutoff))
        event = self._event_with_cutoff_weather_forecast(event, cutoff_dt)
        evidence = self.evidence_provider.load_event_evidence(event_id, cutoff_dt)
        feature_adjustments = self.feature_provider.load_event_features(season, event, cutoff_dt)
        pre_model_quality = self.evidence_quality_scorer.score_event(event_id, evidence, [], cutoff_dt)
        evidence_input_weights = self._evidence_input_weights(pre_model_quality)
        pace_model = PaceModel(season, evidence, feature_adjustments, evidence_weights=evidence_input_weights)
        simulator = SingleRaceSimulator(
            season,
            pace_model,
            iterations=self.iterations,
            config=self.simulator_config,
        )
        simulation_summary = simulator.simulate_summary(event)
        probabilities = simulation_summary.race_probabilities
        representative_lap = simulation_summary.representative_lap
        simulation_replay = representative_lap
        evidence_impact = self._evidence_impact(
            season,
            event,
            evidence,
            feature_adjustments,
            probabilities,
            evidence_input_weights,
        )
        evidence_quality = self.evidence_quality_scorer.score_event(
            event_id,
            evidence,
            evidence_impact,
            cutoff_dt,
        )
        factor_trace = self.factor_trace_builder.build(
            season,
            event,
            evidence,
            evidence_impact,
            evidence_quality,
        )

        market_edges = []
        market_analyzer = MarketAnalyzer()
        available_winner_markets = event_market_snapshots(
            season.markets,
            event.event_id,
            cutoff_dt,
            market_type=WINNER,
        )
        for market in available_winner_markets:
            market_edges.extend(market_analyzer.compare_winner_market(market, probabilities))
        available_constructor_double_podium_markets = event_market_snapshots(
            season.markets,
            event.event_id,
            cutoff_dt,
            market_type=CONSTRUCTOR_DOUBLE_PODIUM,
        )
        for market in available_constructor_double_podium_markets:
            market_edges.extend(
                market_analyzer.compare_probability_market(
                    market,
                    simulation_summary.team_double_podium_probabilities,
                )
            )
        available_driver_h2h_markets = event_market_snapshots(
            season.markets,
            event.event_id,
            cutoff_dt,
            market_type=DRIVER_H2H,
        )
        for market in available_driver_h2h_markets:
            market_edges.extend(
                market_analyzer.compare_probability_market(
                    market,
                    simulation_summary.driver_h2h_probabilities,
                )
            )

        return PredictionReport(
            event=event,
            generated_at=utc_now().isoformat(),
            knowledge_cutoff=knowledge_cutoff,
            iterations=self.iterations,
            race_probabilities=probabilities,
            market_edges=market_edges,
            evidence=evidence,
            evidence_quality=evidence_quality,
            evidence_impact=evidence_impact,
            feature_adjustments=feature_adjustments,
            representative_lap=representative_lap,
            simulation_replay=simulation_replay,
            ai_judgement=self._ai_judgement(
                evidence,
                evidence_quality,
                evidence_impact,
                factor_trace,
                feature_adjustments,
                market_edges,
                cutoff_dt,
                market_snapshot_count=(
                    len(available_winner_markets)
                    + len(available_constructor_double_podium_markets)
                    + len(available_driver_h2h_markets)
                ),
                market_snapshot_counts={
                    WINNER: len(available_winner_markets),
                    CONSTRUCTOR_DOUBLE_PODIUM: len(available_constructor_double_podium_markets),
                    DRIVER_H2H: len(available_driver_h2h_markets),
                },
            ),
            factor_trace=factor_trace,
        )

    def _event_with_cutoff_weather_forecast(
        self,
        event: RaceEvent,
        cutoff_dt: datetime | None,
    ) -> RaceEvent:
        forecast = self.weather_forecast_provider.load_for_event(event, cutoff_dt)
        if forecast is None:
            return event
        provenance = forecast.provenance(event.track_type)
        feature_refs = dict(event.feature_refs)
        feature_refs["weather_forecast"] = provenance
        event_input_provenance = feature_refs.get("event_input_provenance")
        if isinstance(event_input_provenance, dict):
            updated_provenance = dict(event_input_provenance)
            updated_provenance["weather_prior"] = provenance
            feature_refs["event_input_provenance"] = updated_provenance
        return replace(
            event,
            weather_prior=forecast.weather_prior(event.track_type),
            feature_refs=feature_refs,
        )

    def forecast_season(
        self,
        knowledge_cutoff: str | None = None,
        iterations: int | None = None,
    ) -> SeasonForecastReport:
        season = self.data_source.load()
        cutoff_dt = self._normalize_cutoff(parse_dt(knowledge_cutoff)) or utc_now().replace(microsecond=0)
        cutoff_text = knowledge_cutoff or cutoff_dt.isoformat()
        (
            base_points,
            completed_events_counted,
            base_point_sources,
            standings_warnings,
        ) = self._base_points_for_season_forecast(
            season,
            cutoff_dt,
            self.result_repository.latest_results_by_event(season.season),
        )
        remaining_events = self._remaining_events_for_forecast(season, cutoff_dt)
        pace_models = {}
        missing_evidence = 0
        missing_features = 0
        for event in remaining_events:
            evidence = self.evidence_provider.load_event_evidence(event.event_id, cutoff_dt)
            features = self.feature_provider.load_event_features(season, event, cutoff_dt)
            if not evidence:
                missing_evidence += 1
            if not features:
                missing_features += 1
            pre_model_quality = self.evidence_quality_scorer.score_event(event.event_id, evidence, [], cutoff_dt)
            pace_models[event.event_id] = PaceModel(
                season,
                evidence,
                features,
                evidence_weights=self._evidence_input_weights(pre_model_quality),
            )

        forecast_iterations = iterations or max(600, min(self.iterations, 2500))
        rows = SeasonForecastSimulator(
            season,
            pace_models=pace_models,
            iterations=forecast_iterations,
            simulator_config=self.simulator_config,
        ).forecast(base_points, remaining_events)
        warnings = self._season_forecast_warnings(
            missing_evidence=missing_evidence,
            missing_features=missing_features,
            remaining_events=len(remaining_events),
            completed_events_counted=completed_events_counted,
            base_point_sources=base_point_sources,
            standings_warnings=standings_warnings,
        )
        return SeasonForecastReport(
            generated_at=utc_now().isoformat(),
            knowledge_cutoff=cutoff_text,
            iterations=forecast_iterations,
            status="diagnostic_only",
            formal_ready=False,
            completed_events_counted=completed_events_counted,
            remaining_events_simulated=len(remaining_events),
            event_sampling_model="strategy_aware_race_time_sampler",
            base_points_source=self._base_points_source_label(base_point_sources),
            base_points_event_sources=base_point_sources,
            warnings=warnings,
            rows=rows,
        )

    @staticmethod
    def _ai_judgement(
        evidence,
        evidence_quality: list[EvidenceQuality],
        evidence_impact,
        factor_trace,
        feature_adjustments,
        market_edges,
        cutoff_dt: datetime | None,
        market_snapshot_count: int,
        market_snapshot_counts: dict[str, int] | None = None,
    ) -> dict[str, object]:
        reviewed = sum(1 for item in evidence if item.review_required)
        weak_quality = [
            item for item in evidence_quality
            if item.quality_status in {"weak_diagnostic", "review_required"}
        ]
        strong_quality = [item for item in evidence_quality if item.quality_status == "strong"]
        source_flags = sorted({flag for row in evidence_quality for flag in row.risk_flags})
        triangulation_counts: dict[str, int] = {}
        conflict_counts: dict[str, int] = {}
        for row in evidence_quality:
            triangulation_counts[row.triangulation_status] = triangulation_counts.get(row.triangulation_status, 0) + 1
            conflict_counts[row.conflict_status] = conflict_counts.get(row.conflict_status, 0) + 1
        weak_triangulation = sum(
            count for status, count in triangulation_counts.items()
            if status in {"single_source", "same_source_repetition", "seed_or_test_only", "unlinked_source"}
        )
        model_input_weights = [row.model_input_weight for row in evidence_quality]
        positive_edges = [
            item for item in market_edges
            if (item.conservative_edge_after_cost if item.conservative_edge_after_cost is not None else item.edge_after_cost) > 0.0
        ]
        downgraded_edges = [
            item for item in market_edges
            if "recommendation_downgraded_by_calibration" in item.risk_flags
        ]
        risk_notes = []
        if reviewed:
            risk_notes.append(f"{reviewed} evidence claims require review before real trading.")
        if weak_quality:
            risk_notes.append(f"{len(weak_quality)} Codex evidence quality rows are weak or review-required.")
        if strong_quality:
            risk_notes.append(f"{len(strong_quality)} Codex evidence rows have strong source-aware quality scores.")
        if source_flags:
            risk_notes.append(f"Evidence quality flags: {', '.join(source_flags[:5])}.")
        if weak_triangulation:
            risk_notes.append(f"{weak_triangulation} Codex evidence rows rely on single-source or seed-only support.")
        conflicted = len(evidence_quality) - conflict_counts.get("no_conflict", 0)
        if conflicted:
            risk_notes.append(f"{conflicted} Codex evidence rows have opposing normalized claim directions.")
        if model_input_weights:
            risk_notes.append(
                "Codex evidence entered the simulator with source-quality weights "
                f"ranging {min(model_input_weights):.2f}-{max(model_input_weights):.2f}."
            )
        if not evidence:
            risk_notes.append("No Codex evidence available for this event; prediction is structure-only.")
        if feature_adjustments:
            risk_notes.append(f"{len(feature_adjustments)} processed data features entered the pace model.")
        if market_snapshot_count == 0:
            risk_notes.append("No market snapshot available at the prediction cutoff; market edge comparison is disabled.")
        if market_snapshot_count > 0:
            risk_notes.append("Market recommendations use conservative probability shrinkage for calibration risk.")
            if market_snapshot_counts:
                active_market_types = ", ".join(
                    f"{key}: {value}"
                    for key, value in sorted(market_snapshot_counts.items())
                    if value
                )
                if active_market_types:
                    risk_notes.append(f"Market snapshot types available at cutoff: {active_market_types}.")
        if downgraded_edges:
            risk_notes.append(f"{len(downgraded_edges)} raw market gaps were downgraded by calibration risk.")
        if cutoff_dt is not None:
            risk_notes.append("Knowledge cutoff enforced for replay.")
        if evidence_impact:
            largest = max(evidence_impact, key=lambda row: abs(row.max_win_probability_delta))
            risk_notes.append(
                "Largest Codex sensitivity: "
                f"{largest.claim_id} moved target-scope win probability by "
                f"{largest.max_win_probability_delta:+.3f}."
            )
        factor_route_counts: dict[str, int] = {}
        for row in factor_trace:
            factor_route_counts[row.route] = factor_route_counts.get(row.route, 0) + 1
        if factor_trace:
            routed = sum(1 for row in factor_trace if row.route_status != "unsupported_metric")
            observed = sum(1 for row in factor_trace if row.route_status == "observed_probability_movement")
            risk_notes.append(
                f"{routed} normalized factors were routed into simulator surfaces; "
                f"{observed} showed same-seed probability movement."
            )
        risk_notes.append(
            "Strategy-aware race-time simulation includes tyre degradation, pit-loss, weather, safety-car, and reliability proxies."
        )
        return {
            "summary": "Codex evidence was normalized before entering the strategy-aware simulator.",
            "evidence_count": len(evidence),
            "evidence_quality_count": len(evidence_quality),
            "strong_evidence_quality_count": len(strong_quality),
            "weak_evidence_quality_count": len(weak_quality),
            "triangulation_status_counts": dict(sorted(triangulation_counts.items())),
            "conflict_status_counts": dict(sorted(conflict_counts.items())),
            "conflicting_evidence_count": conflicted,
            "average_model_input_weight": round(sum(model_input_weights) / len(model_input_weights), 4)
            if model_input_weights
            else None,
            "min_model_input_weight": min(model_input_weights) if model_input_weights else None,
            "max_model_input_weight": max(model_input_weights) if model_input_weights else None,
            "weak_triangulation_count": weak_triangulation,
            "evidence_impact_count": len(evidence_impact),
            "factor_trace_count": len(factor_trace),
            "factor_route_counts": dict(sorted(factor_route_counts.items())),
            "feature_adjustment_count": len(feature_adjustments),
            "market_snapshot_count": market_snapshot_count,
            "market_snapshot_counts": market_snapshot_counts or {},
            "review_required_count": reviewed,
            "positive_edge_count": len(positive_edges),
            "risk_notes": risk_notes,
        }

    def _evidence_impact(
        self,
        season: SeasonState,
        event: RaceEvent,
        evidence: list[EvidenceClaim],
        feature_adjustments,
        probabilities: list[DriverRaceProbability],
        evidence_input_weights: dict[str, float] | None = None,
    ) -> list[EvidenceImpact]:
        if not evidence:
            return []

        full_by_driver = {row.driver_id: row for row in probabilities}

        rows = []
        for claim in evidence:
            counterfactual_evidence = [row for row in evidence if row.claim_id != claim.claim_id]
            counterfactual_weights = {
                claim_id: weight
                for claim_id, weight in (evidence_input_weights or {}).items()
                if claim_id != claim.claim_id
            }
            counterfactual_pace = PaceModel(
                season,
                counterfactual_evidence,
                feature_adjustments,
                evidence_weights=counterfactual_weights,
            )
            counterfactual_probabilities, _ = SingleRaceSimulator(
                season,
                counterfactual_pace,
                iterations=self.iterations,
                config=self.simulator_config,
            ).simulate(event)
            counterfactual_by_driver = {row.driver_id: row for row in counterfactual_probabilities}
            affected = self._affected_driver_ids(season, event, claim)
            outcome_rows = []
            for driver_id in affected:
                full = full_by_driver.get(driver_id)
                counterfactual = counterfactual_by_driver.get(driver_id)
                if full is None or counterfactual is None:
                    continue
                outcome_rows.append(
                    {
                        "driver_id": driver_id,
                        "win_delta": round(full.win - counterfactual.win, 4),
                        "podium_delta": round(full.podium - counterfactual.podium, 4),
                        "expected_points_delta": round(full.expected_points - counterfactual.expected_points, 3),
                    }
                )

            outcome_rows.sort(key=lambda row: abs(float(row["win_delta"])), reverse=True)
            if claim.target_type == "event":
                outcome_rows = outcome_rows[:5]
            max_delta = max((abs(float(row["win_delta"])) for row in outcome_rows), default=0.0)
            signed_max_delta = self._signed_max_delta(outcome_rows)
            rows.append(
                EvidenceImpact(
                    claim_id=claim.claim_id,
                    source=claim.source,
                    target_type=claim.target_type,
                    target_id=claim.target_id,
                    metric=claim.metric,
                    direction=claim.direction,
                    signed_input_impact=round(
                        claim.signed_impact() * (evidence_input_weights or {}).get(claim.claim_id, 1.0),
                        4,
                    ),
                    confidence=claim.confidence,
                    uncertainty=claim.uncertainty,
                    attribution_method="diagnostic_same_seed_leave_one_claim_comparison",
                    affected_outcomes=outcome_rows,
                    max_win_probability_delta=round(signed_max_delta if signed_max_delta else max_delta, 4),
                    interpretation=self._impact_interpretation(claim, outcome_rows),
                )
            )
        return sorted(rows, key=lambda row: abs(row.max_win_probability_delta), reverse=True)

    @staticmethod
    def _evidence_input_weights(evidence_quality: list[EvidenceQuality]) -> dict[str, float]:
        return {row.claim_id: row.model_input_weight for row in evidence_quality}

    @staticmethod
    def _affected_driver_ids(
        season: SeasonState,
        event: RaceEvent,
        claim: EvidenceClaim,
    ) -> list[str]:
        if claim.target_type == "driver":
            return [claim.target_id] if claim.target_id in season.drivers else []
        if claim.target_type == "team":
            return [
                driver.driver_id
                for driver in season.drivers.values()
                if driver.team_id == claim.target_id
            ]
        if claim.target_type == "event" and claim.target_id == event.event_id:
            return list(season.drivers)
        return []

    @staticmethod
    def _signed_max_delta(outcome_rows: list[dict[str, object]]) -> float:
        if not outcome_rows:
            return 0.0
        row = max(outcome_rows, key=lambda item: abs(float(item["win_delta"])))
        return float(row["win_delta"])

    @staticmethod
    def _impact_interpretation(
        claim: EvidenceClaim,
        outcome_rows: list[dict[str, object]],
    ) -> str:
        if not outcome_rows:
            return "Claim is normalized but does not currently feed the race probability model."
        max_delta = max(abs(float(row["win_delta"])) for row in outcome_rows)
        if max_delta >= 0.03:
            tone = "material"
        elif max_delta >= 0.01:
            tone = "moderate"
        else:
            tone = "small"
        return (
            f"{tone} diagnostic sensitivity for {claim.metric}; "
            "computed by comparing the full prediction with a same-seed run that removes this claim only."
        )

    @staticmethod
    def _completed_events_before_cutoff(season: SeasonState, cutoff_dt: datetime) -> int:
        completed_events = 0
        for event in season.events:
            event_dt = parse_dt(f"{event.date}T00:00:00+00:00")
            if event_dt is None or event_dt.date() >= cutoff_dt.date():
                continue
            if event.completed and event.actual_result:
                completed_events += 1
        return completed_events

    def _base_points_for_season_forecast(
        self,
        season: SeasonState,
        cutoff_dt: datetime,
        fastf1_results: dict[str, object],
    ) -> tuple[dict[str, float], int, dict[str, int], tuple[str, ...]]:
        standings_warnings: list[str] = []
        try:
            official = self.official_standings_repository.build(
                season.season,
                season=season,
                knowledge_cutoff=cutoff_dt,
            )
        except ValueError as exc:
            official = None
            standings_warnings.append(f"official_standings_unavailable_before_cutoff:{exc}")

        if official is not None:
            standings_warnings.extend(f"official_standings_{warning}" for warning in official.warnings)
            if official.can_seed_season_points:
                return (
                    official.matched_points(),
                    self._completed_events_before_cutoff(season, cutoff_dt),
                    {"f1_official_driver_standings": 1, "fastf1_points": 0, "classified_order_fallback": 0},
                    tuple(standings_warnings),
                )

        points, completed_events, source_counts = self._base_points_from_completed_results(
            season,
            cutoff_dt,
            fastf1_results,
        )
        return points, completed_events, source_counts, tuple(standings_warnings)

    @staticmethod
    def _base_points_from_completed_results(
        season: SeasonState,
        cutoff_dt: datetime,
        fastf1_results: dict[str, object],
    ) -> tuple[dict[str, float], int, dict[str, int]]:
        points = {driver_id: 0.0 for driver_id in season.drivers}
        completed_events = 0
        source_counts = {
            "fastf1_points": 0,
            "classified_order_fallback": 0,
        }
        driver_lookup = PredictionPipeline._driver_lookup(season)
        for event in season.events:
            event_dt = parse_dt(f"{event.date}T00:00:00+00:00")
            if event_dt is None or event_dt.date() >= cutoff_dt.date():
                continue
            if not event.completed or not event.actual_result:
                continue
            completed_events += 1
            result = fastf1_results.get(normalize_event_name(event.name))
            if result is not None and PredictionPipeline._add_fastf1_result_points(points, driver_lookup, result):
                source_counts["fastf1_points"] += 1
                continue
            source_counts["classified_order_fallback"] += 1
            PredictionPipeline._add_classified_order_points(points, event)
        return points, completed_events, source_counts

    @staticmethod
    def _normalize_cutoff(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _remaining_events_for_forecast(
        season: SeasonState,
        cutoff_dt: datetime,
    ) -> list:
        remaining = []
        for event in season.events:
            event_dt = parse_dt(f"{event.date}T00:00:00+00:00")
            counted_as_actual = (
                event_dt is not None
                and event_dt.date() < cutoff_dt.date()
                and event.completed
                and bool(event.actual_result)
            )
            if not counted_as_actual:
                remaining.append(event)
        return remaining

    @staticmethod
    def _season_forecast_warnings(
        missing_evidence: int,
        missing_features: int,
        remaining_events: int,
        completed_events_counted: int,
        base_point_sources: dict[str, int],
        standings_warnings: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        warnings = [
            "diagnostic_strategy_aware_season_model",
            "strategy_aware_event_sampling_for_remaining_events",
            "season_points_do_not_include_missing_sprint_sessions_unless_present_in_fastf1_points",
        ]
        if base_point_sources.get("classified_order_fallback", 0):
            warnings.append(
                f"classified_order_points_fallback_for_{base_point_sources['classified_order_fallback']}_events"
            )
        if completed_events_counted == 0:
            warnings.append("no_completed_results_counted_before_cutoff")
        if missing_evidence:
            warnings.append(f"missing_event_evidence_for_{missing_evidence}_simulated_events")
        if missing_features:
            warnings.append(f"missing_processed_features_for_{missing_features}_simulated_events")
        if remaining_events == 0:
            warnings.append("no_remaining_events_to_simulate")
        warnings.extend(standings_warnings)
        return tuple(warnings)

    @staticmethod
    def _base_points_source_label(source_counts: dict[str, int]) -> str:
        if source_counts.get("f1_official_driver_standings", 0):
            return "f1_official_driver_standings_before_cutoff"
        if source_counts.get("classified_order_fallback", 0):
            return "fastf1_points_with_classified_order_fallback"
        if source_counts.get("fastf1_points", 0):
            return "fastf1_result_points_before_cutoff"
        return "classified_results_before_cutoff"

    @staticmethod
    def _add_fastf1_result_points(
        points: dict[str, float],
        driver_lookup: dict[str, str],
        result: object,
    ) -> bool:
        used = False
        classified = getattr(result, "classified", [])
        for row in classified:
            if not isinstance(row, dict):
                continue
            value = row.get("points")
            if value is None:
                continue
            driver_id = PredictionPipeline._result_driver_id(row, driver_lookup)
            if driver_id is None or driver_id not in points:
                continue
            points[driver_id] += float(value)
            used = True
        return used

    @staticmethod
    def _add_classified_order_points(points: dict[str, float], event) -> None:
        for position, driver_id in enumerate(event.actual_result[:10]):
            if driver_id in points:
                points[driver_id] += POINTS[position]

    @staticmethod
    def _driver_lookup(season: SeasonState) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for driver in season.drivers.values():
            candidates = [
                driver.driver_id,
                driver.name,
                driver.name.split()[-1] if driver.name.split() else "",
            ]
            for candidate in candidates:
                key = PredictionPipeline._compact(candidate)
                if key:
                    mapping[key] = driver.driver_id
        return mapping

    @staticmethod
    def _result_driver_id(row: dict[str, object], driver_lookup: dict[str, str]) -> str | None:
        candidates = [
            str(row.get("driver_id") or ""),
            str(row.get("full_name") or ""),
            str(row.get("full_name") or "").split()[-1] if str(row.get("full_name") or "").split() else "",
        ]
        for candidate in candidates:
            key = PredictionPipeline._compact(candidate)
            if key in driver_lookup:
                return driver_lookup[key]
        raw_id = str(row.get("driver_id") or "")
        return raw_id or None

    @staticmethod
    def _compact(value: str) -> str:
        return "".join(ch for ch in value.lower() if ch.isalnum())
