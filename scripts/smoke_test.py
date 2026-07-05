"""Repository smoke test for the local project environment."""

from __future__ import annotations

import tempfile
from pathlib import Path
import json

from f1predict.api_v2 import BackendApiV2
from f1predict.backtest import Backtester
from f1predict.calibration import ReplayCalibrationBuilder
from f1predict.chronological_replay import ChronologicalReplayBundleBuilder
from f1predict.data_sources.augmented import CalendarAugmentedDataSource
from f1predict.data_sources.seed_loader import SeedDataSource
from f1predict.domain import EvidenceClaim, MarketSnapshot, parse_dt
from f1predict.event_inputs import audit_event_input
from f1predict.improvement_plan import ImprovementPlanBuilder
from f1predict.ingestion import LiveIngestor
from f1predict.intelligence.codex import CodexEvidenceProvider, EvidencePacketStore
from f1predict.intelligence.evidence_quality import EvidenceQualityScorer
from f1predict.intelligence.evidence_workflow import CodexResearchWorkspaceBuilder, EvidenceCoverageAuditor
from f1predict.intelligence.research_packet import CodexResearchPacketArchiver, CodexResearchPacketPreflight
from f1predict.intelligence.research_plan import CodexResearchPlanBuilder
from f1predict.intelligence.source_candidates import CodexSourceCandidateBuilder
from f1predict.intelligence.source_registry import (
    SourceArchiveBackfiller,
    SourceLogAuditor,
    SourceSnapshotter,
    WaybackAvailabilityClient,
)
from f1predict.market import after_cutoff_market_count, event_market_snapshots
from f1predict.market_outcomes import DRIVER_H2H, driver_h2h_outcome_id
from f1predict.market_sources.polymarket import (
    PolymarketDiscoveryAuditor,
    PolymarketGammaNormalizer,
    PolymarketLiveSnapshotter,
    PolymarketPriceHistoryBackfiller,
    PolymarketSearchHistoryBackfiller,
    PolymarketSeasonSearchAuditor,
)
from f1predict.market_readiness import ReadinessMarketScanner
from f1predict.market_store import MarketSnapshotStore
from f1predict.manifest import ReplayFreezeManifestBuilder
from f1predict.model_error_review import ModelErrorReviewBuilder
from f1predict.mvp_completion_audit import MVPCompletionAuditBuilder
from f1predict.models.pace import PaceModel
from f1predict.models.simulator import SingleRaceSimulator
from f1predict.models.technical_factors import technical_context_multiplier, track_demand_profile
from f1predict.mvp_gate import MVPGateBuilder
from f1predict.official_standings import OfficialStandingsRepository
from f1predict.pipeline import PredictionPipeline
from f1predict.prediction_packet import PredictionPacketBuilder
from f1predict.readiness import FormalReadinessBuilder
from f1predict.readiness_intake import ReadinessIntakeExporter, ReadinessIntakeVerifier
from f1predict.replay_analysis import ReplayAnalysisBuilder
from f1predict.replay_artifacts import as_of_from_replay_stem, latest_replay_as_of, replay_stem, stem_time
from f1predict.reviewed_market import ReviewedMarketSnapshotArchiver, ReviewedMarketSnapshotValidationError
from f1predict.results import FastF1ResultRepository
from f1predict.run_tracking import InformationIntakeStore, MatchedPredictionDiff, PredictionRunRegistry
from f1predict.seed_roster import SeedRosterSyncPlanner
from f1predict.simulator_calibration import SimulatorCalibrationBuilder
from f1predict.source_replacements import (
    SourceReplacementApplier,
    SourceReplacementApplyError,
    SourceReplacementCandidateBuilder,
    SourceReplacementCandidateDefinition,
)
from f1predict.storage import RawSnapshotStore
from f1predict.track_assets import TrackAssetAuditor
from f1predict.weather_profiles import WeatherForecastProvider


def main() -> None:
    import fastf1  # noqa: F401

    pipeline = PredictionPipeline(iterations=400)
    events = pipeline.list_events()
    assert events, "events should load"
    assert any(event["event_id"] == "miami_gp" for event in events), "calendar-augmented events should load"
    british_event_row = next(event for event in events if event["event_id"] == "british_gp")
    british_asset = british_event_row.get("track_map_asset", {})
    assert (
        british_asset.get("source") == "f1_official_circuit_map"
        and "Track%20icons" not in str(british_asset.get("source_url"))
        and (Path("web") / str(british_asset.get("web_path", "")).lstrip("/")).exists()
    ), "event list API payloads should expose real official circuit-map assets at the top level"
    british_overlay = british_asset.get("geometry_overlay", {})
    assert (
        isinstance(british_overlay, dict)
        and british_overlay.get("source") == "auto_fit_official_sector_line_v1"
        and british_overlay.get("transform", {}).get("swap_xy") is True
    ), "British GP replay should expose calibrated official-map overlay geometry"
    as_of_text = "2026-07-01T00:00:00+00:00"
    assert stem_time(as_of_text) == "20260701T000000_0000", "replay artifact time stems should be stable"
    assert (
        replay_stem(2026, as_of_text) == "2026_asof_20260701T000000_0000"
    ), "replay artifact stems should include year and cutoff"
    assert (
        as_of_from_replay_stem("2026_asof_20260701T000000_0000") == as_of_text
    ), "replay artifact stems should round-trip UTC cutoffs"
    with tempfile.TemporaryDirectory() as directory:
        artifact_root = Path(directory)
        (artifact_root / "2026_asof_20260630T000000_0000.analysis.json").write_text("{}", encoding="utf-8")
        (artifact_root / "2026_asof_20260701T000000_0000.analysis.json").write_text("{}", encoding="utf-8")
        assert (
            latest_replay_as_of(artifact_root, 2026, suffix=".analysis.json") == as_of_text
        ), "latest replay artifact discovery should choose the newest cutoff"
    with tempfile.TemporaryDirectory() as directory:
        tracking_root = Path(directory)
        evidence_dir = tracking_root / "seed_evidence"
        evidence_dir.mkdir(parents=True)
        tracking_claim = EvidenceClaim(
            claim_id="tracking-smoke-001",
            event_id="british_gp",
            source="tracking smoke",
            source_url="test://tracking-smoke",
            published_at="2026-06-29T10:00:00+00:00",
            observed_at="2026-06-29T10:05:00+00:00",
            target_type="team",
            target_id="mercedes",
            claim_type="ers",
            metric="energy_recovery",
            direction="positive",
            magnitude=0.05,
            confidence=0.8,
            uncertainty=0.2,
            evidence_text="Smoke evidence for run tracking.",
            reasoning="Verifies raw evidence fingerprints stay stable across probability changes.",
            review_required=False,
        )
        (evidence_dir / "british_gp.jsonl").write_text(
            json.dumps(tracking_claim.__dict__, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        intake_store = InformationIntakeStore(
            root=tracking_root / "intake",
            evidence_provider=CodexEvidenceProvider(
                evidence_dir=evidence_dir,
                packet_root=tracking_root / "packets",
            ),
            research_root=tracking_root / "research",
            reports_root=tracking_root / "reports",
        )
        intake_record, intake_path = intake_store.build_and_write(
            "british_gp",
            knowledge_cutoff="2026-06-30T12:00:00+00:00",
        )
        assert intake_record.claim_count == 1, "information intake should snapshot cutoff-valid claims"
        assert intake_record.metric_counts == {"energy_recovery": 1}
        registry = PredictionRunRegistry(tracking_root / "prediction_runs")

        def tracking_packet(generated_at: str, russell_win: float, antonelli_win: float) -> dict:
            probabilities = [
                {
                    "driver_id": "russell",
                    "win": russell_win,
                    "podium": 0.7,
                    "points": 0.95,
                    "expected_points": 17.0 + russell_win,
                    "average_finish": 2.8 - russell_win,
                },
                {
                    "driver_id": "antonelli",
                    "win": antonelli_win,
                    "podium": 0.65,
                    "points": 0.93,
                    "expected_points": 16.0 + antonelli_win,
                    "average_finish": 3.1 - antonelli_win,
                },
            ]
            return {
                "event_id": "british_gp",
                "event_name": "British Grand Prix",
                "generated_at": generated_at,
                "knowledge_cutoff": "2026-06-30T12:00:00+00:00",
                "iterations": 1000,
                "status": "diagnostic_only",
                "formal_edge_ready": False,
                "blocker_codes": [],
                "warning_codes": [],
                "event_input_audit": {"quality": "smoke", "risk_codes": []},
                "market_context": {"usable_snapshot_count": 0, "market_edge_count": 0},
                "codex_context": {"evidence_count": 1, "factor_trace_count": 0},
                "probability_summary": {"top_win_probabilities": probabilities},
                "top_market_edges": [],
                "prediction": {
                    "event": {"event_id": "british_gp", "name": "British Grand Prix"},
                    "race_probabilities": probabilities,
                    "evidence": [tracking_claim.__dict__],
                    "feature_adjustments": [],
                },
            }

        base_run = registry.register_payload(
            tracking_packet("2026-06-30T12:01:00+00:00", 0.40, 0.30),
            information_intake_path=intake_path,
        )
        candidate_run = registry.register_payload(
            tracking_packet("2026-06-30T12:02:00+00:00", 0.45, 0.25),
            information_intake_path=intake_path,
        )
        diff = MatchedPredictionDiff(registry, tracking_root / "prediction_diffs").build(
            base_run.run_id,
            candidate_run.run_id,
        )
        assert not diff.evidence_changed, "raw evidence fingerprint should stay stable when only probabilities move"
        assert diff.probability_changed, "prediction diff should detect probability movement"
        assert diff.summary["changed_driver_count"] == 2, "prediction diff should count changed driver rows"
    report = pipeline.predict_event("british_gp")
    assert report.race_probabilities, "race probabilities should be produced"
    assert report.representative_lap, "representative lap should be produced"
    assert report.simulation_replay, "selected simulation replay should be produced"
    first_lap = report.representative_lap[0]
    assert {
        "position",
        "gap_to_leader",
        "grid_position",
        "compound",
        "stint",
        "pit_stop",
        "track_status",
        "planned_stops",
        "pit_laps",
    }.issubset(first_lap), "representative lap should expose strategy, tyre, and weather trace fields"
    assert (
        first_lap["planned_stops"] >= 1 and first_lap["pit_laps"]
    ), "strategy-aware simulator should publish a concrete pit plan"
    assert any(
        row["pit_stop"] for row in report.simulation_replay
    ), "simulation replay should include pit-stop laps across the selected drivers"
    season = pipeline.data_source.load()
    british_event = next(event for event in season.events if event.event_id == "british_gp")
    british_event_technical_profile = track_demand_profile(british_event.track_type, british_event.feature_refs)
    static_british_profile = track_demand_profile(british_event.track_type)
    assert any(
        "event_geometry_adjusted=true" in note for note in british_event_technical_profile.notes
    ), "event-aware technical profile should use sourced British GP circuit geometry"
    assert (
        british_event_technical_profile.ers_demand > static_british_profile.ers_demand
    ), "Silverstone geometry should slightly raise ERS demand above the coarse high-speed bucket"
    api_v2 = BackendApiV2(Path.cwd())
    assert "/api/v2/prediction-runs" in api_v2.handle_get("/api/v2/openapi.json", {}).payload[
        "paths"
    ], "API v2 should publish prediction-run endpoint definitions"
    api_health = api_v2.handle_get("/api/v2/health", {}).payload
    assert (
        api_health["driver_count"] == len(season.drivers) == 22
    ), "API v2 health should expose the verified 2026 22-driver roster"
    api_season = api_v2.handle_get("/api/v2/season-state", {}).payload
    assert (
        api_season["team_count"] == len(season.teams) == 11
    ), "API v2 season-state should expose the verified 2026 11-team roster"
    api_intake = api_v2.handle_get(
        "/api/v2/information-intake",
        {
            "event_id": ["british_gp"],
            "knowledge_cutoff": ["2026-06-30T12:00:00+00:00"],
        },
    ).payload
    assert api_intake["claim_count"] >= 1, "API v2 should preview cutoff-valid information intake"
    api_runs = api_v2.handle_get("/api/v2/prediction-runs", {"event_id": ["british_gp"]}).payload
    assert api_runs["run_count"] >= 1, "API v2 should list registered prediction runs"
    high_altitude_refs = {
        "weather_profile": {"elevation_m": 2240.0},
        "circuit_profile": {
            "geometry_metrics": {
                "corner_count": 17,
                "avg_abs_corner_angle": 96.0,
                "total_abs_corner_angle": 1632.0,
                "high_angle_corner_count": 5,
                "low_angle_corner_count": 3,
            }
        },
    }
    assert (
        track_demand_profile("power", high_altitude_refs).altitude_power_derate > 0.0
    ), "event-aware technical profile should expose high-altitude power derate"
    assert (
        technical_context_multiplier("power_unit", "power", feature_refs=high_altitude_refs)
        > technical_context_multiplier("power_unit", "power")
    ), "high-altitude context should increase power-unit evidence sensitivity"
    technical_claims = [
        EvidenceClaim(
            claim_id="smoke-tech-mercedes-ers",
            event_id="british_gp",
            source="smoke technical packet",
            source_url="test://technical/mercedes-ers",
            published_at="2026-06-29T10:00:00+00:00",
            observed_at="2026-06-29T10:05:00+00:00",
            target_type="team",
            target_id="mercedes",
            claim_type="ers",
            metric="energy_recovery",
            direction="positive",
            magnitude=0.10,
            confidence=0.90,
            uncertainty=0.05,
            evidence_text="Smoke source says Mercedes has stronger deployment and less clipping on long straights.",
            reasoning="Energy recovery should matter more on a high-speed Silverstone-style circuit.",
            review_required=True,
        ),
        EvidenceClaim(
            claim_id="smoke-tech-redbull-upgrade",
            event_id="british_gp",
            source="smoke technical packet",
            source_url="test://technical/redbull-upgrade",
            published_at="2026-06-29T11:00:00+00:00",
            observed_at="2026-06-29T11:05:00+00:00",
            target_type="team",
            target_id="red_bull",
            claim_type="upgrade",
            metric="upgrade_effect",
            direction="positive",
            magnitude=0.08,
            confidence=0.82,
            uncertainty=0.12,
            evidence_text="Smoke source says Red Bull's latest package has validated performance gain.",
            reasoning="A validated upgrade should improve both race and qualifying context through upgrade_effect.",
            review_required=True,
        ),
        EvidenceClaim(
            claim_id="smoke-tech-ferrari-straightline",
            event_id="british_gp",
            source="smoke technical packet",
            source_url="test://technical/ferrari-straightline",
            published_at="2026-06-29T12:00:00+00:00",
            observed_at="2026-06-29T12:05:00+00:00",
            target_type="team",
            target_id="ferrari",
            claim_type="power_unit",
            metric="straight_line_speed",
            direction="negative",
            magnitude=0.08,
            confidence=0.80,
            uncertainty=0.10,
            evidence_text="Smoke source says Ferrari is losing on long straights in this configuration.",
            reasoning="Straight-line deficit should be penalized more on high-speed circuits.",
            review_required=True,
        ),
        EvidenceClaim(
            claim_id="smoke-tech-ferrari-launch",
            event_id="british_gp",
            source="smoke technical packet",
            source_url="test://technical/ferrari-launch",
            published_at="2026-06-29T12:30:00+00:00",
            observed_at="2026-06-29T12:35:00+00:00",
            target_type="team",
            target_id="ferrari",
            claim_type="launch",
            metric="launch_performance",
            direction="positive",
            magnitude=0.08,
            confidence=0.78,
            uncertainty=0.12,
            evidence_text="Smoke source says Ferrari has stronger launch response at a low-altitude start.",
            reasoning="Launch response should improve start and first-lap conversion through launch_performance.",
            review_required=True,
        ),
        EvidenceClaim(
            claim_id="smoke-tech-ferrari-tyre-deg",
            event_id="british_gp",
            source="smoke technical packet",
            source_url="test://technical/ferrari-tyre",
            published_at="2026-06-29T13:00:00+00:00",
            observed_at="2026-06-29T13:05:00+00:00",
            target_type="team",
            target_id="ferrari",
            claim_type="tyre_degradation",
            metric="tyre_deg",
            direction="negative",
            magnitude=0.08,
            confidence=0.82,
            uncertainty=0.10,
            evidence_text="Smoke source says Ferrari has elevated tyre degradation risk on high lateral-load tracks.",
            reasoning="Negative tyre_deg should increase simulated degradation rate.",
            review_required=True,
        ),
    ]
    baseline_pace = PaceModel(season, [], [])
    technical_pace = PaceModel(season, technical_claims, [])
    russell = season.drivers["russell"]
    hamilton = season.drivers["hamilton"]
    baseline_russell_score = baseline_pace.score_breakdown(russell, british_event, mode="race")
    technical_russell_score = technical_pace.score_breakdown(russell, british_event, mode="race")
    technical_hamilton_score = technical_pace.score_breakdown(hamilton, british_event, mode="race")
    assert (
        technical_russell_score["evidence_energy_recovery"] > 0
    ), "technical ERS evidence should enter the race score as energy_recovery"
    assert (
        technical_hamilton_score["evidence_straight_line_speed"] < 0
    ), "negative straight-line evidence should penalize high-speed Ferrari race score"
    assert (
        baseline_pace.launch_adjustment(hamilton, british_event) == 0.0
    ), "baseline launch adjustment should be neutral without launch evidence"
    assert (
        technical_pace.launch_adjustment(hamilton, british_event) > 0.0
    ), "positive launch evidence should enter the start/first-lap simulator surface"
    assert (
        SingleRaceSimulator(season, technical_pace, iterations=80)._launch_time_bonus(british_event, hamilton, 4) > 0.0
    ), "positive launch evidence should reduce sampled race time after the grid is set"
    assert (
        technical_russell_score["total"] > baseline_russell_score["total"]
    ), "positive technical evidence should raise the target driver's contextual race score"
    baseline_ferrari_deg = SingleRaceSimulator(
        season,
        baseline_pace,
        iterations=80,
    )._degradation_rate(british_event, hamilton)
    technical_ferrari_deg = SingleRaceSimulator(
        season,
        technical_pace,
        iterations=80,
    )._degradation_rate(british_event, hamilton)
    assert (
        technical_ferrari_deg > baseline_ferrari_deg
    ), "negative tyre_deg evidence should increase simulated Ferrari tyre degradation"
    baseline_summary = SingleRaceSimulator(season, baseline_pace, iterations=500).simulate_summary(british_event)
    technical_summary = SingleRaceSimulator(season, technical_pace, iterations=500).simulate_summary(british_event)
    baseline_mercedes_win = sum(
        row.win for row in baseline_summary.race_probabilities if season.drivers[row.driver_id].team_id == "mercedes"
    )
    technical_mercedes_win = sum(
        row.win for row in technical_summary.race_probabilities if season.drivers[row.driver_id].team_id == "mercedes"
    )
    assert (
        technical_mercedes_win > baseline_mercedes_win
    ), "technical evidence should move same-seed simulated win probabilities in the expected direction"
    assert report.evidence, "seed Codex evidence should be loaded"
    assert report.evidence_quality, "prediction report should expose source-aware Codex evidence quality"
    quality_by_claim = {row.claim_id: row for row in report.evidence_quality}
    assert (
        "seed-british-001" in quality_by_claim
    ), "evidence quality should include seed Codex claims"
    assert (
        "seed_scenario_source" in quality_by_claim["seed-british-001"].risk_flags
    ), "seed scenario evidence should be flagged as diagnostic quality only"
    assert (
        quality_by_claim["seed-british-001"].triangulation_status == "seed_or_test_only"
    ), "seed scenario evidence should expose seed-only triangulation"
    assert (
        quality_by_claim["seed-british-001"].conflict_status == "no_conflict"
    ), "non-conflicting seed evidence should expose a no_conflict status"
    assert (
        "seed_only_triangulation" in quality_by_claim["seed-british-001"].risk_flags
    ), "seed-only evidence should be flagged before formal edge use"
    assert (
        0 < quality_by_claim["seed-british-001"].model_input_weight < 1
    ), "seed-only Codex evidence should be downweighted before entering the simulator"
    assert (
        report.ai_judgement["evidence_quality_count"] == len(report.evidence_quality)
    ), "AI judgement should summarize evidence quality rows"
    assert (
        report.ai_judgement["weak_triangulation_count"] >= 1
    ), "AI judgement should summarize weak/single-source evidence support"
    assert report.factor_trace, "prediction report should expose normalized factor traces"
    factor_by_claim = {row.claim_id: row for row in report.factor_trace}
    for claim_id, expected_metric in {
        "seed-british-001": "energy_recovery",
        "seed-british-002": "upgrade_effect",
        "seed-british-003": "straight_line_speed",
        "seed-british-004": "tyre_deg",
        "seed-british-005": "launch_performance",
        "british_gp-weather-openmeteo-001": "wet_skill",
    }.items():
        assert claim_id in factor_by_claim, f"{claim_id} should have a factor trace row"
        assert factor_by_claim[claim_id].metric == expected_metric
        assert factor_by_claim[claim_id].route_status != "unsupported_metric"
    assert (
        factor_by_claim["seed-british-001"].route == "track_contextual_pace"
    ), "Mercedes ERS claim should route into track-contextual pace"
    assert (
        factor_by_claim["seed-british-001"].context_multiplier
        == round(
            technical_context_multiplier(
                "energy_recovery",
                british_event.track_type,
                feature_refs=british_event.feature_refs,
            ),
            4,
        )
    ), "Mercedes ERS trace should expose the same track-context multiplier used by PaceModel"
    assert (
        factor_by_claim["seed-british-001"].track_demand_component == "ers_demand"
    ), "Mercedes ERS trace should expose the track-demand component used for contextual weighting"
    assert (
        factor_by_claim["seed-british-001"].track_demand_value
        == british_event_technical_profile.ers_demand
    ), "Mercedes ERS trace should expose the track-demand value used for Silverstone"
    assert (
        factor_by_claim["seed-british-001"].track_demand_profile
        and factor_by_claim["seed-british-001"].track_demand_profile["track_type"] == british_event.track_type
    ), "factor trace should preserve the full track-demand profile for audit"
    assert (
        factor_by_claim["seed-british-001"].weighted_input_impact
        == factor_by_claim["seed-british-001"].signed_input_impact
    ), "factor trace should keep signed_input_impact as the quality-weighted model input"
    assert (
        factor_by_claim["seed-british-001"].effective_race_input
        == round(
            factor_by_claim["seed-british-001"].weighted_input_impact
            * factor_by_claim["seed-british-001"].context_multiplier,
            4,
        )
    ), "track-context technical factors should expose the effective race simulator input"
    assert (
        factor_by_claim["seed-british-001"].effective_qualifying_input
        == round(
            factor_by_claim["seed-british-001"].weighted_input_impact
            * technical_context_multiplier(
                "energy_recovery",
                british_event.track_type,
                mode="qualifying",
                feature_refs=british_event.feature_refs,
            ),
            4,
        )
    ), "track-context technical factors should expose the effective qualifying simulator input"
    assert (
        factor_by_claim["seed-british-001"].context_multiplier_reason
        and "clipping" in factor_by_claim["seed-british-001"].context_multiplier_reason
    ), "ERS trace should explain the mechanism behind the context multiplier"
    assert (
        factor_by_claim["seed-british-004"].route == "tyre_degradation"
    ), "Ferrari tyre degradation claim should route into simulator degradation"
    assert (
        factor_by_claim["seed-british-004"].context_multiplier is None
    ), "non-track-context factors should not expose a contextual pace multiplier"
    assert (
        factor_by_claim["seed-british-005"].route == "race_start_launch"
    ), "Ferrari launch claim should route into the start/first-lap simulator surface"
    assert (
        factor_by_claim["seed-british-005"].track_demand_component == "launch_importance"
    ), "launch claims should expose the launch-importance demand component"
    assert (
        factor_by_claim["seed-british-005"].track_demand_value
        == british_event_technical_profile.launch_importance
    ), "launch claims should use the event-aware launch-importance value"
    assert (
        factor_by_claim["seed-british-005"].effective_race_input
        == round(
            factor_by_claim["seed-british-005"].weighted_input_impact
            * technical_context_multiplier(
                "launch_performance",
                british_event.track_type,
                feature_refs=british_event.feature_refs,
            ),
            4,
        )
    ), "launch trace should expose the exact start-simulator input"
    assert (
        factor_by_claim["seed-british-005"].max_win_probability_delta is not None
        and factor_by_claim["seed-british-005"].max_win_probability_delta >= 0
    ), "positive launch evidence should not inherit unrelated same-target negative evidence impact"
    launch_impact = next(row for row in report.evidence_impact if row.claim_id == "seed-british-005")
    assert (
        launch_impact.attribution_method == "diagnostic_same_seed_leave_one_claim_comparison"
    ), "evidence impact should isolate each claim with a leave-one counterfactual"
    assert (
        "track_context_multiplier_applied=true" in factor_by_claim["seed-british-003"].route_notes
    ), "straight-line technical facts should disclose contextual track weighting"
    assert any(
        note.startswith("context_multiplier=") for note in factor_by_claim["seed-british-003"].route_notes
    ), "track-context route notes should include the numeric multiplier"
    assert (
        report.ai_judgement["factor_route_counts"].get("track_contextual_pace", 0) >= 3
    ), "AI judgement should summarize routed technical factor counts"
    assert (
        report.ai_judgement["factor_route_counts"].get("race_start_launch", 0) >= 1
    ), "AI judgement should summarize launch/start factor routing separately from pace"
    with tempfile.TemporaryDirectory() as directory:
        research_root = Path(directory)
        event_dir = research_root / "triangulation_gp"
        event_dir.mkdir(parents=True, exist_ok=True)
        cutoff = "2026-06-01T00:00:00+00:00"
        source_log = {
            "event_id": "triangulation_gp",
            "event_name": "Triangulation Grand Prix",
            "knowledge_cutoff": cutoff,
            "sources": [
                {
                    "url": "https://www.formula1.com/en/latest/article/triangulation-official",
                    "source": "F1 official",
                    "source_class": "f1_official",
                    "reliability": 0.95,
                    "published_at": "2026-05-30T10:00:00+00:00",
                    "captured_at": "2026-05-30T10:05:00+00:00",
                    "cutoff_status": "within_cutoff",
                    "used_in_claim_ids": ["triangulation-001"],
                },
                {
                    "url": "https://www.fia.com/events/triangulation-gp/classification",
                    "source": "FIA official",
                    "source_class": "fia",
                    "reliability": 0.95,
                    "published_at": "2026-05-30T11:00:00+00:00",
                    "captured_at": "2026-05-30T11:05:00+00:00",
                    "cutoff_status": "within_cutoff",
                    "used_in_claim_ids": ["triangulation-002"],
                },
            ],
        }
        (event_dir / "source_log.json").write_text(json.dumps(source_log), encoding="utf-8")
        triangulated_claims = [
            EvidenceClaim(
                claim_id="triangulation-001",
                event_id="triangulation_gp",
                source="F1 official",
                source_url="https://www.formula1.com/en/latest/article/triangulation-official",
                published_at="2026-05-30T10:00:00+00:00",
                observed_at="2026-05-30T10:05:00+00:00",
                target_type="team",
                target_id="mercedes",
                claim_type="practice_pace",
                metric="race_pace",
                direction="positive",
                magnitude=0.05,
                confidence=0.82,
                uncertainty=0.12,
                evidence_text="Mercedes long-run pace was competitive on the relevant track profile.",
                reasoning="Official timing summary supports a positive race-pace adjustment.",
                review_required=False,
            ),
            EvidenceClaim(
                claim_id="triangulation-002",
                event_id="triangulation_gp",
                source="FIA official",
                source_url="https://www.fia.com/events/triangulation-gp/classification",
                published_at="2026-05-30T11:00:00+00:00",
                observed_at="2026-05-30T11:05:00+00:00",
                target_type="team",
                target_id="mercedes",
                claim_type="classification_pace",
                metric="race_pace",
                direction="positive",
                magnitude=0.04,
                confidence=0.80,
                uncertainty=0.14,
                evidence_text="The FIA classification corroborates Mercedes pace against the same peer group.",
                reasoning="Independent official classification reduces source-specific evidence risk.",
                review_required=False,
            ),
        ]
        triangulated_rows = EvidenceQualityScorer(research_root).score_event(
            "triangulation_gp",
            triangulated_claims,
            [],
            parse_dt(cutoff),
        )
        assert all(
            row.triangulation_status == "independent_corroboration"
            for row in triangulated_rows
        ), "same-direction claims with independent official sources should be marked as corroborated"
        assert all(
            row.independent_source_count >= 2 for row in triangulated_rows
        ), "triangulation should count independent source groups"
        conflict_dir = research_root / "conflict_gp"
        conflict_dir.mkdir(parents=True, exist_ok=True)
        conflict_source_log = {
            "event_id": "conflict_gp",
            "event_name": "Conflict Grand Prix",
            "knowledge_cutoff": cutoff,
            "sources": [
                {
                    "url": "https://www.formula1.com/en/latest/article/conflict-positive",
                    "source": "F1 official",
                    "source_class": "f1_official",
                    "reliability": 0.95,
                    "published_at": "2026-05-30T10:00:00+00:00",
                    "captured_at": "2026-05-30T10:05:00+00:00",
                    "cutoff_status": "within_cutoff",
                    "used_in_claim_ids": ["conflict-001"],
                },
                {
                    "url": "https://www.fia.com/events/conflict-gp/technical",
                    "source": "FIA technical note",
                    "source_class": "fia",
                    "reliability": 0.95,
                    "published_at": "2026-05-30T11:00:00+00:00",
                    "captured_at": "2026-05-30T11:05:00+00:00",
                    "cutoff_status": "within_cutoff",
                    "used_in_claim_ids": ["conflict-002"],
                },
            ],
        }
        (conflict_dir / "source_log.json").write_text(json.dumps(conflict_source_log), encoding="utf-8")
        conflicting_claims = [
            EvidenceClaim(
                claim_id="conflict-001",
                event_id="conflict_gp",
                source="F1 official",
                source_url="https://www.formula1.com/en/latest/article/conflict-positive",
                published_at="2026-05-30T10:00:00+00:00",
                observed_at="2026-05-30T10:05:00+00:00",
                target_type="team",
                target_id="mercedes",
                claim_type="ers",
                metric="energy_recovery",
                direction="positive",
                magnitude=0.05,
                confidence=0.82,
                uncertainty=0.12,
                evidence_text="Mercedes deployment looked cleaner across the representative high-speed run.",
                reasoning="A cleaner deployment profile should improve energy_recovery on this circuit class.",
                review_required=False,
            ),
            EvidenceClaim(
                claim_id="conflict-002",
                event_id="conflict_gp",
                source="FIA technical note",
                source_url="https://www.fia.com/events/conflict-gp/technical",
                published_at="2026-05-30T11:00:00+00:00",
                observed_at="2026-05-30T11:05:00+00:00",
                target_type="team",
                target_id="mercedes",
                claim_type="ers",
                metric="energy_recovery",
                direction="negative",
                magnitude=0.04,
                confidence=0.78,
                uncertainty=0.16,
                evidence_text="A technical note suggests Mercedes clipped earlier than peers on the same straights.",
                reasoning="Earlier clipping should reduce energy_recovery benefit until resolved.",
                review_required=False,
            ),
        ]
        conflicting_rows = EvidenceQualityScorer(research_root).score_event(
            "conflict_gp",
            conflicting_claims,
            [],
            parse_dt(cutoff),
        )
        assert all(
            row.conflict_status == "independent_source_conflict"
            for row in conflicting_rows
        ), "opposing same-target metric claims from independent sources should be flagged as conflicts"
        assert all(
            row.conflicting_claim_count == 1 for row in conflicting_rows
        ), "conflict diagnostics should count opposing claims"
        assert all(
            "independent_source_conflict" in row.risk_flags for row in conflicting_rows
        ), "independent source conflicts should become evidence-quality risk flags"
        assert all(
            row.model_input_weight <= row.conflict_score for row in conflicting_rows
        ), "conflict diagnostics should cap model input weights"
        assert all(
            row.quality_status != "strong" for row in conflicting_rows
        ), "conflicted evidence should not be promoted to strong quality"
    packet = PredictionPacketBuilder(PredictionPipeline(iterations=120)).build(
        "british_gp",
        knowledge_cutoff="2026-06-30T12:00:00+00:00",
        iterations=120,
    )
    assert packet.status == "diagnostic_only", "prediction packet should not promote diagnostic inputs to formal edge"
    assert not packet.formal_edge_ready, "prediction packet should keep formal edge readiness false while blockers remain"
    assert (
        "codex_evidence_quality_review_required" in packet.blocker_codes
    ), "prediction packet should surface weak/review-required Codex evidence quality"
    assert (
        packet.market_context["usable_snapshot_count"] >= 1
    ), "prediction packet should summarize cutoff-usable market snapshots"
    assert (
        packet.codex_context["factor_route_counts"].get("track_contextual_pace", 0) >= 3
    ), "prediction packet should preserve technical factor route counts"
    assert (
        packet.codex_context["factor_trace"][0]["route_status"] != "unsupported_metric"
    ), "prediction packet should expose simulator-routed factor trace rows"
    assert all(
        "effective_race_input" in row and "weighted_input_impact" in row
        for row in packet.codex_context["factor_trace"]
    ), "prediction packet should preserve effective simulator input decomposition"
    assert any(
        row.get("track_demand_component") == "ers_demand"
        for row in packet.codex_context["factor_trace"]
    ), "prediction packet should preserve technical track-demand components"
    assert any(
        row.get("context_multiplier") is not None
        for row in packet.codex_context["factor_trace"]
        if row.get("route") == "track_contextual_pace"
    ), "prediction packet should preserve track-context multipliers for technical factors"
    assert (
        packet.codex_context["conflict_status_counts"].get("no_conflict", 0) >= 1
    ), "prediction packet should summarize Codex conflict diagnostics"
    assert (
        packet.codex_context["average_model_input_weight"] < 1
    ), "prediction packet should expose quality-derived Codex input weighting"
    packet_intake = packet.codex_context["intake"]
    assert (
        packet_intake["source_candidate_status"] == "source_candidates_ready_for_claim_review"
    ), "prediction packet should expose the source-candidate audit status"
    assert (
        packet_intake["research_preflight_status"] == "preflight_passed"
    ), "prediction packet should expose the research-packet preflight status"
    assert (
        packet_intake["preflight_valid_claim_count"] >= 1
    ), "prediction packet should preserve valid preflight claim counts"
    assert packet.packet_payload_sha256, "prediction packet should carry a payload hash"
    with tempfile.TemporaryDirectory() as directory:
        paths = PredictionPacketBuilder(PredictionPipeline(iterations=80)).write(
            "british_gp",
            knowledge_cutoff="2026-06-30T12:00:00+00:00",
            iterations=80,
            output_dir=Path(directory),
        )
        assert paths["json"].exists(), "prediction packet JSON should be written"
        assert paths["markdown"].exists(), "prediction packet Markdown should be written"
    with tempfile.TemporaryDirectory() as directory:
        temp_root = Path(directory)

        class FakeOpenF1WeatherCalendar:
            def meetings(self, **params):
                assert params["year"] == 2026, "forecast ingestion should query the requested season"
                return [
                    {
                        "meeting_name": "British Grand Prix",
                        "meeting_official_name": "FORMULA 1 BRITISH GRAND PRIX 2026",
                        "date_start": "2026-07-03T00:00:00+00:00",
                        "date_end": "2026-07-05T00:00:00+00:00",
                        "location": "Silverstone",
                        "circuit_short_name": "Silverstone",
                        "country_name": "United Kingdom",
                    }
                ]

        class FakeOpenMeteoForecast:
            def geocode(self, name, count=10, country_code=None, language="en"):
                assert name == "Silverstone", "forecast ingestion should use the event weather location alias first"
                return {
                    "results": [
                        {
                            "name": "Silverstone",
                            "country": "United Kingdom",
                            "latitude": 52.0786,
                            "longitude": -1.0169,
                        }
                    ]
                }

            def forecast_weather(self, latitude, longitude, daily=None, timezone="UTC", forecast_days=16):
                assert forecast_days == 5, "forecast ingestion should pass through the requested horizon"
                return {
                    "daily": {
                        "time": ["2026-07-04", "2026-07-05"],
                        "precipitation_probability_max": [4, 12],
                        "precipitation_sum": [0.0, 0.1],
                        "rain_sum": [0.0, 0.1],
                        "weather_code": [2, 61],
                    }
                }

        forecast_result = LiveIngestor(
            store=RawSnapshotStore(temp_root),
            openf1=FakeOpenF1WeatherCalendar(),
            open_meteo=FakeOpenMeteoForecast(),
        ).ingest_weather_forecasts(year=2026, event_queries=["British"], forecast_days=5)
        assert len(forecast_result.records) == 1, "race-week forecast ingestion should write one snapshot"
        forecast_provider = WeatherForecastProvider(raw_root=temp_root)
        forecast_pipeline = PredictionPipeline(
            iterations=80,
            weather_forecast_provider=forecast_provider,
        )
        forecast_report = forecast_pipeline.predict_event("british_gp")
        assert (
            forecast_report.event.weather_prior["wet_probability"] == 0.12
        ), "cutoff-current prediction should use the Open-Meteo race-week forecast probability"
        assert (
            forecast_report.event.feature_refs["weather_forecast"]["race_week_forecast"] is True
        ), "prediction report should expose race-week weather forecast provenance"
        early_cutoff_report = forecast_pipeline.predict_event(
            "british_gp",
            knowledge_cutoff="1900-01-01T00:00:00+00:00",
        )
        assert (
            "weather_forecast" not in early_cutoff_report.event.feature_refs
        ), "forecast snapshots captured after the cutoff must not enter historical replay"
    assert report.evidence_impact, "prediction report should expose Codex evidence impact diagnostics"
    assert (
        report.evidence_impact[0].attribution_method == "diagnostic_same_seed_leave_one_claim_comparison"
    ), "evidence impact should disclose its diagnostic attribution method"
    probability_impact = next(row for row in report.evidence_impact if row.affected_outcomes)
    assert (
        "win_delta" in probability_impact.affected_outcomes[0]
    ), "evidence impact should include target-scope probability deltas"
    assert report.feature_adjustments, "processed data features should be loaded"
    official_feature_adjustments = [
        adjustment
        for adjustment in report.feature_adjustments
        if adjustment.source.startswith("f1_official_standings:")
    ]
    assert (
        official_feature_adjustments
    ), "official standings should enter the single-race pace model as structured feature adjustments"
    official_feature_lookup = {
        (adjustment.target_type, adjustment.target_id, adjustment.metric): adjustment
        for adjustment in official_feature_adjustments
    }
    assert (
        official_feature_lookup[("team", "mercedes", "race_pace")].value > 0
    ), "constructor standings should give Mercedes a positive team form prior"
    assert (
        official_feature_lookup[("team", "ferrari", "race_pace")].value > 0
    ), "constructor standings should give Ferrari a positive team form prior"
    assert (
        official_feature_lookup[("team", "cadillac", "race_pace")].value < 0
    ), "constructor standings should give the zero-point Cadillac team a negative team form prior"
    assert (
        official_feature_lookup[("driver", "antonelli", "race_pace")].value > 0
    ), "driver standings should give the championship leader a positive driver form prior"
    assert (
        official_feature_lookup[("driver", "perez", "race_pace")].value < 0
    ), "driver standings should penalize zero-point drivers in the driver form prior"
    assert report.market_edges, "market comparison should be produced"
    season_forecast = pipeline.forecast_season("2026-06-30T00:00:00+00:00", iterations=80)
    assert season_forecast.rows, "season forecast should produce driver rows"
    assert season_forecast.status == "diagnostic_only", "season forecast should not be marked formal-ready"
    assert not season_forecast.formal_ready, "strategy-aware season forecast should remain diagnostic"
    assert (
        season_forecast.event_sampling_model == "strategy_aware_race_time_sampler"
    ), "season forecast should reuse the strategy-aware single-race sampling boundary"
    assert (
        "strategy_aware_event_sampling_for_remaining_events" in season_forecast.warnings
    ), "season forecast diagnostics should disclose strategy-aware event sampling"
    assert (
        season_forecast.completed_events_counted >= 8
    ), "season forecast should count completed pre-cutoff race results"
    assert (
        season_forecast.base_points_source == "fastf1_result_points_before_cutoff"
    ), "season forecast should prefer FastF1 result points for completed-race base points"
    assert any(
        warning.startswith("official_standings_unavailable_before_cutoff")
        for warning in season_forecast.warnings
    ), "official standings captured after the cutoff should not seed the replay forecast"
    assert (
        season_forecast.base_points_event_sources["fastf1_points"] == season_forecast.completed_events_counted
    ), "all counted completed races should use stored FastF1 points when available"
    assert (
        season_forecast.base_points_event_sources["classified_order_fallback"] == 0
    ), "season forecast should not fall back to classified-order points when FastF1 points exist"
    assert (
        season_forecast.remaining_events_simulated >= 10
    ), "season forecast should simulate remaining races"
    assert (
        season_forecast.rows[0].expected_final_points >= season_forecast.rows[0].base_points
    ), "season forecast expected final points should include remaining simulated points"
    title_probability_sum = sum(row.champion_probability for row in season_forecast.rows)
    assert (
        0.98 <= title_probability_sum <= 1.02
    ), "season forecast champion probabilities should approximately sum to one"
    official_standings = OfficialStandingsRepository().build(2026, season=pipeline.data_source.load())
    assert len(official_standings.driver_rows) == 22, "official driver standings should parse all rows"
    assert len(official_standings.team_rows) == 11, "official team standings should parse all rows"
    assert (
        official_standings.roster_status == "aligned"
    ), "official standings should align with the project seed roster before seeding current season points"
    assert (
        official_standings.can_seed_season_points
    ), "official standings should be eligible to seed current base points after roster alignment"
    assert (
        not official_standings.unmatched_official_drivers
    ), "roster audit should not leave official drivers unmatched"
    assert (
        not official_standings.unmatched_project_drivers
    ), "roster audit should not leave project seed drivers unmatched"
    assert (
        not official_standings.team_mismatch_drivers
    ), "roster audit should not leave driver/team mismatches"
    roster_plan = SeedRosterSyncPlanner().plan(2026)
    assert roster_plan.status == "no_changes", "official roster sync should find the current seed already aligned"
    with tempfile.TemporaryDirectory() as directory:
        drift_seed = Path(directory) / "drift_seed.json"
        applied_seed = Path(directory) / "applied_seed.json"
        raw_seed = json.loads(Path("data/seed/demo_season.json").read_text(encoding="utf-8"))
        raw_seed["drivers"] = [driver for driver in raw_seed["drivers"] if driver["driver_id"] != "colapinto"]
        for driver in raw_seed["drivers"]:
            if driver["driver_id"] == "gasly":
                driver["current_points"] = 0
            if driver["driver_id"] == "hadjar":
                driver["team_id"] = "racing_bulls"
        drift_seed.write_text(json.dumps(raw_seed, ensure_ascii=False, indent=2), encoding="utf-8")
        drift_plan = SeedRosterSyncPlanner().plan(2026, seed_path=drift_seed)
        drift_actions = {operation.action for operation in drift_plan.operations}
        assert "update_driver_points" in drift_actions, "roster sync should plan source-backed points corrections"
        assert "update_driver_team" in drift_actions, "roster sync should plan source-backed team corrections"
        assert "add_driver" in drift_actions, "roster sync should flag official drivers missing from the seed"
        assert (
            drift_plan.status == "review_required"
        ), "new driver priors should require review instead of being silently applied"
        apply_result = SeedRosterSyncPlanner().apply(drift_plan, seed_path=drift_seed, output_path=applied_seed)
        applied_raw = json.loads(applied_seed.read_text(encoding="utf-8"))
        applied_drivers = {driver["driver_id"]: driver for driver in applied_raw["drivers"]}
        assert applied_drivers["gasly"]["current_points"] == 41, "auto apply should update official points"
        assert applied_drivers["hadjar"]["team_id"] == "red_bull", "auto apply should update official team assignment"
        assert "colapinto" not in applied_drivers, "review-required new drivers should not auto-apply by default"
        assert apply_result.skipped_review_required_count >= 1, "apply result should report skipped review changes"
    miami_cutoff_forecast = pipeline.forecast_season("2026-05-03T00:00:00+00:00", iterations=40)
    assert (
        miami_cutoff_forecast.completed_events_counted < season_forecast.completed_events_counted
    ), "season forecast must not count same-day race results before the cutoff"
    generated_report = pipeline.predict_event("miami_gp")
    assert generated_report.race_probabilities, "calendar-generated event should be predictable"
    assert generated_report.event.laps == 57, "Miami should use the official Formula1.com planned lap count"
    assert (
        generated_report.event.feature_refs.get("weather_profile")
    ), "Miami should use an archived Open-Meteo climate weather profile"
    generated_input_audit = audit_event_input(generated_report.event)
    assert (
        generated_input_audit.quality == "generated_verified"
    ), "calendar-generated events with sourced profiles should expose verified generated input quality"
    assert (
        "heuristic_generated_event_profile" not in generated_input_audit.risk_codes
    ), "sourced generated profiles should not keep the heuristic profile blocker"
    assert (
        "track_map" in generated_input_audit.verified_fields
    ), "calendar-generated track maps should use stored circuit profile geometry"
    assert (
        "laps" in generated_input_audit.verified_fields
    ), "calendar-generated lap counts should use official race profile pages"
    assert (
        "track_type" in generated_input_audit.derived_fields
    ), "calendar-generated track type should be derived from stored circuit geometry"
    assert (
        "weather_prior" in generated_input_audit.derived_fields
    ), "calendar-generated weather prior should be derived from archived climate profiles"
    assert (
        "track_type" not in generated_input_audit.heuristic_fields
    ), "stored circuit geometry should replace event-name track-type heuristics"
    assert (
        "laps" not in generated_input_audit.heuristic_fields
    ), "official race profiles should replace static lap-count heuristics"
    assert (
        not generated_input_audit.heuristic_fields
    ), "sourced generated profile fields should replace static heuristics"
    assert (
        "track_map" not in generated_input_audit.placeholder_fields
    ), "stored circuit profile geometry should replace placeholder track maps"
    loaded_events = pipeline.data_source.load().events
    missing_track_assets = [
        event.event_id
        for event in loaded_events
        if not (
            event.feature_refs.get("track_map_asset")
            or (event.feature_refs.get("event_input_provenance") or {}).get("track_map_asset")
        )
    ]
    assert not missing_track_assets, f"all model events should expose official track-map assets: {missing_track_assets}"
    bad_track_assets = []
    for event in loaded_events:
        asset = event.feature_refs.get("track_map_asset") or (
            event.feature_refs.get("event_input_provenance") or {}
        ).get("track_map_asset") or {}
        if asset.get("source") == "f1_official_track_icon" or "Track%20icons" in str(asset.get("source_url")):
            bad_track_assets.append(
                {
                    "event_id": event.event_id,
                    "source": asset.get("source"),
                    "source_url": asset.get("source_url"),
                    "web_path": asset.get("web_path"),
                }
            )
    assert not bad_track_assets, f"frontend track assets must use real circuit maps, not F1 carbon icons: {bad_track_assets}"
    frontend_html = Path("web/index.html").read_text(encoding="utf-8")
    frontend_js = Path("web/app.js").read_text(encoding="utf-8")
    server_py = Path("src/f1predict/server.py").read_text(encoding="utf-8")
    assert (
        "Research Packet Preflight" in frontend_html
        and "researchPreflightList" in frontend_html
    ), "frontend should expose the research packet preflight panel"
    assert (
        "/api/research-preflight" in frontend_js
        and "renderResearchPreflight" in frontend_js
    ), "frontend should load and render research preflight diagnostics"
    assert (
        "/api/research-preflight" in server_py
        and "CodexResearchPacketPreflight" in server_py
    ), "server should expose research preflight diagnostics"
    assert (
        "Simulator Calibration" in frontend_html
        and "simulatorCalibrationList" in frontend_html
    ), "frontend should expose simulator calibration diagnostics"
    assert (
        "/api/simulator-calibration" in frontend_js
        and "renderSimulatorCalibration" in frontend_js
    ), "frontend should load and render simulator calibration diagnostics"
    assert (
        "/api/simulator-calibration" in server_py
        and "SimulatorCalibrationBuilder" in server_py
    ), "server should expose simulator calibration diagnostics"
    track_asset_audit = TrackAssetAuditor().build(2026, loaded_events)
    assert track_asset_audit.status == "passed", "track asset audit should pass for all loaded season events"
    assert (
        track_asset_audit.passed_event_count == track_asset_audit.event_count
    ), "every loaded event should have a verified circuit-map asset"
    track_profile_risks = {
        event.event_id: audit_event_input(event).to_dict()
        for event in loaded_events
        if audit_event_input(event).placeholder_fields or audit_event_input(event).heuristic_fields
    }
    assert not track_profile_risks, f"loaded event track profiles should not use generic placeholders: {track_profile_risks}"
    assert generated_report.feature_adjustments, "calendar-generated events should receive point-in-time form features"
    assert all(
        "miami" not in adjustment.source for adjustment in generated_report.feature_adjustments
    ), "Miami prediction features must not include Miami race results"
    assert all(
        adjustment.observed_at <= "2026-05-03T00:00:00+00:00"
        for adjustment in generated_report.feature_adjustments
    ), "Miami prediction features should be available before the race cutoff"
    backtest = Backtester(PredictionPipeline(iterations=300)).run_replay()
    assert len(backtest) >= 8, "diagnostic replay should cover completed FastF1 result snapshots"
    chinese_row = next(row for row in backtest if row.event_id == "chinese_gp")
    assert chinese_row.actual_winner == "antonelli", "FastF1 canonical result should override seed Chinese winner"
    assert (
        chinese_row.market_snapshot_count >= 1
    ), "cutoff-valid supported Chinese market snapshots should enter diagnostic replay"
    assert (
        chinese_row.market_edge_count >= 1
    ), "supported Chinese market snapshots should produce diagnostic market edges"
    assert (
        chinese_row.market_snapshot_after_cutoff_count >= 1
    ), "after-cutoff Chinese market should be exposed diagnostically"
    coverage = EvidenceCoverageAuditor().build(as_of="2026-06-30T00:00:00+00:00")
    assert coverage.completed_event_count >= 8, "evidence coverage should cover due completed events"
    assert coverage.events_with_evidence >= 8, "completed replay events should have diagnostic Codex evidence"
    miami_coverage = next(row for row in coverage.rows if row.event_id == "miami_gp")
    chinese_coverage = next(row for row in coverage.rows if row.event_id == "chinese_gp")
    assert (
        miami_coverage.event_input_quality == "generated_verified"
    ), "coverage should expose generated input quality"
    assert (
        "laps" in miami_coverage.event_input_verified_fields
    ), "coverage should expose official planned lap-count provenance"
    assert (
        "weather_prior" in miami_coverage.event_input_derived_fields
    ), "coverage should expose archived climate weather-prior provenance"
    assert (
        not miami_coverage.event_input_heuristic_fields
    ), "coverage should show no remaining heuristic generated profile fields"
    assert (
        "verified_event_profile" not in miami_coverage.missing_inputs
    ), "coverage should not request generated profile data once all profile fields are sourced or derived"
    assert (
        miami_coverage.missing_market_snapshot_detail
    ), "coverage should expose the required cutoff for missing market snapshots"
    assert (
        miami_coverage.missing_market_snapshot_detail["status"] == "missing_cutoff_valid_snapshot"
    ), "missing market details should explain that no cutoff-valid snapshot exists"
    assert (
        chinese_coverage.market_snapshot_after_cutoff_details
    ), "coverage should expose after-cutoff market snapshots diagnostically"
    assert (
        chinese_coverage.market_snapshot_after_cutoff_details[0]["status"] == "after_cutoff"
    ), "after-cutoff market details should be labeled explicitly"
    assert (
        chinese_coverage.market_snapshot_count >= 1
    ), "coverage should count cutoff-valid supported non-winner market snapshots"
    assert (
        not chinese_coverage.missing_market_snapshot_detail
    ), "supported Chinese market snapshots should clear the missing market blocker"
    assert any(
        detail["market_type"] == "constructor_double_podium"
        for detail in chinese_coverage.market_snapshot_details
    ), "coverage should identify supported non-winner market snapshot types"
    assert (
        coverage.events_with_retrospective_source_snapshots >= 1
    ), "coverage should expose retrospective source snapshots"
    assert (
        miami_coverage.retrospective_source_details
    ), "coverage should expose URL-level details for retrospective source snapshots"
    assert (
        miami_coverage.retrospective_source_details[0]["archive_status"] == "missing_cutoff_archive"
    ), "retrospective source details should explain that cutoff archive proof is missing"
    replay_analysis = ReplayAnalysisBuilder(PredictionPipeline(iterations=200)).build(
        year=2026,
        as_of="2026-06-30T00:00:00+00:00",
    )
    assert replay_analysis.status == "diagnostic_only", "replay analysis should be explicitly diagnostic"
    assert not replay_analysis.formal_backtest_ready, "current replay should not be marked formal-ready"
    assert replay_analysis.diagnostic_metrics["diagnostic_scored_events"] >= 8, "analysis should score completed replay rows"
    assert (
        replay_analysis.diagnostic_metrics["events_with_evidence_impact"] >= 8
    ), "analysis should expose Codex evidence-impact diagnostics for replayed events"
    assert (
        replay_analysis.diagnostic_metrics["events_with_evidence_quality"] >= 8
    ), "analysis should expose Codex evidence-quality diagnostics for replayed events"
    assert (
        replay_analysis.diagnostic_metrics["events_with_weak_evidence_quality"] >= 1
    ), "analysis should count weak or review-required Codex evidence quality"
    assert (
        replay_analysis.diagnostic_metrics["max_evidence_win_delta"] is not None
    ), "analysis should summarize the largest Codex evidence win-probability sensitivity"
    assert (
        replay_analysis.diagnostic_metrics["events_with_market_snapshots"] >= 2
    ), "analysis should count supported winner and non-winner market snapshots"
    assert any(
        issue.code == "retrospective_source_snapshots" for issue in replay_analysis.issues
    ), "analysis should surface retrospective source snapshots"
    root_causes = {cause.code: cause for cause in replay_analysis.root_causes}
    assert (
        "market_data_gap" in root_causes and root_causes["market_data_gap"].blocks_formal_claim
    ), "root-cause diagnosis should identify missing same-time market data as a formal blocker"
    assert (
        "source_time_integrity_gap" in root_causes and root_causes["source_time_integrity_gap"].blocks_formal_claim
    ), "root-cause diagnosis should identify retrospective sources as a formal blocker"
    assert (
        "model_ranking_calibration_gap" in root_causes
        and not root_causes["model_ranking_calibration_gap"].blocks_formal_claim
    ), "model ranking misses should be diagnosed without pretending the replay is formal"
    assert not any(
        issue.code == "missing_processed_features" for issue in replay_analysis.issues
    ), "season opener should not be mislabeled as missing processed features"
    assert not any(
        issue.code == "calendar_result_round_mismatch" for issue in replay_analysis.issues
    ), "cancelled-event sequence shifts should not be mislabeled as round mismatches"
    assert any(
        issue.code == "season_opener_no_prior_form" and not issue.blocks_formal_claim
        for issue in replay_analysis.issues
    ), "season opener with no prior form should be tracked as nonblocking provenance"
    assert not any(
        issue.code == "heuristic_generated_event_profile"
        for issue in replay_analysis.issues
    ), "archived weather profiles should remove the generated-profile heuristic blocker"
    assert not any(
        issue.code == "generated_structure_only_event_input" for issue in replay_analysis.issues
    ), "generated rows with field provenance should not be mislabeled as structure-only"
    miami_diagnostic = next(row for row in replay_analysis.event_diagnostics if row.event_id == "miami_gp")
    assert (
        miami_diagnostic.evidence_quality_count > 0
    ), "replay diagnostics should expose evidence-quality counts"
    assert (
        miami_diagnostic.event_input_quality == "generated_verified"
    ), "replay diagnostics should include event input quality"
    assert miami_diagnostic.round_number == 6, "Miami should keep its raw calendar round number"
    assert (
        miami_diagnostic.racing_sequence_number == 4
    ), "Miami should expose the cancellation-aware non-cancelled race sequence"
    assert (
        miami_diagnostic.cancelled_before_count == 2
    ), "Miami should expose how many cancelled events caused the schedule sequence shift"
    assert any(
        warning.startswith("round_sequence_shift_") for warning in miami_diagnostic.warnings
    ), "expected sequence shifts should be preserved as provenance warnings"
    assert (
        miami_diagnostic.retrospective_source_details
    ), "replay diagnostics should carry URL-level retrospective source details"
    assert (
        miami_diagnostic.evidence_impact_count > 0
    ), "replay diagnostics should carry Codex evidence-impact counts"
    assert (
        miami_diagnostic.max_evidence_win_delta is not None
    ), "replay diagnostics should carry max Codex evidence win-probability deltas"
    assert (
        miami_diagnostic.missing_market_snapshot_detail
    ), "replay diagnostics should carry missing market snapshot requirements"
    chinese_diagnostic = next(row for row in replay_analysis.event_diagnostics if row.event_id == "chinese_gp")
    assert (
        chinese_diagnostic.market_snapshot_after_cutoff_details
    ), "replay diagnostics should expose excluded after-cutoff market snapshots"
    assert (
        chinese_diagnostic.market_snapshot_count >= 1
    ), "replay diagnostics should count cutoff-valid supported non-winner market snapshots"
    assert (
        chinese_diagnostic.market_edge_count >= 1
    ), "replay diagnostics should count supported non-winner market edges"
    assert (
        not chinese_diagnostic.missing_market_snapshot_detail
    ), "Chinese replay diagnostics should not retain a missing market blocker once supported snapshots exist"
    assert (
        "track_map" in miami_diagnostic.event_input_verified_fields
    ), "replay diagnostics should expose verified track-map provenance"
    assert (
        "laps" in miami_diagnostic.event_input_verified_fields
    ), "replay diagnostics should expose verified planned lap-count provenance"
    assert (
        "track_type" in miami_diagnostic.event_input_derived_fields
    ), "replay diagnostics should expose derived track-type provenance"
    assert (
        "weather_prior" in miami_diagnostic.event_input_derived_fields
    ), "replay diagnostics should expose derived climate weather-prior provenance"
    assert (
        "track_type" not in miami_diagnostic.event_input_heuristic_fields
    ), "replay diagnostics should show track type no longer comes from event-name heuristics"
    assert (
        not miami_diagnostic.event_input_heuristic_fields
    ), "replay diagnostics should show no remaining heuristic generated profile fields"
    assert (
        "track_map" not in miami_diagnostic.event_input_placeholder_fields
    ), "replay diagnostics should show stored geometry replaced placeholder track maps"
    assert not any(
        issue.code == "seed_result_conflict" for issue in replay_analysis.issues
    ), "canonical FastF1 labels should not leave a blocking seed-result conflict"
    assert any(
        row.result_source == "fastf1" and row.fastf1_winner == row.actual_winner
        for row in replay_analysis.event_diagnostics
        if row.event_id == "chinese_gp"
    ), "replay analysis should expose FastF1 as the canonical result source"
    chronological = ChronologicalReplayBundleBuilder(PredictionPipeline(iterations=80)).build(
        year=2026,
        as_of="2026-06-30T00:00:00+00:00",
        iterations=80,
    )
    assert chronological.status == "diagnostic_only", "chronological replay bundle should not promote diagnostic replay"
    assert not chronological.formal_edge_ready, "chronological replay bundle should keep formal edge readiness false"
    assert chronological.replay_scope["due_events"] >= 8, "chronological replay bundle should cover due races"
    assert chronological.replay_scope["replayed_events"] >= 8, "chronological replay bundle should cover replayed races"
    assert len(chronological.timeline) >= chronological.replay_scope["calendar_events"], "chronological bundle should expose the full ordered calendar"
    assert (
        chronological.readiness_summary["blocking_action_count"] >= 9
    ), "chronological bundle should preserve formal readiness blockers"
    assert (
        chronological.improvement_summary["top_priority"] == "Backfill Same-Time Market Snapshots"
    ), "chronological bundle should preserve the current top project blocker"
    with tempfile.TemporaryDirectory() as directory:
        paths = ChronologicalReplayBundleBuilder(PredictionPipeline(iterations=60)).write(
            year=2026,
            as_of="2026-06-30T00:00:00+00:00",
            iterations=60,
            output_dir=Path(directory),
            write_components=False,
            write_freeze=False,
        )
        assert paths["json"].exists(), "chronological replay bundle JSON should be written"
        assert paths["markdown"].exists(), "chronological replay bundle Markdown should be written"
    readiness = FormalReadinessBuilder(PredictionPipeline(iterations=160)).build(
        year=2026,
        as_of="2026-06-30T00:00:00+00:00",
    )
    assert readiness.status == "inputs_required", "formal readiness should not hide remaining replay blockers"
    assert not readiness.formal_backtest_ready, "formal readiness should remain false while market/source blockers exist"
    assert (
        readiness.action_category_counts["market_snapshot_required"] >= 6
    ), "formal readiness should generate market backfill actions"
    assert (
        readiness.action_category_counts["source_archive_required"] >= 3
    ), "formal readiness should generate source archive proof actions"
    workstreams_by_category = {workstream.category: workstream for workstream in readiness.workstreams}
    assert (
        workstreams_by_category["market_snapshot_required"].blocking_action_count >= 6
    ), "formal readiness should group market blockers into a workstream"
    assert (
        workstreams_by_category["source_archive_required"].blocking_action_count >= 3
    ), "formal readiness should group source archive blockers into a workstream"
    assert (
        workstreams_by_category["after_cutoff_market_replacement"].blocking_action_count == 0
    ), "excluded after-cutoff market rows should be warnings rather than duplicate formal blockers"
    assert (
        workstreams_by_category["after_cutoff_market_replacement"].warning_action_count >= 2
    ), "formal readiness should keep excluded after-cutoff market rows visible for cleanup"
    assert (
        workstreams_by_category["market_snapshot_required"].command_templates
    ), "formal readiness workstreams should include executable command templates"
    assert any(
        "search-backfill-polymarket-history" in command
        for command in workstreams_by_category["market_snapshot_required"].command_templates
    ), "formal readiness market blockers should use the integrated search/history backfill command"
    assert any(
        "--market-type driver_h2h" in command
        for command in workstreams_by_category["market_snapshot_required"].command_templates
    ), "formal readiness market blockers should expose driver H2H as a supported diagnostic market backfill"
    assert any(
        "reviewed-market-template" in command
        for command in workstreams_by_category["market_snapshot_required"].command_templates
    ), "formal readiness market blockers should expose the reviewed market packet template command"
    assert any(
        "archive-reviewed-market-snapshot" in command
        for command in workstreams_by_category["market_snapshot_required"].command_templates
    ), "formal readiness market blockers should expose the strict reviewed market archive command"
    assert not any(
        "python -m f1predict.cli backfill-polymarket-history" in command
        or "<reviewed_gamma_payload.json>" in command
        for command in workstreams_by_category["market_snapshot_required"].command_templates
    ), "formal readiness market blockers should not emit the old manual Gamma payload flow"
    assert any(
        action.command_templates
        for event in readiness.events
        for action in event.actions
        if action.blocks_formal_claim
    ), "formal readiness blockers should include executable command templates"
    freeze_manifest = ReplayFreezeManifestBuilder().build(
        year=2026,
        as_of="2026-06-30T00:00:00+00:00",
        iterations=160,
    )
    freeze_groups = {group.group_id: group for group in freeze_manifest.artifact_groups}
    assert freeze_groups["source_code"].file_count > 0, "freeze manifest should fingerprint source code"
    assert freeze_groups["input_data"].file_count > 0, "freeze manifest should fingerprint prediction inputs"
    assert (
        freeze_manifest.report_summaries["formal_readiness"]["summary"]["formal_backtest_ready"] is False
    ), "freeze manifest should preserve formal readiness state"
    assert (
        "formal_edge_claim_not_ready" in freeze_manifest.integrity_flags
    ), "freeze manifest should disclose that current replay is diagnostic only"
    assert (
        "model_error_review" in freeze_manifest.report_summaries
    ), "freeze manifest should summarize model error review reports"
    assert (
        "improvement_plan" in freeze_manifest.report_summaries
    ), "freeze manifest should summarize improvement plan reports"
    mvp_gate = MVPGateBuilder().build(year=2026, as_of="2026-07-01T00:00:00+00:00")
    assert mvp_gate.diagnostic_mvp_operational, "MVP gate should recognize the diagnostic MVP path as operational"
    assert mvp_gate.mvp_delivery_ready, "MVP gate should allow diagnostic MVP delivery while formal-edge blockers remain"
    assert not mvp_gate.formal_edge_ready, "MVP gate must not promote diagnostic replay to formal edge"
    assert any(
        row.requirement_id == "market_gap_analysis" and row.blocks_formal_edge and not row.blocks_mvp_delivery
        for row in mvp_gate.requirements
    ), "MVP gate should expose missing market snapshots as formal blockers, not diagnostic MVP delivery blockers"
    market_gate = next(row for row in mvp_gate.requirements if row.requirement_id == "market_gap_analysis")
    assert any(
        "diagnostic_non_winner_market_events" in item for item in market_gate.evidence
    ), "MVP gate should disclose diagnostic non-winner market coverage separately from winner blockers"
    simulation_gate = next(row for row in mvp_gate.requirements if row.requirement_id == "simulation_and_probabilities")
    assert any(
        "simulator_calibration=" in item for item in simulation_gate.evidence
    ), "MVP gate should disclose simulator calibration candidate status"
    assert any(
        row.requirement_id == "codex_normalized_intelligence" and row.blocks_formal_edge and not row.blocks_mvp_delivery
        for row in mvp_gate.requirements
    ), "MVP gate should expose unresolved source archive proof as a formal Codex blocker"
    assert (
        mvp_gate.summary["codex_source_candidate_ready_reports"] >= 1
    ), "MVP gate should summarize ready Codex source-candidate reports"
    assert (
        mvp_gate.summary["codex_preflight_passed_reports"] >= 1
    ), "MVP gate should summarize passed Codex research preflight reports"
    completion_audit = MVPCompletionAuditBuilder().build(year=2026, as_of="2026-07-01T00:00:00+00:00")
    assert completion_audit.mvp_complete, "completion audit should recognize the diagnostic MVP as complete"
    assert (
        completion_audit.status == "mvp_complete_formal_edge_not_ready"
    ), "completion audit should keep formal edge readiness separate from MVP completion"
    assert not completion_audit.formal_edge_ready, "completion audit must not promote diagnostic artifacts to formal edge"
    assert (
        completion_audit.summary["mvp_incomplete_count"] == 0
    ), "completion audit should expose zero incomplete MVP-required rows"
    assert any(
        row.requirement_id == "codex_factor_positive_help_diagnostics"
        and row.status == "diagnostic_achieved"
        and row.formal_edge_required
        for row in completion_audit.requirements
    ), "completion audit should separate diagnostic Codex impact from formal positive-lift proof"
    assert any(
        row.requirement_id == "formal_edge_boundary" and row.status == "formal_blocked"
        for row in completion_audit.requirements
    ), "completion audit should preserve the stable-edge boundary as blocked"
    with tempfile.TemporaryDirectory() as audit_directory:
        audit_paths = MVPCompletionAuditBuilder().write(
            2026,
            "2026-07-01T00:00:00+00:00",
            Path(audit_directory) / "mvp_completion_audit",
        )
        written_audit = json.loads(audit_paths["json"].read_text(encoding="utf-8"))
        assert (
            written_audit["status"] == "mvp_complete_formal_edge_not_ready"
        ), "completion audit JSON should be writable"
    with tempfile.TemporaryDirectory() as directory:
        intake_bundle = ReadinessIntakeExporter(PredictionPipeline(iterations=160)).write(
            year=2026,
            as_of="2026-06-30T00:00:00+00:00",
            output_dir=Path(directory),
        )
        assert intake_bundle.action_count >= 12, "readiness intake should export all blocker actions"
        assert (
            "market_snapshot_backfill_jsonl" in intake_bundle.files
        ), "readiness intake should create a market backfill JSONL queue"
        assert (
            "source_archive_proof_csv" in intake_bundle.files
        ), "readiness intake should create a source archive CSV queue"
        assert Path(intake_bundle.files["manifest"]).exists(), "readiness intake manifest should be written"
        assert Path(intake_bundle.files["actions_jsonl"]).read_text(encoding="utf-8").count("\n") >= 12
        verification = ReadinessIntakeVerifier(PredictionPipeline(iterations=160)).verify(
            year=2026,
            as_of="2026-06-30T00:00:00+00:00",
            bundle_root=Path(directory),
        )
        assert verification.status == "open_actions_remaining", "fresh intake should verify as still open"
        assert verification.open_action_count == intake_bundle.action_count, "fresh intake verification should match exported actions"
        assert verification.new_action_count == 0, "fresh intake verification should not find unqueued actions"
        market_actions = [
            json.loads(line)
            for line in Path(intake_bundle.files["market_snapshot_backfill_jsonl"]).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert any(
            action.get("blocker_codes") for action in market_actions
        ), "market intake actions should inherit machine-readable market readiness blocker codes"
        assert any(
            action.get("next_action_category") in {
                "find_same_season_winner_definition",
                "find_winner_market_definition",
                "backfill_winner_price_history",
            }
            for action in market_actions
        ), "market intake actions should inherit specific market action categories"
        assert any(
            action.get("minimum_missing_requirements") for action in market_actions
        ), "market intake actions should carry minimum missing market proof requirements"
        assert any(
            "search-backfill-polymarket-history" in " ".join(action["command_templates"])
            for action in market_actions
        ), "market intake actions should point at the integrated search/history backfill command"
        assert any(
            "--market-type driver_h2h" in " ".join(action["command_templates"])
            for action in market_actions
        ), "market intake actions should expose driver H2H as a supported diagnostic market backfill"
        assert any(
            "archive-reviewed-market-snapshot" in " ".join(action["command_templates"])
            for action in market_actions
        ), "market intake actions should point at the strict reviewed market archive command"
        assert not any(
            "<reviewed_gamma_payload.json>" in " ".join(action["command_templates"])
            or "python -m f1predict.cli backfill-polymarket-history" in " ".join(action["command_templates"])
            for action in market_actions
        ), "market intake actions should not require a separate reviewed Gamma payload placeholder"
        readme_text = Path(intake_bundle.files["readme"]).read_text(encoding="utf-8")
        assert (
            "search-backfill-polymarket-history" in readme_text
        ), "readiness intake README should document the integrated search/history backfill command"
        assert (
            "--market-type driver_h2h" in readme_text
        ), "readiness intake README should document driver H2H diagnostic market backfill"
        assert (
            "archive-reviewed-market-snapshot" in readme_text
        ), "readiness intake README should document the reviewed market archive command"
        source_actions = [
            json.loads(line)
            for line in Path(intake_bundle.files["source_archive_proof_jsonl"]).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert any(
            action.get("blocker_codes") for action in source_actions
        ), "source intake actions should inherit source replacement blocker codes"
        assert any(
            action.get("next_action_category") in {"find_cutoff_archive", "review_current_content_and_find_archive"}
            for action in source_actions
        ), "source intake actions should inherit replacement-source action categories"
        assert any(
            action.get("minimum_missing_requirements") for action in source_actions
        ), "source intake actions should carry minimum missing source proof requirements"

        class FakeMarketSearchClient:
            def search_markets(self, query: str, limit: int = 20, include_closed: bool = False):
                assert query, "readiness market scanner should issue concrete event search queries"
                assert include_closed, "historical market readiness scans should include closed markets"
                return {"markets": []}

        market_scan = ReadinessMarketScanner(
            client=FakeMarketSearchClient(),
            market_normalization_dir=Path(directory) / "market_normalization",
        ).scan(
            year=2026,
            as_of="2026-06-30T00:00:00+00:00",
            bundle_root=Path(directory),
            limit=2,
            include_closed=True,
        )
        assert market_scan.action_count >= 7, "market readiness scan should load market blocker actions"
        assert market_scan.event_count >= 7, "market readiness scan should dedupe blocker events"
        assert market_scan.status == "no_candidate_markets", "empty fake search should produce no-candidate status"
        assert market_scan.blocking_event_count >= 6, "market readiness should count blocking market events separately"
        assert market_scan.warning_only_event_count >= 1, "market readiness should separate warning-only market events"
        assert (
            market_scan.blocking_unresolved_event_count < market_scan.unresolved_event_count
        ), "warning-only rows should not inflate blocking unresolved market counts"
        assert market_scan.query_count >= market_scan.event_count, "market readiness scan should run event queries"
        first_market_row = market_scan.rows[0]
        assert first_market_row["blocks_formal_claim"], "blocking market rows should expose their formal-claim flag"
        assert first_market_row["blocking_action_count"] >= 1
        assert first_market_row["review_summary"], "market readiness rows should explain candidate review status"
        assert first_market_row["next_action"], "market readiness rows should expose the next blocker action"
        assert "issue_examples_json" in first_market_row, "market readiness rows should carry issue examples for review"
        assert (
            "same_time_winner_snapshot_missing" in json.loads(first_market_row["blocker_codes_json"])
        ), "blocking market rows should expose machine-readable snapshot blocker codes"
        assert first_market_row["next_action_category"], "market readiness rows should expose a machine-readable action category"
        assert (
            market_scan.blocker_code_counts.get("same_time_winner_snapshot_missing", 0) >= 6
        ), "market readiness reports should aggregate blocking market reason codes"
        assert market_scan.next_action_category_counts, "market readiness reports should aggregate action categories"
        attempted_row = ReadinessMarketScanner._row(
            "test_gp",
            {
                "event_name": "Test Grand Prix",
                "action_ids": ["test_gp:market_snapshot"],
                "categories": ["market_snapshot_required"],
                "required_by": ["2026-01-01T00:00:00+00:00"],
                "first_command": "python -m f1predict.cli search-backfill-polymarket-history --event test_gp",
            },
            search_row=None,
            backfill_report={
                "event_id": "test_gp",
                "market_type": "winner",
                "knowledge_cutoff": "2026-01-01T00:00:00+00:00",
                "unique_market_count": 11,
                "definition_count": 0,
                "snapshot_count": 0,
                "cutoff_valid_snapshot_count": 0,
                "after_cutoff_snapshot_count": 0,
                "output": "reports/market_normalization/test_gp_price_history.json",
                "issues": [{"code": "season_mismatch", "detail": "2025 market", "question": "Test"}],
            },
        )
        assert attempted_row["status"] == "backfill_attempted_no_winner_definitions"
        assert attempted_row["blocks_formal_claim"], "direct market rows should infer blocking status from categories"
        assert attempted_row["blocking_action_count"] >= 1
        assert attempted_row["backfill_attempted"], "market readiness rows should expose attempted backfills"
        assert attempted_row["backfill_unique_market_count"] == 11
        assert attempted_row["backfill_top_issue_code"] == "season_mismatch"
        assert "backfill_issue_counts_json" in attempted_row
        assert "backfill_issue_examples_json" in attempted_row
        assert "Integrated search/history backfill was attempted" in attempted_row["review_summary"]
        assert "mismatched-season" in attempted_row["review_summary"]
        assert (
            "archive-reviewed-market-snapshot" in attempted_row["next_action"]
        ), "market readiness next action should route reviewed manual sources through strict archive command"
        attempted_codes = json.loads(attempted_row["blocker_codes_json"])
        assert (
            "mismatched_season_markets_rejected" in attempted_codes
            and "same_season_winner_definition_missing" in attempted_codes
        ), "season-mismatch market backfills should expose precise formal blocker codes"
        attempted_missing = json.loads(attempted_row["minimum_missing_requirements_json"])
        assert any(
            "archive-reviewed-market-snapshot" in requirement for requirement in attempted_missing
        ), "market readiness missing requirements should name the reviewed market archive path"
        assert (
            attempted_row["next_action_category"] == "find_same_season_winner_definition"
        ), "season-mismatch market backfills should route to same-season winner definition search"
        assert json.loads(
            attempted_row["minimum_missing_requirements_json"]
        ), "blocking market rows should expose minimum missing requirements"

        class FakeAlternativeMarketSearchClient:
            def search_markets(self, query: str, limit: int = 20, include_closed: bool = False):
                if "Chinese" not in query:
                    return {"markets": []}
                return {
                    "markets": [
                        {
                            "id": "pm-china-double-podium",
                            "question": "Will McLaren double podium at the 2026 Chinese Grand Prix?",
                            "description": "This market will resolve Yes if both drivers for McLaren finish in the top 3 at the 2026 Chinese Grand Prix.",
                            "groupItemTitle": "McLaren",
                            "outcomes": "[\"Yes\", \"No\"]",
                            "outcomePrices": "[\"0.22\", \"0.78\"]",
                            "clobTokenIds": "[\"yes-token-double-podium\", \"no-token-double-podium\"]",
                            "active": True,
                            "closed": False,
                        }
                    ]
                }

        alternative_market_scan = ReadinessMarketScanner(
            client=FakeAlternativeMarketSearchClient(),
            market_normalization_dir=Path(directory) / "market_normalization",
        ).scan(
            year=2026,
            as_of="2026-06-30T00:00:00+00:00",
            bundle_root=Path(directory),
            limit=2,
            include_closed=True,
        )
        china_market_row = next(row for row in alternative_market_scan.rows if row["event_id"] == "chinese_gp")
        alternative_counts = json.loads(china_market_row["alternative_market_counts_json"])
        alternative_types = json.loads(china_market_row["alternative_market_types_json"])
        assert (
            china_market_row["status"] == "alternative_definitions_found"
        ), "supported non-winner same-season markets should be classified as alternative definitions"
        assert not china_market_row["blocks_formal_claim"], "Chinese replacement row should stay warning-only"
        assert china_market_row["warning_only"], "warning-only market rows should be explicit in the scan output"
        assert china_market_row["warning_action_count"] >= 1
        assert (
            alternative_counts["constructor_double_podium"] == 1
        ), "market readiness should classify constructor double-podium candidates"
        assert (
            alternative_types["constructor_double_podium"] == 1
        ), "market readiness should count supported constructor double-podium definitions"
        assert (
            "--market-type constructor_double_podium" in china_market_row["next_action"]
        ), "alternative definitions should point to the market-type-specific history backfill"
        assert (
            "diagnostic_non_winner_market_definitions_available" in json.loads(china_market_row["warning_codes_json"])
        ), "warning-only alternative markets should expose diagnostic warning codes"
        assert (
            china_market_row["next_action_category"] == "backfill_diagnostic_alternative_market"
        ), "warning-only alternative definitions should route to diagnostic market backfill"
    calibration = ReplayCalibrationBuilder(PredictionPipeline(iterations=160)).build(
        year=2026,
        as_of="2026-06-30T00:00:00+00:00",
    )
    assert calibration.status == "diagnostic_only", "calibration report should stay diagnostic"
    assert not calibration.formal_probability_claim_ready, "small replay calibration must not be marked formal-ready"
    assert calibration.scored_events >= 8, "calibration should score completed replay rows"
    assert calibration.summary["mean_winner_brier_score"] >= 0.0, "calibration should compute Brier score"
    assert calibration.summary["mean_actual_log_loss"] >= 0.0, "calibration should compute log loss"
    assert any(bin_row.count > 0 for bin_row in calibration.bins), "calibration should populate confidence bins"
    assert (
        "market_scored_subset_incomplete" in calibration.warnings
    ), "calibration should disclose incomplete market-scored subset"
    simulator_calibration = SimulatorCalibrationBuilder(PredictionPipeline(iterations=80)).build(
        year=2026,
        as_of="2026-06-30T00:00:00+00:00",
        iterations=80,
    )
    assert simulator_calibration.status == "diagnostic_only", "simulator calibration should stay diagnostic"
    assert (
        not simulator_calibration.formal_simulator_claim_ready
    ), "simulator calibration must not promote in-sample candidates"
    assert simulator_calibration.candidate_count >= 5, "simulator calibration should compare multiple parameter candidates"
    assert simulator_calibration.recommended_config_id, "simulator calibration should name a review candidate"
    assert (
        simulator_calibration.candidates[0].selected_for_review
    ), "top-ranked simulator candidate should be selected for review"
    assert (
        "candidate_selection_is_in_sample_no_holdout" in simulator_calibration.warnings
    ), "simulator calibration should disclose no-holdout selection risk"
    model_error_review = ModelErrorReviewBuilder(PredictionPipeline(iterations=160)).build(
        year=2026,
        as_of="2026-06-30T00:00:00+00:00",
    )
    assert model_error_review.status == "diagnostic_only", "model error review should stay diagnostic"
    assert not model_error_review.formal_model_claim_ready, "model error review must not be promoted to formal proof"
    assert model_error_review.reviewed_events >= 8, "model error review should cover replayed events"
    assert model_error_review.missed_events >= 1, "model error review should expose replay misses"
    assert model_error_review.issue_counts, "model error review should aggregate diagnosis codes"
    first_model_row = model_error_review.events[0]
    assert first_model_row.candidate_drivers, "model error review should include candidate driver component rows"
    assert (
        "race_score" in first_model_row.candidate_drivers[0]
    ), "candidate rows should expose model component scores"
    with tempfile.TemporaryDirectory() as directory:
        temp_reports = Path(directory)
        ModelErrorReviewBuilder(PredictionPipeline(iterations=80)).write(
            year=2026,
            as_of="2026-06-30T00:00:00+00:00",
            output_dir=temp_reports / "model_error_review",
        )
        improvement_with_model_review = ImprovementPlanBuilder(
            PredictionPipeline(iterations=80),
            reports_root=temp_reports,
        ).build(year=2026, as_of="2026-06-30T00:00:00+00:00")
        model_workstream = next(
            row for row in improvement_with_model_review.workstreams if row.workstream_id == "model_iteration"
        )
        assert (
            model_workstream.metrics["model_error_issue_counts"]
        ), "improvement plan should ingest model error review issue counts when present"
        assert any(
            "Model error review found" in item for item in model_workstream.current_evidence
        ), "improvement plan should surface model error review evidence"
    improvement = ImprovementPlanBuilder(PredictionPipeline(iterations=160)).build(
        year=2026,
        as_of="2026-06-30T00:00:00+00:00",
    )
    assert improvement.status == "inputs_required", "improvement plan should preserve formal input blockers"
    assert not improvement.formal_edge_ready, "improvement plan must not promote diagnostic replay to formal edge"
    assert (
        improvement.workstreams[0].workstream_id == "market_same_time_snapshots"
    ), "market snapshots should remain the top formal blocker"
    assert (
        improvement.blocking_workstream_count >= 3
    ), "improvement plan should include market, source, and freeze blockers"
    market_workstream = next(
        row for row in improvement.workstreams if row.workstream_id == "market_same_time_snapshots"
    )
    assert any(
        "search-backfill-polymarket-history" in command for command in market_workstream.command_templates
    ), "improvement plan market workstream should use the integrated search/history backfill command"
    assert any(
        "--market-type driver_h2h" in command for command in market_workstream.command_templates
    ), "improvement plan market workstream should expose driver H2H as a supported diagnostic market backfill"
    assert any(
        "archive-reviewed-market-snapshot" in command for command in market_workstream.command_templates
    ), "improvement plan market workstream should include the strict reviewed market ingress command"
    assert any(
        "archive-reviewed-market-snapshot" in item for item in market_workstream.acceptance_checks
    ), "improvement plan market acceptance should require reviewed inputs to use the strict archive path"
    assert "alternative_definition_count" in market_workstream.metrics
    assert "events_with_alternative_definitions" in market_workstream.metrics
    assert not any(
        "<reviewed_gamma_payload.json>" in command
        or "python -m f1predict.cli backfill-polymarket-history" in command
        or "archive-market-snapshot --event <event_id>" in command
        for command in market_workstream.command_templates
    ), "improvement plan should not point at the old manual market backfill/archive flow"
    with tempfile.TemporaryDirectory() as directory:
        temp_root = Path(directory)
        fastf1_root = temp_root / "raw"
        race_dir = fastf1_root / "fastf1" / "2026_Test_Grand_Prix_Race_results" / "2026-06-30"
        sprint_dir = fastf1_root / "fastf1" / "2026_Test_Grand_Prix_Sprint_results" / "2026-06-30"
        race_dir.mkdir(parents=True, exist_ok=True)
        sprint_dir.mkdir(parents=True, exist_ok=True)
        race_payload = {
            "year": 2026,
            "requested_session": "R",
            "resolved_event": {"EventName": "Test Grand Prix", "RoundNumber": 1},
            "session": {"name": "Race"},
            "results": [
                {
                    "Position": 1,
                    "DriverId": "russell",
                    "FullName": "George Russell",
                    "Points": 25,
                }
            ],
        }
        sprint_payload = {
            "year": 2026,
            "requested_session": "S",
            "resolved_event": {"EventName": "Test Grand Prix", "RoundNumber": 1},
            "session": {"name": "Sprint"},
            "results": [
                {
                    "Position": 1,
                    "DriverId": "antonelli",
                    "FullName": "Kimi Antonelli",
                    "Points": 8,
                }
            ],
        }
        race_path = race_dir / "race.json"
        sprint_path = sprint_dir / "sprint.json"
        race_path.write_text(json.dumps(race_payload, ensure_ascii=False), encoding="utf-8")
        sprint_path.write_text(json.dumps(sprint_payload, ensure_ascii=False), encoding="utf-8")
        (race_dir / "race.meta.json").write_text(
            json.dumps(
                {
                    "source": "fastf1",
                    "dataset": "2026_Test Grand Prix_Race_results",
                    "captured_at": "2026-06-30T08:00:00+00:00",
                    "params": {"year": 2026, "session_name": "Race"},
                    "data_path": str(race_path),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (sprint_dir / "sprint.meta.json").write_text(
            json.dumps(
                {
                    "source": "fastf1",
                    "dataset": "2026_Test Grand Prix_Sprint_results",
                    "captured_at": "2026-06-30T09:00:00+00:00",
                    "params": {"year": 2026, "session_name": "Sprint"},
                    "data_path": str(sprint_path),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result_repo = FastF1ResultRepository(fastf1_root)
        default_results = result_repo.latest_results_by_event(2026)
        assert (
            default_results["test"].session_name == "Race"
        ), "default FastF1 result lookup should only return Race sessions"
        assert (
            default_results["test"].winner_driver_id == "russell"
        ), "a newer Sprint snapshot must not override the Race result"
        sprint_results = result_repo.latest_session_results_by_event(2026, session_names={"sprint"})
        assert (
            sprint_results["test"].winner_driver_id == "antonelli"
        ), "Sprint results should remain available through explicit session filtering"

        polymarket_payload = [
            {
                "title": "Miami Grand Prix Winner",
                "slug": "2026-miami-grand-prix-winner",
                "markets": [
                    {
                        "id": "pm-miami-verstappen",
                        "question": "Will Max Verstappen win the 2026 Miami Grand Prix?",
                        "outcomes": "[\"Yes\", \"No\"]",
                        "outcomePrices": "[\"0.31\", \"0.69\"]",
                        "clobTokenIds": "[\"yes-token-verstappen\", \"no-token-verstappen\"]",
                        "active": True,
                        "closed": False,
                        "liquidityNum": "2400",
                        "spread": "0.02",
                    },
                    {
                        "id": "pm-miami-other",
                        "question": "Will another driver win the 2026 Miami Grand Prix?",
                        "outcomes": "[\"Yes\", \"No\"]",
                        "outcomePrices": "[\"0.07\", \"0.93\"]",
                        "active": True,
                        "closed": False,
                    },
                    {
                        "id": "pm-miami-old-season",
                        "question": "Will Max Verstappen win the 2024 Miami Grand Prix?",
                        "outcomes": "[\"Yes\", \"No\"]",
                        "outcomePrices": "[\"0.99\", \"0.01\"]",
                        "active": True,
                        "closed": False,
                    },
                ],
            }
        ]
        normalized_market = PolymarketGammaNormalizer(pipeline.data_source.load()).normalize_payload(
            polymarket_payload,
            event_id="miami_gp",
            captured_at="2026-05-02T12:00:00+00:00",
        )
        assert len(normalized_market.snapshots) == 1, "Polymarket normalizer should emit only unambiguous 2026 driver markets"
        assert len(normalized_market.definitions) == 1, "Polymarket normalizer should preserve CLOB token definitions"
        assert (
            normalized_market.snapshots[0].prices["verstappen"] == 0.31
        ), "Polymarket normalizer should read Yes probability for binary driver markets"
        assert any(
            issue.code == "unrecognized_driver" for issue in normalized_market.issues
        ), "Polymarket normalizer should flag ambiguous other-driver markets"
        assert any(
            issue.code == "season_mismatch" for issue in normalized_market.issues
        ), "Polymarket normalizer should reject same-event markets from the wrong season"
        duplicated_normalized_market = PolymarketGammaNormalizer(pipeline.data_source.load()).normalize_payload(
            polymarket_payload + polymarket_payload,
            event_id="miami_gp",
            captured_at="2026-05-02T12:00:00+00:00",
        )
        assert (
            len(duplicated_normalized_market.snapshots) == 1
        ), "Polymarket normalizer should dedupe repeated market snapshots"
        assert (
            len(duplicated_normalized_market.definitions) == 1
        ), "Polymarket normalizer should dedupe repeated token definitions"
        assert (
            sum(1 for issue in duplicated_normalized_market.issues if issue.code == "season_mismatch") == 1
        ), "Polymarket normalizer should dedupe repeated market issues"
        discovery_report = PolymarketDiscoveryAuditor(pipeline.data_source.load()).build(polymarket_payload)
        discovery_rows = {row.event_id: row for row in discovery_report.rows}
        assert (
            discovery_rows["miami_gp"].definition_count == 1
        ), "Polymarket discovery should expose per-event market definitions"
        assert (
            discovery_report.issue_counts.get("season_mismatch") == 1
        ), "Polymarket discovery should aggregate rejected market issues"

        constructor_double_podium_payload = [
            {
                "markets": [
                    {
                        "id": "pm-china-mclaren-double-podium",
                        "question": "Will McLaren double podium at the 2026 Chinese Grand Prix?",
                        "description": "This market resolves Yes if both participating drivers for McLaren finish in the top 3.",
                        "groupItemTitle": "McLaren",
                        "outcomes": "[\"Yes\", \"No\"]",
                        "outcomePrices": "[\"0.22\", \"0.78\"]",
                        "clobTokenIds": "[\"yes-token-mclaren-double\", \"no-token-mclaren-double\"]",
                        "active": True,
                        "closed": False,
                    },
                    {
                        "id": "pm-china-other-double-podium",
                        "question": "Will another team double podium at the 2026 Chinese Grand Prix?",
                        "description": "This market resolves Yes if both participating drivers for the listed team finish in the top 3.",
                        "groupItemTitle": "Other",
                        "outcomes": "[\"Yes\", \"No\"]",
                        "outcomePrices": "[\"0.04\", \"0.96\"]",
                        "active": True,
                        "closed": False,
                    },
                ]
            }
        ]
        normalized_constructor_market = PolymarketGammaNormalizer(pipeline.data_source.load()).normalize_payload(
            constructor_double_podium_payload,
            event_id="chinese_gp",
            captured_at="2026-03-14T12:00:00+00:00",
            market_type="constructor_double_podium",
        )
        assert (
            normalized_constructor_market.snapshots[0].prices["mclaren"] == 0.22
        ), "constructor double-podium markets should map Yes prices to team IDs"
        assert (
            normalized_constructor_market.definitions[0].outcome_id == "mclaren"
        ), "constructor double-podium definitions should preserve team outcome IDs"
        assert any(
            issue.code == "unrecognized_team" for issue in normalized_constructor_market.issues
        ), "constructor double-podium normalization should reject ambiguous other-team markets"

        driver_h2h_payload = [
            {
                "markets": [
                    {
                        "id": "pm-china-hamilton-russell-h2h",
                        "question": "2026 Chinese Grand Prix Head to Head: Hamilton vs Russell",
                        "outcomes": "[\"Lewis Hamilton\", \"George Russell\"]",
                        "outcomePrices": "[\"0.48\", \"0.52\"]",
                        "clobTokenIds": "[\"token-hamilton-h2h\", \"token-russell-h2h\"]",
                        "active": True,
                        "closed": False,
                    },
                    {
                        "id": "pm-china-verstappen-norris-ahead",
                        "question": "Will Max Verstappen finish ahead of Lando Norris at the 2026 Chinese Grand Prix?",
                        "outcomes": "[\"Yes\", \"No\"]",
                        "outcomePrices": "[\"0.57\", \"0.43\"]",
                        "clobTokenIds": "[\"token-verstappen-ahead\", \"token-norris-ahead-no\"]",
                        "active": True,
                        "closed": False,
                    },
                ]
            }
        ]
        normalized_driver_h2h = PolymarketGammaNormalizer(pipeline.data_source.load()).normalize_payload(
            driver_h2h_payload,
            event_id="chinese_gp",
            captured_at="2026-03-14T12:00:00+00:00",
            market_type=DRIVER_H2H,
        )
        hamilton_over_russell = driver_h2h_outcome_id("hamilton", "russell")
        russell_over_hamilton = driver_h2h_outcome_id("russell", "hamilton")
        verstappen_over_norris = driver_h2h_outcome_id("verstappen", "norris")
        h2h_prices = {
            outcome_id: price
            for snapshot in normalized_driver_h2h.snapshots
            for outcome_id, price in snapshot.prices.items()
        }
        assert (
            h2h_prices[hamilton_over_russell] == 0.48
            and h2h_prices[russell_over_hamilton] == 0.52
            and h2h_prices[verstappen_over_norris] == 0.57
        ), "driver H2H normalization should emit canonical driver_ahead_of_driver outcome IDs"
        assert any(
            definition.outcome_id == verstappen_over_norris
            for definition in normalized_driver_h2h.definitions
        ), "driver H2H definitions should preserve the Yes token for directed binary markets"

        class FakePolymarketSearchClient:
            def search_markets(self, query, limit=20, include_closed=False):
                if "Miami" not in query:
                    return []
                return [
                    {
                        "id": "pm-miami-verstappen",
                        "question": "Will Max Verstappen win the 2026 Miami Grand Prix?",
                        "outcomes": "[\"Yes\", \"No\"]",
                        "outcomePrices": "[\"0.31\", \"0.69\"]",
                        "clobTokenIds": "[\"yes-token-verstappen\", \"no-token-verstappen\"]",
                        "active": True,
                        "closed": False,
                    }
                ]

        season_search = PolymarketSeasonSearchAuditor(
            pipeline.data_source.load(),
            client=FakePolymarketSearchClient(),
        ).build(event_ids=["miami_gp"], limit=5)
        assert season_search.event_count == 1, "season search should support event filtering"
        assert season_search.events_with_definitions == 1, "season search should find query-discovered definitions"
        assert season_search.total_definitions == 1, "season search should dedupe repeated query results"

        class FakePolymarketNoMatchSearchClient:
            def search_markets(self, query, limit=20, include_closed=False):
                return [
                    {
                        "id": "pm-unrelated",
                        "question": "Will Team A win the 2026 championship?",
                        "outcomes": "[\"Yes\", \"No\"]",
                        "outcomePrices": "[\"0.42\", \"0.58\"]",
                        "clobTokenIds": "[\"yes-token-unrelated\", \"no-token-unrelated\"]",
                        "active": True,
                        "closed": False,
                    }
                ]

        no_match_search = PolymarketSeasonSearchAuditor(
            pipeline.data_source.load(),
            client=FakePolymarketNoMatchSearchClient(),
        ).build(event_ids=["miami_gp"], limit=5)
        assert (
            no_match_search.issue_counts.get("no_matching_event_alias") == 1
        ), "season search should expose when returned markets do not match the event alias"

        class FakePolymarketLiveClient:
            def search_markets(self, query, limit=20, include_closed=False):
                if "Miami" not in query:
                    return []
                return [
                    {
                        "id": "pm-miami-outright",
                        "question": "Who will win the 2026 Miami Grand Prix?",
                        "outcomes": "[\"Max Verstappen\", \"Kimi Antonelli\"]",
                        "outcomePrices": "[\"0.30\", \"0.25\"]",
                        "clobTokenIds": "[\"token-verstappen\", \"token-antonelli\"]",
                        "active": True,
                        "closed": False,
                        "liquidityNum": "5000",
                    }
                ]

            def order_book(self, token_id):
                if token_id == "token-verstappen":
                    return {
                        "bids": [{"price": "0.30", "size": "100"}],
                        "asks": [{"price": "0.36", "size": "120"}],
                        "last_trade_price": "0.35",
                        "timestamp": "2026-05-02T12:00:00+00:00",
                        "hash": "book-verstappen",
                    }
                if token_id == "token-antonelli":
                    return {
                        "bids": [{"price": "0.20", "size": "50"}],
                        "asks": [{"price": "0.45", "size": "60"}],
                        "last_trade_price": "0.31",
                        "timestamp": 1777723200,
                        "hash": "book-antonelli",
                    }
                raise AssertionError(f"unexpected token: {token_id}")

        live_snapshot = PolymarketLiveSnapshotter(
            pipeline.data_source.load(),
            client=FakePolymarketLiveClient(),
        ).capture_event(
            "miami_gp",
            captured_at="2026-05-02T12:00:00+00:00",
            limit=5,
        )
        assert live_snapshot.unique_market_count == 1, "live snapshotter should dedupe repeated search hits"
        assert len(live_snapshot.snapshots) == 1, "multi-outcome live markets should become one grouped snapshot"
        assert (
            live_snapshot.snapshots[0].prices["verstappen"] == 0.33
        ), "narrow order-book spreads should use the midpoint as displayed price"
        assert (
            live_snapshot.snapshots[0].prices["antonelli"] == 0.31
        ), "wide order-book spreads should use last trade as displayed price"
        live_quote_statuses = {quote.outcome_id: quote.status for quote in live_snapshot.quotes}
        assert live_quote_statuses["verstappen"] == "book_midpoint", "quote status should explain midpoint pricing"
        assert (
            live_quote_statuses["antonelli"] == "book_last_trade_wide_spread"
        ), "quote status should explain wide-spread last-trade pricing"

        class FakePolymarketClient:
            def price_history(self, token_id, start_ts=None, end_ts=None, interval=None, fidelity=None):
                assert token_id == "yes-token-verstappen", "backfiller should query the Yes token"
                return {
                    "history": [
                        {"t": "2026-05-01T12:00:00+00:00", "p": 0.29},
                        {"t": "2026-05-02T12:00:00+00:00", "p": 0.33},
                        {"t": "2026-05-04T12:00:00+00:00", "p": 0.90},
                    ]
                }

        backfilled_market = PolymarketPriceHistoryBackfiller(
            pipeline.data_source.load(),
            client=FakePolymarketClient(),
        ).backfill_payload(
            polymarket_payload,
            event_id="miami_gp",
            knowledge_cutoff="2026-05-03T00:00:00+00:00",
        )
        assert len(backfilled_market.snapshots) == 1, "price-history backfill should emit one cutoff snapshot"
        assert (
            backfilled_market.snapshots[0].prices["verstappen"] == 0.33
        ), "price-history backfill should choose the latest price before the cutoff"
        assert (
            backfilled_market.snapshots[0].captured_at == "2026-05-02T12:00:00+00:00"
        ), "price-history backfill should preserve the source price timestamp"

        class FakeSearchBackfillClient:
            def __init__(self):
                self.queries = []

            def search_markets(self, query, limit=20, include_closed=False):
                self.queries.append(query)
                assert include_closed, "historical search backfill should pass through include_closed"
                if "Chinese" not in query or "double podium" not in query.lower():
                    return []
                return [
                    {
                        "id": "pm-china-mclaren-double-search",
                        "question": "Will McLaren double podium at the 2026 Chinese Grand Prix?",
                        "description": "This market resolves Yes if both McLaren drivers finish in the top 3.",
                        "groupItemTitle": "McLaren",
                        "outcomes": "[\"Yes\", \"No\"]",
                        "outcomePrices": "[\"0.22\", \"0.78\"]",
                        "clobTokenIds": "[\"yes-token-double-podium-search\", \"no-token-double-podium-search\"]",
                        "active": False,
                        "closed": True,
                    }
                ]

            def price_history(self, token_id, start_ts=None, end_ts=None, interval=None, fidelity=None):
                assert token_id == "yes-token-double-podium-search", "search backfill should query the Yes token"
                return {
                    "history": [
                        {"t": "2026-03-14T12:00:00+00:00", "p": 0.22},
                        {"t": "2026-03-16T12:00:00+00:00", "p": 0.80},
                    ]
                }

        search_backfill_client = FakeSearchBackfillClient()
        search_backfilled_market = PolymarketSearchHistoryBackfiller(
            pipeline.data_source.load(),
            client=search_backfill_client,
        ).backfill_event(
            event_id="chinese_gp",
            knowledge_cutoff="2026-03-15T00:00:00+00:00",
            market_type="constructor_double_podium",
            include_closed=True,
            limit=5,
        )
        assert any(
            "double podium" in query.lower() for query in search_backfill_client.queries
        ), "constructor double-podium search backfill should generate market-type-specific queries"
        assert (
            search_backfilled_market.unique_market_count == 1
        ), "search backfill should dedupe discovered Gamma markets"
        assert len(search_backfilled_market.snapshots) == 1, "search backfill should emit cutoff snapshots"
        assert (
            search_backfilled_market.snapshots[0].prices["mclaren"] == 0.22
        ), "search backfill should use the latest price before the cutoff"

        class FakeH2HSearchBackfillClient:
            def __init__(self):
                self.queries = []

            def search_markets(self, query, limit=20, include_closed=False):
                self.queries.append(query)
                if "Chinese" not in query or ("h2h" not in query.lower() and "head to head" not in query.lower()):
                    return []
                return [
                    {
                        "id": "pm-china-hamilton-russell-h2h-search",
                        "question": "2026 Chinese Grand Prix Head to Head: Hamilton vs Russell",
                        "outcomes": "[\"Lewis Hamilton\", \"George Russell\"]",
                        "outcomePrices": "[\"0.48\", \"0.52\"]",
                        "clobTokenIds": "[\"token-hamilton-h2h-search\", \"token-russell-h2h-search\"]",
                        "active": False,
                        "closed": True,
                    }
                ]

            def price_history(self, token_id, start_ts=None, end_ts=None, interval=None, fidelity=None):
                return {
                    "history": [
                        {"t": "2026-03-14T12:00:00+00:00", "p": 0.48 if "hamilton" in token_id else 0.52},
                        {"t": "2026-03-16T12:00:00+00:00", "p": 0.80},
                    ]
                }

        h2h_search_client = FakeH2HSearchBackfillClient()
        h2h_search_backfill = PolymarketSearchHistoryBackfiller(
            pipeline.data_source.load(),
            client=h2h_search_client,
        ).backfill_event(
            event_id="chinese_gp",
            knowledge_cutoff="2026-03-15T00:00:00+00:00",
            market_type=DRIVER_H2H,
            include_closed=True,
            limit=5,
        )
        assert any(
            "h2h" in query.lower() or "head to head" in query.lower()
            for query in h2h_search_client.queries
        ), "driver H2H search backfill should generate matchup-specific queries"
        assert len(h2h_search_backfill.snapshots) == 2, "driver H2H backfill should emit both matchup sides"
        assert {
            driver_h2h_outcome_id("hamilton", "russell"),
            driver_h2h_outcome_id("russell", "hamilton"),
        } == {
            next(iter(snapshot.prices))
            for snapshot in h2h_search_backfill.snapshots
        }, "driver H2H backfill snapshots should use canonical directional outcome IDs"

        market_store = MarketSnapshotStore(temp_root / "market_snapshots")
        miami_market_path = market_store.write_event_snapshots(
            "miami_gp",
            [
                MarketSnapshot(
                    market_id="smoke_miami_gp_winner",
                    event_id="miami_gp",
                    market_type="winner",
                    captured_at="2026-05-02T12:00:00+00:00",
                    prices={"antonelli": 0.27, "verstappen": 0.25},
                    liquidity=1200.0,
                    spread_estimate=0.02,
                ),
                MarketSnapshot(
                    market_id="smoke_miami_gp_winner",
                    event_id="miami_gp",
                    market_type="winner",
                    captured_at="2026-05-02T12:00:00+00:00",
                    prices={"antonelli": 0.27, "verstappen": 0.25},
                    liquidity=1200.0,
                    spread_estimate=0.02,
                ),
                MarketSnapshot(
                    market_id="smoke_miami_gp_late_winner",
                    event_id="miami_gp",
                    market_type="winner",
                    captured_at="2026-05-04T12:00:00+00:00",
                    prices={"antonelli": 0.99},
                    liquidity=500.0,
                    spread_estimate=0.02,
                ),
            ],
            params={"source": "smoke"},
        )
        market_store.write_event_snapshots(
            "chinese_gp",
            [
                MarketSnapshot(
                    market_id="smoke_chinese_gp_mclaren_double_podium",
                    event_id="chinese_gp",
                    market_type="constructor_double_podium",
                    captured_at="2026-03-14T12:00:00+00:00",
                    prices={"mclaren": 0.22},
                    liquidity=900.0,
                    spread_estimate=0.03,
                )
            ],
            params={"source": "smoke"},
        )
        market_store.write_event_snapshots(
            "chinese_gp",
            [
                MarketSnapshot(
                    market_id="smoke_chinese_gp_hamilton_russell_h2h",
                    event_id="chinese_gp",
                    market_type=DRIVER_H2H,
                    captured_at="2026-03-14T12:00:00+00:00",
                    prices={
                        driver_h2h_outcome_id("hamilton", "russell"): 0.48,
                        driver_h2h_outcome_id("russell", "hamilton"): 0.52,
                    },
                    liquidity=1100.0,
                    spread_estimate=0.03,
                )
            ],
            params={"source": "smoke"},
        )
        stored_markets = market_store.load_event("miami_gp")
        cutoff_dt = parse_dt("2026-05-03T00:00:00+00:00")
        assert len(market_store.load_file(miami_market_path)) == 2, "market snapshot store should dedupe duplicate writes"
        assert len(stored_markets) == 2, "market snapshot store should load archived snapshots"
        assert (
            len(event_market_snapshots(stored_markets, "miami_gp", cutoff_dt, market_type="winner")) == 1
        ), "only cutoff-valid market snapshots should enter prediction"
        assert (
            after_cutoff_market_count(stored_markets, "miami_gp", cutoff_dt, market_type="winner") == 1
        ), "after-cutoff archived markets should remain diagnostic"
        reviewed_packet_path = temp_root / "reviewed_miami_market.json"
        reviewed_packet_path.write_text(
            json.dumps(
                {
                    "event_id": "miami_gp",
                    "market_id": "reviewed_miami_gp_winner",
                    "market_type": "winner",
                    "captured_at": "2026-05-02T12:00:00+00:00",
                    "prices": {"antonelli": 0.27, "verstappen": 0.25, "hamilton": 0.14},
                    "liquidity": 1250.0,
                    "spread_estimate": 0.02,
                    "review": {
                        "status": "accepted",
                        "reviewed_by": "codex-smoke",
                        "reviewed_at": "2026-05-02T12:05:00+00:00",
                        "source_url": "https://polymarket.example/miami-2026-winner",
                        "source_captured_at": "2026-05-02T12:01:00+00:00",
                        "notes": "Smoke-reviewed same-season winner market with model driver IDs.",
                        "resolution_rule": "Resolves to the official 2026 Miami Grand Prix race winner.",
                        "outcome_mapping": {
                            "antonelli": "Kimi Antonelli",
                            "verstappen": "Max Verstappen",
                            "hamilton": "Lewis Hamilton",
                        },
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        reviewed_store = MarketSnapshotStore(temp_root / "reviewed_market_snapshots")
        reviewed_result = ReviewedMarketSnapshotArchiver(
            season=PredictionPipeline(iterations=1).data_source.load(),
            store=reviewed_store,
        ).archive_packet(
            "miami_gp",
            reviewed_packet_path,
            knowledge_cutoff="2026-05-03T00:00:00+00:00",
            require_cutoff_valid=True,
        )
        assert reviewed_result.cutoff_valid_snapshot_count == 1, "reviewed market packets should archive cutoff-valid snapshots"
        assert reviewed_result.archived_path, "reviewed market packet archiver should write through MarketSnapshotStore"
        assert (
            reviewed_store.load_event("miami_gp")[0].market_id == "reviewed_miami_gp_winner"
        ), "reviewed market packets should enter the same normalized market store"

        reviewed_h2h_packet_path = temp_root / "reviewed_chinese_h2h_market.json"
        reviewed_h2h_packet_path.write_text(
            json.dumps(
                {
                    "event_id": "chinese_gp",
                    "market_id": "reviewed_chinese_gp_hamilton_russell_h2h",
                    "market_type": DRIVER_H2H,
                    "captured_at": "2026-03-14T12:00:00+00:00",
                    "prices": {driver_h2h_outcome_id("hamilton", "russell"): 0.48},
                    "liquidity": 800.0,
                    "spread_estimate": 0.03,
                    "review": {
                        "status": "accepted",
                        "reviewed_by": "codex-smoke",
                        "reviewed_at": "2026-03-14T12:05:00+00:00",
                        "source_url": "https://polymarket.example/china-2026-h2h",
                        "source_captured_at": "2026-03-14T12:01:00+00:00",
                        "notes": "Smoke-reviewed driver H2H market mapped to canonical directional outcome ID.",
                        "resolution_rule": "Resolves if Hamilton is classified ahead of Russell.",
                        "outcome_mapping": {
                            driver_h2h_outcome_id("hamilton", "russell"): "Hamilton",
                        },
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        reviewed_h2h_result = ReviewedMarketSnapshotArchiver(
            season=PredictionPipeline(iterations=1).data_source.load(),
            store=reviewed_store,
        ).archive_packet(
            "chinese_gp",
            reviewed_h2h_packet_path,
            knowledge_cutoff="2026-03-15T00:00:00+00:00",
            require_cutoff_valid=True,
        )
        assert reviewed_h2h_result.market_type == DRIVER_H2H, "reviewed market ingress should accept driver H2H packets"

        bad_reviewed_packet = json.loads(reviewed_packet_path.read_text(encoding="utf-8"))
        bad_reviewed_packet["prices"] = {"unknown_driver": 0.4}
        bad_reviewed_packet["review"]["outcome_mapping"] = {"unknown_driver": "Unknown Driver"}
        bad_reviewed_packet_path = temp_root / "bad_reviewed_miami_market.json"
        bad_reviewed_packet_path.write_text(
            json.dumps(bad_reviewed_packet, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            ReviewedMarketSnapshotArchiver(
                season=PredictionPipeline(iterations=1).data_source.load(),
                store=MarketSnapshotStore(temp_root / "bad_reviewed_market_snapshots"),
            ).archive_packet(
                "miami_gp",
                bad_reviewed_packet_path,
                knowledge_cutoff="2026-05-03T00:00:00+00:00",
                require_cutoff_valid=True,
            )
            raise AssertionError("reviewed winner markets must reject unknown driver outcome IDs")
        except ReviewedMarketSnapshotValidationError:
            pass

        late_reviewed_packet = json.loads(reviewed_packet_path.read_text(encoding="utf-8"))
        late_reviewed_packet["captured_at"] = "2026-05-04T12:00:00+00:00"
        late_reviewed_packet_path = temp_root / "late_reviewed_miami_market.json"
        late_reviewed_packet_path.write_text(
            json.dumps(late_reviewed_packet, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            ReviewedMarketSnapshotArchiver(
                season=PredictionPipeline(iterations=1).data_source.load(),
                store=MarketSnapshotStore(temp_root / "late_reviewed_market_snapshots"),
            ).archive_packet(
                "miami_gp",
                late_reviewed_packet_path,
                knowledge_cutoff="2026-05-03T00:00:00+00:00",
                require_cutoff_valid=True,
            )
            raise AssertionError("reviewed market packets must not satisfy cutoff-valid backfill with late prices")
        except ReviewedMarketSnapshotValidationError:
            pass
        market_pipeline = PredictionPipeline(
            data_source=CalendarAugmentedDataSource(market_store=market_store),
            iterations=80,
        )
        market_report = market_pipeline.predict_event(
            "miami_gp",
            knowledge_cutoff="2026-05-03T00:00:00+00:00",
        )
        assert market_report.market_edges, "archived market snapshots should enter edge comparison"
        market_packet = PredictionPacketBuilder(market_pipeline).build(
            "miami_gp",
            knowledge_cutoff="2026-05-03T00:00:00+00:00",
            iterations=60,
        )
        assert (
            market_packet.market_context["usable_snapshot_count"] == 1
        ), "prediction packet should preserve injected pipeline data sources when changing iterations"
        top_edge = market_report.market_edges[0]
        assert (
            top_edge.conservative_model_probability is not None
        ), "market edge comparison should expose conservative calibrated probabilities"
        assert (
            top_edge.conservative_edge_after_cost is not None
        ), "market edge comparison should expose conservative edge after costs"
        assert (
            "diagnostic_conservative_calibration" in top_edge.risk_flags
        ), "market edge comparison should label diagnostic calibration risk"
        assert (
            market_report.ai_judgement["market_snapshot_count"] == 1
        ), "late archived markets must not count as usable snapshots"
        constructor_market_report = market_pipeline.predict_event(
            "chinese_gp",
            knowledge_cutoff="2026-03-15T00:00:00+00:00",
        )
        constructor_edges = [
            edge for edge in constructor_market_report.market_edges
            if edge.market_type == "constructor_double_podium"
        ]
        assert constructor_edges, "constructor double-podium snapshots should enter market edge comparison"
        assert (
            constructor_edges[0].outcome_id == "mclaren"
        ), "constructor double-podium edge outcomes should use team IDs"
        assert all(
            edge.recommendation == "no_trade"
            for edge in constructor_edges
            if edge.edge_after_cost < 0.0
        ), "single-outcome constructor markets must not become paper trades through calibration shrinkage"
        assert all(
            "non_winner_market_diagnostic_only" in edge.risk_flags
            for edge in constructor_edges
        ), "non-winner market comparisons should be explicitly diagnostic"
        assert (
            constructor_market_report.ai_judgement["market_snapshot_counts"]["constructor_double_podium"] == 1
        ), "AI judgement should summarize non-winner market snapshot types separately"
        h2h_edges = [
            edge for edge in constructor_market_report.market_edges
            if edge.market_type == DRIVER_H2H
        ]
        assert h2h_edges, "driver H2H snapshots should enter market edge comparison"
        assert {
            driver_h2h_outcome_id("hamilton", "russell"),
            driver_h2h_outcome_id("russell", "hamilton"),
        }.issubset({edge.outcome_id for edge in h2h_edges}), "driver H2H edge outcomes should stay directional"
        assert all(
            "non_winner_market_diagnostic_only" in edge.risk_flags
            for edge in h2h_edges
        ), "driver H2H market comparisons should remain diagnostic-only"
        assert (
            constructor_market_report.ai_judgement["market_snapshot_counts"][DRIVER_H2H] == 1
        ), "AI judgement should summarize driver H2H market snapshot types separately"
        research_plan = CodexResearchPlanBuilder().build(
            "miami_gp",
            knowledge_cutoff="2026-05-03T00:00:00+00:00",
        )
        assert research_plan.status, "Codex research plan should expose an intake status"
        assert (
            len(research_plan.source_tasks) >= 5
        ), "Codex research plan should enumerate source-specific research tasks"
        assert any(
            task.source_class == "weather" for task in research_plan.source_tasks
        ), "Codex research plan should include weather research tasks"
        assert any(
            task.source_class == "market" for task in research_plan.source_tasks
        ), "Codex research plan should include market-rule research tasks"
        assert (
            "race_pace" in research_plan.metric_guidance
        ), "Codex research plan should map unstructured claims to model metrics"
        assert (
            "energy_recovery" in research_plan.metric_guidance
            and "upgrade_effect" in research_plan.metric_guidance
        ), "Codex research plan should expose technical mechanism metrics for simulator inputs"
        assert any(
            band.band == "material" for band in research_plan.impact_bands
        ), "Codex research plan should define bounded impact bands"
        assert any(
            "Market prices must enter through MarketSnapshot" in gate
            for gate in research_plan.quality_gates
        ), "Codex research plan should keep market prices outside LLM claims"
        assert any(
            "preflight-research-packet" in step for step in research_plan.tool_workflow
        ), "Codex research plan should require packet preflight before archive"
        assert any(
            "codex-source-candidates" in step for step in research_plan.tool_workflow
        ), "Codex research plan should require source candidate auditing before claims"
        assert (
            "codex-source-candidates" in research_plan.output_contract["source_candidate_command"]
        ), "Codex research plan output contract should expose source candidate audit command"
        assert (
            "preflight-research-packet" in research_plan.output_contract["preflight_command"]
        ), "Codex research plan output contract should expose preflight command"
        assert (
            research_plan.output_contract["preflight_report_json"].endswith(f"{research_plan.event_id}.json")
        ), "Codex research plan should expose preflight JSON report path"
        written_plan = CodexResearchPlanBuilder.write(research_plan, output_dir=temp_root)
        assert written_plan["json"].exists(), "Codex research plan JSON should be written"
        assert written_plan["markdown"].exists(), "Codex research plan Markdown should be written"
        assert (
            "preflight_command" in written_plan["markdown"].read_text(encoding="utf-8")
        ), "Codex research plan Markdown should include the preflight command"
        paths = CodexResearchWorkspaceBuilder().write_event_workspace("miami_gp", output_dir=temp_root)
        assert len(paths) == 8, "research workspace should include task, plan, candidate/template files, source log, and draft JSONL"
        assert (temp_root / "miami_gp" / "codex_research_plan.json").exists(), "workspace should include Codex research plan JSON"
        assert (temp_root / "miami_gp" / "codex_research_plan.md").exists(), "workspace should include Codex research plan Markdown"
        assert (temp_root / "miami_gp" / "source_candidates.json").exists(), "workspace should include source candidate template"
        assert (temp_root / "miami_gp" / "research_packet_template.json").exists(), "batch research packet template should be written"
        task_text = (temp_root / "miami_gp" / "research_task.md").read_text(encoding="utf-8")
        assert (
            "preflight-research-packet" in task_text
        ), "research workspace task should require preflight before batch archive"
        assert (
            "codex-source-candidates" in task_text
        ), "research workspace task should require Codex source candidate auditing"
        candidate_report = CodexSourceCandidateBuilder().build(
            "miami_gp",
            knowledge_cutoff="2026-05-03T00:00:00+00:00",
            candidates=[
                {
                    "candidate_id": "miami_gp-source-ready-001",
                    "task_id": "miami_gp:team-updates-track-fit",
                    "query": "Miami Grand Prix 2026 Mercedes ERS upgrade",
                    "source": "Team source smoke",
                    "source_class": "team_or_driver",
                    "url": "https://example.com/miami-mercedes-ers",
                    "title": "Miami Grand Prix Mercedes ERS preview",
                    "snippet": "Mercedes says ERS deployment and energy recovery are improved for the Miami Grand Prix.",
                    "published_at": "2026-05-02T10:00:00+00:00",
                    "observed_at": "2026-05-02T10:15:00+00:00",
                    "captured_by": "codex_web_search",
                    "model_metrics": ["energy_recovery"],
                    "target_hints": ["mercedes"],
                },
                {
                    "candidate_id": "miami_gp-source-late-001",
                    "task_id": "miami_gp:team-updates-track-fit",
                    "query": "Miami Grand Prix 2026 Red Bull upgrade",
                    "source": "Late media smoke",
                    "source_class": "media",
                    "url": "https://example.com/miami-red-bull-late",
                    "title": "Miami Grand Prix Red Bull upgrade",
                    "snippet": "Red Bull upgrade analysis after the cutoff.",
                    "published_at": "2026-05-04T10:00:00+00:00",
                    "observed_at": "2026-05-04T10:15:00+00:00",
                    "captured_by": "codex_web_search",
                    "model_metrics": ["upgrade_effect"],
                    "target_hints": ["red_bull"],
                },
            ],
        )
        assert candidate_report.candidate_count == 2, "source candidate report should count Codex search candidates"
        assert (
            candidate_report.review_ready_count == 1
        ), "within-cutoff relevant source candidates should be ready for claim review"
        assert (
            candidate_report.blocked_count == 1
        ), "after-cutoff candidates should block before claim drafting"
        assert (
            candidate_report.status_counts.get("candidate_blocked") == 1
        ), "candidate report should expose blocked source candidates"
        assert (
            candidate_report.input_contract["path"].endswith("miami_gp/source_candidates.json")
        ), "candidate report should expose the candidate input contract"
        ready_candidate = next(row for row in candidate_report.rows if row.candidate_id == "miami_gp-source-ready-001")
        assert (
            ready_candidate.route_preview[0]["route"] == "track_contextual_pace"
        ), "source candidate report should preview simulator route for technical metrics"
        assert (
            ready_candidate.route_preview[0]["context_multiplier"]
            == round(technical_context_multiplier("energy_recovery", "street"), 4)
        ), "source candidate route preview should expose track-context multiplier before claim drafting"
        assert (
            ready_candidate.route_preview[0]["track_demand_component"] == "ers_demand"
            and ready_candidate.route_preview[0]["track_demand_value"] == track_demand_profile("street").ers_demand
        ), "source candidate route preview should expose track-demand component before claim drafting"
        assert any(
            band["band"] == "material" for band in ready_candidate.impact_band_guidance
        ), "source candidate report should carry impact-band guidance without selecting a magnitude"
        candidate_json = temp_root / "miami_gp_candidates.json"
        candidate_md = temp_root / "miami_gp_candidates.md"
        written_candidates = CodexSourceCandidateBuilder.write(
            candidate_report,
            json_output=candidate_json,
            markdown_output=candidate_md,
        )
        assert candidate_json.exists() and candidate_md.exists(), "source candidate reports should be writable"
        assert "json_output" in written_candidates and "markdown_output" in written_candidates
        mismatch_candidate_report = CodexSourceCandidateBuilder().build(
            "miami_gp",
            knowledge_cutoff="2026-05-03T00:00:00+00:00",
            candidates=[
                {
                    "candidate_id": "wrong-event-source-001",
                    "event_id": "british_gp",
                    "task_id": "miami_gp:team-updates-track-fit",
                    "query": "Miami Grand Prix Mercedes ERS",
                    "source": "Wrong event smoke",
                    "source_class": "team_or_driver",
                    "url": "https://example.com/wrong-event",
                    "title": "Miami Grand Prix Mercedes ERS",
                    "snippet": "Mercedes discusses ERS deployment for the Miami Grand Prix.",
                    "published_at": "2026-05-02T10:00:00+00:00",
                    "observed_at": "2026-05-02T10:15:00+00:00",
                    "captured_by": "codex_web_search",
                    "model_metrics": ["energy_recovery"],
                    "target_hints": ["mercedes"],
                }
            ],
        )
        assert (
            mismatch_candidate_report.blocked_count == 1
        ), "source candidate report should block candidates whose event_id does not match the requested event"
        assert (
            "event_id_mismatch" in mismatch_candidate_report.rows[0].risk_flags
        ), "event-id mismatches should be explicit so cross-event Codex leakage cannot enter claim drafting"
        draft_path = temp_root / "miami_gp" / "draft_evidence.jsonl"
        draft_claim = {
            "claim_id": "miami_gp-smoke-001",
            "event_id": "miami_gp",
            "source": "smoke fixture",
            "source_url": "test://source",
            "published_at": "2026-05-02T12:00:00Z",
            "observed_at": "2026-05-02T12:00:00Z",
            "target_type": "team",
            "target_id": "mercedes",
            "claim_type": "smoke",
            "metric": "race_pace",
            "direction": "neutral",
            "magnitude": 0.0,
            "confidence": 0.1,
            "uncertainty": 0.9,
            "evidence_text": "Smoke-test placeholder claim.",
            "reasoning": "Used only to verify packet validation and archive plumbing.",
            "review_required": True,
        }
        draft_path.write_text(json.dumps(draft_claim, ensure_ascii=False) + "\n", encoding="utf-8")
        claims = CodexEvidenceProvider().validate_event_file("miami_gp", draft_path)
        source_result = SourceSnapshotter(raw_store=RawSnapshotStore(temp_root / "raw"), research_root=temp_root).snapshot_url(
            event_id="miami_gp",
            url="test://source",
            source="smoke source",
            source_class="media",
            published_at="2026-05-02T10:00:00Z",
            observed_at="2026-05-02T11:00:00Z",
            knowledge_cutoff="2026-05-03T00:00:00+00:00",
            used_in_claim_ids=[draft_claim["claim_id"]],
            content_override="<html><title>Smoke Source</title><body>ok</body></html>",
        )
        assert source_result.title == "Smoke Source", "source snapshot should extract HTML title"
        assert source_result.cutoff_status == "within_cutoff", "source snapshot should enforce cutoff metadata"
        source_audit = SourceLogAuditor().audit_claims(
            claims,
            temp_root / "miami_gp" / "source_log.json",
            knowledge_cutoff="2026-05-03T00:00:00+00:00",
        )
        assert source_audit.can_archive, "source audit should allow linked within-cutoff evidence"
        assert any(
            finding.code == "snapshot_captured_after_cutoff" for finding in source_audit.findings
        ), "retrospective source snapshots should be flagged as warnings"
        archived = EvidencePacketStore(temp_root / "evidence").write_event_packet("miami_gp", claims, params={"source_audit": source_audit.to_dict()})
        loaded = CodexEvidenceProvider(evidence_dir=temp_root / "empty_seed", packet_root=temp_root / "evidence").load_event_evidence("miami_gp")
        assert archived.exists(), "evidence packet should be archived"
        assert len(loaded) == 1, "archived evidence should be loadable"
        source_log_path = temp_root / "miami_gp" / "source_log.json"
        source_log = json.loads(source_log_path.read_text(encoding="utf-8"))
        source_log["sources"][0]["observed_at"] = "2999-01-01T00:00:00+00:00"
        source_log_path.write_text(json.dumps(source_log, ensure_ascii=False, indent=2), encoding="utf-8")
        rejected_audit = SourceLogAuditor().audit_claims(
            claims,
            source_log_path,
            knowledge_cutoff="2026-05-03T00:00:00+00:00",
        )
        assert not rejected_audit.can_archive, "source audit should reject timestamps after snapshot capture"
        assert any(
            finding.code == "source_observed_after_snapshot" for finding in rejected_audit.findings
        ), "source audit should report observed_at after snapshot capture"
        archive_root = temp_root / "archive_proof_research"
        archived_claim = dict(draft_claim)
        archived_claim.update(
            {
                "claim_id": "miami_gp-archive-proof-001",
                "source_url": "test://archived-source",
                "published_at": "2026-05-02T08:00:00Z",
                "observed_at": "2026-05-02T08:30:00Z",
            }
        )
        archived_draft_path = archive_root / "miami_gp" / "draft_evidence.jsonl"
        archived_draft_path.parent.mkdir(parents=True, exist_ok=True)
        archived_draft_path.write_text(json.dumps(archived_claim, ensure_ascii=False) + "\n", encoding="utf-8")
        archived_claims = CodexEvidenceProvider().validate_event_file("miami_gp", archived_draft_path)
        SourceSnapshotter(
            raw_store=RawSnapshotStore(temp_root / "archive_proof_raw"),
            research_root=archive_root,
        ).snapshot_url(
            event_id="miami_gp",
            url="test://archived-source",
            source="smoke archived source",
            source_class="media",
            published_at="2026-05-02T08:00:00Z",
            observed_at="2026-05-02T08:30:00Z",
            knowledge_cutoff="2026-05-03T00:00:00+00:00",
            used_in_claim_ids=[archived_claim["claim_id"]],
            content_override="<html><title>Archived Smoke Source</title><body>ok</body></html>",
            historical_archive={
                "archive_url": "https://web.archive.org/web/20260502090000/test://archived-source",
                "archived_at": "2026-05-02T09:00:00+00:00",
                "original_url": "test://archived-source",
                "verified_at": "2026-06-30T00:00:00+00:00",
                "verification_method": "manual_review",
                "notes": "Smoke fixture for cutoff-valid archive proof.",
            },
        )
        archive_audit = SourceLogAuditor().audit_claims(
            archived_claims,
            archive_root / "miami_gp" / "source_log.json",
            knowledge_cutoff="2026-05-03T00:00:00+00:00",
        )
        assert archive_audit.can_archive, "valid historical archive proof should not block source audit"
        assert any(
            finding.code == "historical_archive_supports_cutoff" for finding in archive_audit.findings
        ), "audit should expose when a historical archive makes a late local snapshot usable"
        assert not any(
            finding.code == "snapshot_captured_after_cutoff" for finding in archive_audit.findings
        ), "archive-backed sources should not count as retrospective source snapshots"
        archive_coverage = EvidenceCoverageAuditor(research_root=archive_root).build(as_of="2026-06-30T00:00:00+00:00")
        archive_miami_row = next(row for row in archive_coverage.rows if row.event_id == "miami_gp")
        assert archive_miami_row.source_snapshot_count == 1, "coverage should count archive-backed source snapshots"
        assert (
            archive_miami_row.archive_backed_source_snapshot_count == 1
        ), "coverage should expose archive-backed source snapshots"
        assert (
            archive_miami_row.archive_backed_source_details
        ), "coverage should expose URL-level archive-backed source details"
        assert (
            archive_miami_row.archive_backed_source_details[0]["archive_status"] == "archive_backed"
        ), "archive-backed details should identify historical archive proof"
        assert (
            archive_miami_row.retrospective_source_snapshot_count == 0
        ), "coverage should not mark archive-backed source snapshots as retrospective"
        assert (
            archive_coverage.events_with_archive_backed_source_snapshots >= 1
        ), "coverage summary should expose events with archive-backed source snapshots"

        early_archive_root = temp_root / "early_archive_research"
        early_archive_claim = dict(archived_claim)
        early_archive_claim["claim_id"] = "miami_gp-early-archive-proof-001"
        early_archive_claim["source_url"] = "test://early-archived-source"
        early_archive_draft_path = early_archive_root / "miami_gp" / "draft_evidence.jsonl"
        early_archive_draft_path.parent.mkdir(parents=True, exist_ok=True)
        early_archive_draft_path.write_text(json.dumps(early_archive_claim, ensure_ascii=False) + "\n", encoding="utf-8")
        early_archive_claims = CodexEvidenceProvider().validate_event_file("miami_gp", early_archive_draft_path)
        SourceSnapshotter(
            raw_store=RawSnapshotStore(temp_root / "early_archive_raw"),
            research_root=early_archive_root,
        ).snapshot_url(
            event_id="miami_gp",
            url="test://early-archived-source",
            source="early archived source",
            source_class="media",
            published_at="2026-05-02T08:00:00Z",
            observed_at="2026-05-02T08:30:00Z",
            knowledge_cutoff="2026-05-03T00:00:00+00:00",
            used_in_claim_ids=[early_archive_claim["claim_id"]],
            content_override="<html><title>Early Archived Source</title><body>ok</body></html>",
            historical_archive={
                "archive_url": "https://web.archive.org/web/20260502081500/test://early-archived-source",
                "archived_at": "2026-05-02T08:15:00+00:00",
                "original_url": "test://early-archived-source",
                "verified_at": "2026-06-30T00:00:00+00:00",
                "verification_method": "manual_review",
                "notes": "Smoke fixture for a stale archive proof.",
            },
        )
        early_archive_audit = SourceLogAuditor().audit_claims(
            early_archive_claims,
            early_archive_root / "miami_gp" / "source_log.json",
            knowledge_cutoff="2026-05-03T00:00:00+00:00",
        )
        assert not early_archive_audit.can_archive, "historical archives before claim/source observation should not pass audit"
        assert any(
            finding.code == "claim_observed_after_historical_archive" for finding in early_archive_audit.findings
        ), "source audit should report claim observed_at after the historical archive capture"

        auto_archive_root = temp_root / "auto_archive_research"
        auto_claim = dict(draft_claim)
        auto_claim.update(
            {
                "claim_id": "miami_gp-auto-archive-001",
                "source_url": "https://example.com/miami-preview",
                "published_at": "2026-05-02T08:00:00Z",
                "observed_at": "2026-05-02T08:30:00Z",
            }
        )
        auto_draft_path = auto_archive_root / "miami_gp" / "draft_evidence.jsonl"
        auto_draft_path.parent.mkdir(parents=True, exist_ok=True)
        auto_draft_path.write_text(json.dumps(auto_claim, ensure_ascii=False) + "\n", encoding="utf-8")
        auto_claims = CodexEvidenceProvider().validate_event_file("miami_gp", auto_draft_path)
        SourceSnapshotter(
            raw_store=RawSnapshotStore(temp_root / "auto_archive_raw"),
            research_root=auto_archive_root,
        ).snapshot_url(
            event_id="miami_gp",
            url="https://example.com/miami-preview",
            source="auto archive source",
            source_class="media",
            published_at="2026-05-02T08:00:00Z",
            observed_at="2026-05-02T08:30:00Z",
            knowledge_cutoff="2026-05-03T00:00:00+00:00",
            used_in_claim_ids=[auto_claim["claim_id"]],
            content_override="<html><title>Auto Archive Source</title><body>ok</body></html>",
        )

        class FakeWaybackClient:
            def archive_before(self, url, cutoff):
                assert url == "https://example.com/miami-preview", "archive discovery should query the source URL"
                return {
                    "archive_url": "https://web.archive.org/web/20260502090000/https://example.com/miami-preview",
                    "archived_at": "2026-05-02T09:00:00+00:00",
                    "original_url": url,
                    "verified_at": "2026-06-30T00:00:00+00:00",
                    "verification_method": "wayback_available_api",
                    "notes": "Smoke fixture.",
                }

        class FakeWaybackHttp:
            def get_json(self, url, params=None):
                if "wayback/available" in url:
                    return {"archived_snapshots": {}}
                assert "web.archive.org/cdx" in url, "CDX fallback should run after availability misses"
                assert params["url"] == "https://example.com/miami-preview", "CDX should first try the exact URL"
                return [
                    ["timestamp", "original", "statuscode", "mimetype"],
                    ["20260502090000", "https://example.com/miami-preview", "200", "text/html"],
                ]

        cdx_proof = WaybackAvailabilityClient(http=FakeWaybackHttp()).archive_before(
            "https://example.com/miami-preview",
            parse_dt("2026-05-03T00:00:00+00:00"),
        )
        assert cdx_proof is not None, "Wayback CDX fallback should produce a proof"
        assert cdx_proof["verification_method"] == "wayback_cdx_api", "CDX fallback should disclose proof source"
        assert (
            cdx_proof["original_url"] == "https://example.com/miami-preview"
        ), "CDX proof should preserve the source URL for audit matching"

        dry_archive_report = SourceArchiveBackfiller(
            research_root=auto_archive_root,
            client=FakeWaybackClient(),
        ).discover(event_ids=["miami_gp"], write=False)
        assert dry_archive_report.candidate_count == 1, "archive discovery should find a cutoff-valid candidate"
        assert dry_archive_report.sources_updated == 0, "dry-run archive discovery should not write source logs"
        dry_archive_row = dry_archive_report.rows[0].to_dict()
        assert dry_archive_row["review_summary"], "archive discovery rows should explain review status"
        assert dry_archive_row["next_action"], "archive discovery rows should expose the next action"
        assert dry_archive_row["acceptance_criteria"], "archive discovery rows should expose proof acceptance criteria"

        class MissingWaybackClient:
            def archive_before(self, url, cutoff):
                assert url == "https://example.com/miami-preview", "archive discovery should query the source URL"
                return None

        missing_archive_report = SourceArchiveBackfiller(
            research_root=auto_archive_root,
            client=MissingWaybackClient(),
        ).discover(event_ids=["miami_gp"], write=False)
        missing_archive_row = missing_archive_report.rows[0].to_dict()
        assert (
            missing_archive_row["status"] == "no_archive_before_cutoff"
        ), "missing archive proof should remain a blocker"
        assert (
            "Replace or supplement" in missing_archive_row["next_action"]
        ), "missing archive rows should name the replacement-source action"
        assert (
            missing_archive_row["replacement_query"]
        ), "missing archive rows should provide a replacement-source query"

        replacement_blocker_path = temp_root / "replacement_blockers.json"
        replacement_blocker_path.write_text(
            json.dumps(
                {
                    "rows": [
                        {
                            "event_id": "miami_gp",
                            "event_name": "Miami Grand Prix",
                            "source_index": 0,
                            "url": "https://www.formula1.com/en/latest/article/miami-original",
                            "title": "Miami original blocked source",
                            "published_at": "2026-05-02T08:30:00+00:00",
                            "observed_at": "2026-05-02T08:30:00+00:00",
                            "knowledge_cutoff": "2026-05-03T00:00:00+00:00",
                            "used_in_claim_ids": ["miami_gp-smoke-claim-001"],
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        class FakeReplacementHttp:
            def get_text(self, url):
                assert "miami" in url, "replacement candidates should be filtered to the requested event"
                return (
                    "<html><title>Miami qualifying</title><body>"
                    "Qualifying Classification Andrea Kimi Antonelli 1:27.798 "
                    "Max Verstappen Charles Leclerc Miami Qualifying"
                    "</body></html>"
                )

        class NoReplacementArchive:
            def archive_before(self, url, cutoff):
                return None

            def nearest_capture(self, url, cutoff):
                return None

        replacement_report = SourceReplacementCandidateBuilder(
            http=FakeReplacementHttp(),
            wayback=NoReplacementArchive(),
        ).build(
            input_path=replacement_blocker_path,
            event_ids=["miami_gp"],
        )
        assert replacement_report.candidate_count >= 2, "replacement report should enumerate catalogued candidates"
        assert (
            replacement_report.cutoff_valid_replacement_count == 0
        ), "current content alone must not make a replacement formal-ready"
        assert (
            replacement_report.remaining_candidate_count == replacement_report.candidate_count
        ), "all candidates should remain unresolved when no cutoff-valid replacement exists"
        assert (
            replacement_report.archive_proof_required_count >= 1
        ), "replacement reports should count candidates that still need archive proof"
        assert (
            replacement_report.blocker_code_counts.get("cutoff_archive_missing", 0) >= 1
        ), "replacement reports should aggregate machine-readable archive blocker codes"
        assert (
            replacement_report.next_action_category_counts.get("find_cutoff_archive", 0) >= 1
        ), "replacement reports should aggregate machine-readable next-action categories"
        assert any(
            row.status == "candidate_needs_archive_proof"
            for event in replacement_report.events
            for row in event.candidates
        ), "verified candidates without cutoff archive proof should keep the archive blocker"
        archive_blocked_candidate = next(
            row
            for event in replacement_report.events
            for row in event.candidates
            if row.status == "candidate_needs_archive_proof"
        )
        assert (
            "cutoff_archive_missing" in archive_blocked_candidate.to_dict()["blocker_codes"]
        ), "candidate payloads should expose the exact missing archive proof reason"
        assert (
            archive_blocked_candidate.to_dict()["minimum_missing_requirements"]
        ), "candidate payloads should expose the minimum missing proof requirements"
        assert (
            replacement_report.events[0].status == "replacement_candidates_need_archive_proof"
        ), "event-level status should point to missing archive proof"

        tool_override_url = "https://blocked.example/miami-official-classification"

        class FailingReplacementHttp:
            def get_text(self, url):
                raise RuntimeError(f"blocked: {url}")

        tool_override_report = SourceReplacementCandidateBuilder(
            http=FailingReplacementHttp(),
            wayback=NoReplacementArchive(),
            candidate_catalog=(
                SourceReplacementCandidateDefinition(
                    candidate_id="miami_gp_tool_override_classification",
                    event_id="miami_gp",
                    source="Tool-normalized official classification",
                    source_class="fia",
                    evidence_type="official_classification",
                    url=tool_override_url,
                    expected_terms=(
                        "Qualifying Classification",
                        "Andrea Kimi Antonelli",
                        "1:27.798",
                        "Max Verstappen",
                        "Charles Leclerc",
                    ),
                ),
            ),
            content_overrides={
                tool_override_url: {
                    "url": tool_override_url,
                    "title": "Qualifying Classification",
                    "captured_by": "codex_web_open",
                    "captured_at": "2026-07-01T13:05:00+00:00",
                    "content_text": (
                        "Qualifying Classification GRID OFFICIAL 1 Andrea Kimi Antonelli "
                        "1:27.798 2 Max Verstappen 1:27.964 3 Charles Leclerc 1:28.143"
                    ),
                }
            },
        ).build(
            input_path=replacement_blocker_path,
            event_ids=["miami_gp"],
        )
        tool_candidate = tool_override_report.events[0].candidates[0]
        assert (
            tool_candidate.current_check_status == "verified_tool_content"
        ), "tool-normalized current content should verify candidates when local HTTP is blocked"
        assert (
            tool_candidate.current_content_source == "codex_web_open"
        ), "tool-normalized candidates should disclose the current-content source"
        assert (
            tool_candidate.status == "candidate_needs_archive_proof"
        ), "tool-normalized current content must still require cutoff archive proof"
        assert (
            not tool_candidate.formal_replacement_ready
        ), "tool-normalized current content alone must not make a formal replacement"
        assert (
            tool_candidate.to_dict()["next_action_category"] == "find_cutoff_archive"
        ), "tool-normalized current content should route to archive proof acquisition"

        class ReplacementArchiveProof:
            def archive_before(self, url, cutoff):
                return {
                    "archive_url": f"https://web.archive.org/web/20260502090000/{url}",
                    "archived_at": "2026-05-02T09:00:00+00:00",
                    "original_url": url,
                    "verified_at": "2026-06-30T00:00:00+00:00",
                    "verification_method": "wayback_available_api",
                    "notes": "Smoke replacement proof.",
                }

        manual_review_url = "https://reviewed.example/miami-official-grid"
        manual_review_definition = SourceReplacementCandidateDefinition(
            candidate_id="miami_gp_reviewed_grid",
            event_id="miami_gp",
            source="Reviewed current-content grid",
            source_class="media",
            evidence_type="reviewed_grid",
            url=manual_review_url,
            expected_terms=("Miami", "Andrea Kimi Antonelli", "Max Verstappen"),
            requires_manual_content_review=True,
        )
        manual_unreviewed_report = SourceReplacementCandidateBuilder(
            http=FakeReplacementHttp(),
            wayback=ReplacementArchiveProof(),
            candidate_catalog=(manual_review_definition,),
            content_overrides={
                manual_review_url: {
                    "url": manual_review_url,
                    "title": "Miami official grid",
                    "captured_by": "codex_web_open",
                    "captured_at": "2026-07-01T13:05:00+00:00",
                    "content_text": "Miami Grand Prix grid: Andrea Kimi Antonelli, Max Verstappen.",
                }
            },
        ).build(
            input_path=replacement_blocker_path,
            event_ids=["miami_gp"],
        )
        manual_unreviewed_candidate = manual_unreviewed_report.events[0].candidates[0]
        assert (
            manual_unreviewed_candidate.current_check_status == "current_content_review_required"
        ), "manual-review candidates should remain blocked without an explicit review conclusion"
        assert (
            "manual_current_content_review_required" in manual_unreviewed_candidate.to_dict()["blocker_codes"]
        ), "manual-review candidates should expose the missing review blocker"
        assert (
            not manual_unreviewed_candidate.formal_replacement_ready
        ), "archive proof cannot bypass an outstanding manual content review"

        manual_reviewed_report = SourceReplacementCandidateBuilder(
            http=FakeReplacementHttp(),
            wayback=ReplacementArchiveProof(),
            candidate_catalog=(manual_review_definition,),
            content_overrides={
                manual_review_url: {
                    "url": manual_review_url,
                    "title": "Miami official grid",
                    "captured_by": "codex_web_open",
                    "captured_at": "2026-07-01T13:05:00+00:00",
                    "manual_review_status": "supports_claim",
                    "reviewed_by": "codex_structured_review",
                    "reviewed_at": "2026-07-01T13:10:00+00:00",
                    "manual_review_notes": (
                        "The normalized current-content extract supports the same Miami pole/grid claim "
                        "as miami_gp-smoke-claim-001."
                    ),
                    "content_text": "Miami Grand Prix grid: Andrea Kimi Antonelli, Max Verstappen.",
                }
            },
        ).build(
            input_path=replacement_blocker_path,
            event_ids=["miami_gp"],
        )
        manual_ready_candidate = manual_reviewed_report.events[0].candidates[0]
        assert (
            manual_ready_candidate.current_check_status == "verified_manual_reviewed_content"
        ), "explicit manual-review approval should verify review-required current content"
        assert (
            manual_ready_candidate.manual_content_review
            and manual_ready_candidate.manual_content_review["supports_claim"] is True
        ), "review-required candidates should preserve the structured review conclusion"
        assert (
            manual_ready_candidate.formal_replacement_ready
        ), "reviewed current content plus cutoff archive proof should make a replacement formal-ready"
        assert (
            "manual_current_content_review_required" not in manual_ready_candidate.to_dict()["blocker_codes"]
        ), "accepted manual review should clear only the current-content review blocker"

        ready_replacement_report = SourceReplacementCandidateBuilder(
            http=FakeReplacementHttp(),
            wayback=ReplacementArchiveProof(),
        ).build(
            input_path=replacement_blocker_path,
            event_ids=["miami_gp"],
        )
        assert (
            ready_replacement_report.cutoff_valid_replacement_count >= 1
        ), "a replacement needs both verified content and cutoff archive proof"
        assert (
            ready_replacement_report.remaining_candidate_count
            == ready_replacement_report.candidate_count - ready_replacement_report.cutoff_valid_replacement_count
        ), "remaining replacement count should exclude formal-ready candidates"
        ready_candidate = next(
            row
            for event in ready_replacement_report.events
            for row in event.candidates
            if row.formal_replacement_ready
        )
        assert (
            ready_candidate.status == "cutoff_valid_replacement_candidate"
        ), "ready replacement candidates should use an explicit formal-ready status"
        assert (
            ready_candidate.archive_temporal_check_status == "archive_time_supports_evidence"
        ), "ready replacements need archive captures after the evidence timestamp"
        assert (
            ready_candidate.evidence_available_at == "2026-05-02T08:30:00+00:00"
        ), "replacement reports should expose the evidence timestamp floor"
        assert (
            ready_candidate.to_dict()["blocker_codes"] == []
        ), "formal-ready replacement candidates should have no blocker codes"
        assert (
            ready_candidate.to_dict()["next_action_category"] == "apply_ready_candidate"
        ), "formal-ready replacement candidates should route to the safe apply command"
        assert ready_candidate.to_dict()["command_templates"], "replacement candidates should expose follow-up commands"
        assert (
            "apply-source-replacement" in " ".join(ready_candidate.to_dict()["command_templates"])
        ), "formal-ready replacement candidates should expose the safe apply command"

        apply_root = temp_root / "replacement_apply"
        apply_evidence_dir = apply_root / "seed_evidence"
        apply_packet_root = apply_root / "packets"
        apply_research_root = apply_root / "research"
        apply_raw_root = apply_root / "raw"
        apply_report_path = apply_root / "ready_replacements.json"
        apply_evidence_dir.mkdir(parents=True, exist_ok=True)
        legacy_claim = {
            "claim_id": "miami_gp-smoke-claim-001",
            "event_id": "miami_gp",
            "source": "Blocked original source",
            "source_url": "https://www.formula1.com/en/latest/article/miami-original",
            "published_at": "2026-05-02T08:30:00+00:00",
            "observed_at": "2026-05-02T08:30:00+00:00",
            "target_type": "driver",
            "target_id": "antonelli",
            "claim_type": "qualifying_signal",
            "metric": "grid_position",
            "direction": "positive",
            "magnitude": 0.1,
            "confidence": 0.7,
            "uncertainty": 0.2,
            "evidence_text": "Antonelli starts from pole in the Miami smoke fixture.",
            "reasoning": "A pole position improves expected race outcome.",
            "review_required": True,
        }
        (apply_evidence_dir / "miami_gp.jsonl").write_text(
            json.dumps(legacy_claim, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        apply_report_path.write_text(
            json.dumps(ready_replacement_report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        apply_provider = CodexEvidenceProvider(
            evidence_dir=apply_evidence_dir,
            packet_root=apply_packet_root,
        )
        apply_result = SourceReplacementApplier(
            replacement_report_path=apply_report_path,
            research_root=apply_research_root,
            packet_root=apply_packet_root,
            evidence_provider=apply_provider,
            raw_store=RawSnapshotStore(apply_raw_root),
        ).apply_candidate(
            ready_candidate.candidate_id,
            content_override=(
                "<html><title>Miami qualifying</title><body>"
                "Qualifying Classification Andrea Kimi Antonelli 1:27.798 "
                "Max Verstappen Charles Leclerc Miami Qualifying"
                "</body></html>"
            ),
        )
        assert apply_result.can_archive, "formal-ready replacement apply should pass source audit"
        assert Path(apply_result.packet_path).exists(), "replacement apply should archive updated evidence claims"
        updated_claim = next(
            claim
            for claim in apply_provider.load_event_evidence(
                "miami_gp",
                parse_dt("2026-05-03T00:00:00+00:00"),
            )
            if claim.claim_id == "miami_gp-smoke-claim-001"
        )
        assert (
            updated_claim.source_url == ready_candidate.url
        ), "replacement apply should update the evidence claim source_url to the replacement source"
        applied_audit = SourceLogAuditor().audit_claims(
            [updated_claim],
            apply_research_root / "miami_gp" / "source_log.json",
            knowledge_cutoff="2026-05-03T00:00:00+00:00",
        )
        assert applied_audit.can_archive, "applied replacement source log should pass source audit"

        not_ready_report_path = apply_root / "not_ready_replacements.json"
        not_ready_report_path.write_text(
            json.dumps(replacement_report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        not_ready_candidate = next(
            row
            for event in replacement_report.events
            for row in event.candidates
            if not row.formal_replacement_ready
        )
        try:
            SourceReplacementApplier(
                replacement_report_path=not_ready_report_path,
                research_root=apply_research_root,
                packet_root=apply_packet_root,
                evidence_provider=apply_provider,
                raw_store=RawSnapshotStore(apply_raw_root),
            ).apply_candidate(not_ready_candidate.candidate_id, content_override="<html></html>")
            raise AssertionError("not-ready replacement candidates must be rejected by apply")
        except SourceReplacementApplyError:
            pass

        class TooEarlyReplacementArchiveProof:
            def archive_before(self, url, cutoff):
                return {
                    "archive_url": f"https://web.archive.org/web/20260502070000/{url}",
                    "archived_at": "2026-05-02T07:00:00+00:00",
                    "original_url": url,
                    "verified_at": "2026-06-30T00:00:00+00:00",
                    "verification_method": "wayback_available_api",
                    "notes": "Smoke replacement proof captured before evidence was available.",
                }

        stale_replacement_report = SourceReplacementCandidateBuilder(
            http=FakeReplacementHttp(),
            wayback=TooEarlyReplacementArchiveProof(),
        ).build(
            input_path=replacement_blocker_path,
            event_ids=["miami_gp"],
        )
        assert (
            stale_replacement_report.cutoff_valid_replacement_count == 0
        ), "archive captures before the evidence timestamp must not make a replacement formal-ready"
        assert (
            stale_replacement_report.archive_proof_required_count >= 1
        ), "temporal-review archive candidates should remain counted as needing stronger proof"
        assert any(
            row.status == "candidate_needs_archive_temporal_review"
            for event in stale_replacement_report.events
            for row in event.candidates
        ), "stale archive captures should surface an explicit temporal-review status"
        stale_candidate = next(
            row
            for event in stale_replacement_report.events
            for row in event.candidates
            if row.status == "candidate_needs_archive_temporal_review"
        )
        assert (
            "archive_before_evidence_time" in stale_candidate.to_dict()["blocker_codes"]
        ), "stale archive captures should expose a temporal blocker code"
        assert (
            stale_candidate.to_dict()["next_action_category"] == "find_archive_after_evidence_time"
        ), "stale archive captures should route to stronger temporal archive proof"
        with tempfile.TemporaryDirectory() as replacement_output_dir:
            replacement_paths = SourceReplacementCandidateBuilder(
                http=FakeReplacementHttp(),
                wayback=NoReplacementArchive(),
            ).write(
                input_path=replacement_blocker_path,
                event_ids=["miami_gp"],
                output_dir=Path(replacement_output_dir),
            )
            assert replacement_paths["json"].exists(), "replacement report JSON should be written"
            assert replacement_paths["markdown"].exists(), "replacement report Markdown should be written"
        write_archive_report = SourceArchiveBackfiller(
            research_root=auto_archive_root,
            client=FakeWaybackClient(),
        ).discover(event_ids=["miami_gp"], write=True)
        assert write_archive_report.sources_updated == 1, "write mode should attach discovered archive proof"
        auto_audit = SourceLogAuditor().audit_claims(
            auto_claims,
            auto_archive_root / "miami_gp" / "source_log.json",
            knowledge_cutoff="2026-05-03T00:00:00+00:00",
        )
        assert auto_audit.can_archive, "auto-discovered archive proof should pass source audit"
        assert not any(
            finding.code == "snapshot_captured_after_cutoff" for finding in auto_audit.findings
        ), "auto archive proof should remove retrospective source warning"
        packet_research_root = temp_root / "packet_research"
        packet_store_root = temp_root / "packet_evidence"
        packet_manifest = {
            "packet_id": "miami_gp-smoke-packet",
            "event_id": "miami_gp",
            "knowledge_cutoff": "2026-05-03T00:00:00+00:00",
            "sources": [
                {
                    "source": "smoke packet source",
                    "url": "test://packet-source",
                    "source_class": "media",
                    "published_at": "2026-05-02T09:00:00Z",
                    "observed_at": "2026-05-02T09:30:00Z",
                    "used_in_claim_ids": ["miami_gp-smoke-packet-001"],
                    "notes": "Offline source fixture for batch research packet archiving.",
                    "content": "<html><title>Packet Source</title><body>ok</body></html>",
                }
            ],
            "claims": [
                {
                    "claim_id": "miami_gp-smoke-packet-001",
                    "event_id": "miami_gp",
                    "source": "smoke packet source",
                    "source_url": "test://packet-source",
                    "published_at": "2026-05-02T09:00:00Z",
                    "observed_at": "2026-05-02T09:30:00Z",
                    "target_type": "driver",
                    "target_id": "antonelli",
                    "claim_type": "smoke_packet",
                    "metric": "race_pace",
                    "direction": "neutral",
                    "magnitude": 0.0,
                    "confidence": 0.1,
                    "uncertainty": 0.9,
                    "evidence_text": "Smoke packet source is linked to this claim.",
                    "reasoning": "Used only to verify batch archive plumbing.",
                    "review_required": True,
                }
            ],
        }
        packet_result = CodexResearchPacketArchiver(
            research_root=packet_research_root,
            raw_store=RawSnapshotStore(temp_root / "packet_raw"),
            packet_root=packet_store_root,
        ).archive_packet(packet_manifest)
        assert packet_result.claim_count == 1, "batch archiver should archive one claim"
        assert packet_result.source_count == 1, "batch archiver should snapshot one source"
        assert any(
            finding["code"] == "snapshot_captured_after_cutoff" for finding in packet_result.findings
        ), "batch archiver should surface retrospective source snapshot warnings"
        loaded_packet = CodexEvidenceProvider(
            evidence_dir=temp_root / "empty_seed",
            packet_root=packet_store_root,
        ).load_event_evidence("miami_gp")
        assert len(loaded_packet) == 1, "batch-archived evidence should be loadable"

        preflight_manifest = {
            "packet_id": "british_gp-preflight-smoke",
            "event_id": "british_gp",
            "knowledge_cutoff": "2026-06-30T12:00:00+00:00",
            "sources": [
                {
                    "source": "independent media smoke source",
                    "url": "https://example.com/british-ers-positive",
                    "source_class": "media",
                    "published_at": "2026-06-29T10:00:00+00:00",
                    "observed_at": "2026-06-29T10:15:00+00:00",
                    "used_in_claim_ids": ["british_gp-preflight-001"],
                    "notes": "Offline preflight source fixture.",
                },
                {
                    "source": "team smoke source",
                    "url": "https://team.example/british-ers-negative",
                    "source_class": "team_or_driver",
                    "published_at": "2026-06-29T11:00:00+00:00",
                    "observed_at": "2026-06-29T11:15:00+00:00",
                    "used_in_claim_ids": ["british_gp-preflight-002"],
                    "notes": "Offline preflight source fixture.",
                },
            ],
            "claims": [
                {
                    "claim_id": "british_gp-preflight-001",
                    "event_id": "british_gp",
                    "source": "independent media smoke source",
                    "source_url": "https://example.com/british-ers-positive",
                    "published_at": "2026-06-29T10:00:00+00:00",
                    "observed_at": "2026-06-29T10:15:00+00:00",
                    "target_type": "team",
                    "target_id": "mercedes",
                    "claim_type": "ers",
                    "metric": "energy_recovery",
                    "direction": "positive",
                    "magnitude": 0.05,
                    "confidence": 0.7,
                    "uncertainty": 0.25,
                    "evidence_text": "Smoke source says Mercedes has a Silverstone ERS deployment advantage.",
                    "reasoning": "Silverstone is high-speed and energy deployment should route into track-contextual pace.",
                    "review_required": False,
                },
                {
                    "claim_id": "british_gp-preflight-002",
                    "event_id": "british_gp",
                    "source": "team smoke source",
                    "source_url": "https://team.example/british-ers-negative",
                    "published_at": "2026-06-29T11:00:00+00:00",
                    "observed_at": "2026-06-29T11:15:00+00:00",
                    "target_type": "team",
                    "target_id": "mercedes",
                    "claim_type": "ers",
                    "metric": "energy_recovery",
                    "direction": "negative",
                    "magnitude": 0.04,
                    "confidence": 0.65,
                    "uncertainty": 0.30,
                    "evidence_text": "Smoke source says Mercedes expects ERS clipping risk late in long Silverstone laps.",
                    "reasoning": "The opposite direction should be surfaced as an independent-source conflict before archive.",
                    "review_required": False,
                },
            ],
        }
        candidate_gate_report = {
            "event_id": "british_gp",
            "status": "source_candidates_ready_for_claim_review",
            "candidate_count": 2,
            "review_ready_count": 2,
            "blocked_count": 0,
            "warning_count": 0,
            "rows": [
                {
                    "candidate_id": "british-candidate-ready-001",
                    "event_id": "british_gp",
                    "url": "https://example.com/british-ers-positive",
                    "status": "candidate_ready_for_claim_review",
                    "source_class": "media",
                },
                {
                    "candidate_id": "british-candidate-ready-002",
                    "event_id": "british_gp",
                    "url": "https://team.example/british-ers-negative",
                    "status": "candidate_ready_for_claim_review",
                    "source_class": "team_or_driver",
                },
            ],
        }
        candidate_gate_path = temp_root / "british_candidate_gate.json"
        candidate_gate_path.write_text(json.dumps(candidate_gate_report, ensure_ascii=False, indent=2), encoding="utf-8")
        preflight = CodexResearchPacketPreflight(data_source=SeedDataSource()).preflight_packet(
            preflight_manifest,
            source_candidate_report_path=candidate_gate_path,
        )
        assert preflight.valid_claim_count == 2, "preflight should parse both smoke claims"
        assert preflight.archive_precheck_can_archive, "warnings should not block archive precheck"
        assert (
            preflight.factor_route_counts.get("track_contextual_pace") == 2
        ), "ERS claims should route into track-contextual pace"
        assert all(
            not row.factor_contract_codes for row in preflight.claims
        ), "valid ERS preflight claims should satisfy the normalized factor contract"
        assert all(
            row.context_multiplier is not None for row in preflight.claims
        ), "preflight should expose technical context multipliers before archive"
        assert all(
            row.effective_race_input == round(row.weighted_input_impact * row.context_multiplier, 4)
            for row in preflight.claims
        ), "preflight should preview quality-weighted, track-context effective simulator inputs"
        assert all(
            row.track_demand_component == "ers_demand" for row in preflight.claims
        ), "preflight should preview the technical track-demand component before archive"
        assert (
            preflight.route_status_counts.get("routed_impact_not_measured") == 2
        ), "preflight should identify routed claims without claiming impact measurement"
        assert (
            preflight.conflict_status_counts.get("independent_source_conflict") == 2
        ), "preflight should surface independent opposing claim directions"
        assert (
            preflight.max_model_input_weight is not None and preflight.max_model_input_weight <= 0.58
        ), "conflicting preflight claims should be capped by conflict-aware input weights"
        assert any(
            finding.code == "source_audit_snapshot_captured_after_cutoff" for finding in preflight.findings
        ), "preflight should expose late synthetic snapshot warnings"
        unfilled_preflight = CodexResearchPacketPreflight(data_source=SeedDataSource()).preflight_packet(
            {
                "packet_id": "british_gp-template-placeholder-smoke",
                "event_id": "british_gp",
                "knowledge_cutoff": "2026-06-30T12:00:00+00:00",
                "sources": [
                    {
                        "source": "REPLACE_WITH_SOURCE_NAME",
                        "url": "REPLACE_WITH_SOURCE_URL",
                        "source_class": "media",
                        "published_at": "REPLACE_WITH_ISO_TIMESTAMP",
                        "observed_at": "REPLACE_WITH_ISO_TIMESTAMP",
                        "used_in_claim_ids": ["british_gp-template-placeholder-001"],
                    }
                ],
                "claims": [
                    {
                        "claim_id": "british_gp-template-placeholder-001",
                        "event_id": "british_gp",
                        "source": "REPLACE_WITH_SOURCE_NAME",
                        "source_url": "REPLACE_WITH_SOURCE_URL",
                        "published_at": "REPLACE_WITH_ISO_TIMESTAMP",
                        "observed_at": "REPLACE_WITH_ISO_TIMESTAMP",
                        "target_type": "team",
                        "target_id": "REPLACE_WITH_TEAM_OR_DRIVER_ID",
                        "claim_type": "ers",
                        "metric": "energy_recovery",
                        "direction": "positive",
                        "magnitude": 0.03,
                        "confidence": 0.5,
                        "uncertainty": 0.35,
                        "evidence_text": "Placeholder should not be treated as a real claim.",
                        "reasoning": "Placeholder should not enter factor routing.",
                        "review_required": True,
                    }
                ],
            }
        )
        assert (
            unfilled_preflight.status == "research_packet_template_unfilled"
        ), "unfilled research packet templates should return an explicit waiting state"
        assert (
            unfilled_preflight.valid_claim_count == 0 and not unfilled_preflight.claims
        ), "placeholder packet rows should not be routed as real claims"
        file_preflight_dir = temp_root / "file_preflight_research" / "british_gp"
        file_preflight_dir.mkdir(parents=True)
        file_packet_path = file_preflight_dir / "research_packet_template.json"
        file_packet_path.write_text(json.dumps(preflight_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        file_source_log = {
            "event_id": "british_gp",
            "event_name": "British Grand Prix",
            "knowledge_cutoff": "2026-06-30T12:00:00+00:00",
            "sources": [
                {
                    **source,
                    "title": source["source"],
                    "knowledge_cutoff": "2026-06-30T12:00:00+00:00",
                    "cutoff_status": "within_cutoff",
                    "reliability": 0.75 if source["source_class"] == "media" else 0.85,
                    "captured_at": source["observed_at"],
                    "snapshot_path": f"fixture://{source['url']}",
                    "content_length": 100,
                }
                for source in preflight_manifest["sources"]
            ],
        }
        (file_preflight_dir / "source_log.json").write_text(
            json.dumps(file_source_log, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        file_preflight = CodexResearchPacketPreflight(data_source=SeedDataSource()).preflight_file(
            file_packet_path,
            source_candidate_report_path=candidate_gate_path,
        )
        assert file_preflight.source_audit and file_preflight.source_audit[
            "source_log_path"
        ].endswith("source_log.json"), "file preflight should use an adjacent source_log.json when available"
        assert not any(
            finding.code == "source_audit_snapshot_captured_after_cutoff"
            for finding in file_preflight.findings
        ), "file preflight should not emit synthetic snapshot warnings when a real source_log is available"
        gated_preflight = CodexResearchPacketPreflight(data_source=SeedDataSource()).preflight_packet(
            preflight_manifest,
            source_candidate_report_path=candidate_gate_path,
        )
        assert (
            gated_preflight.source_candidate_audit
            and gated_preflight.source_candidate_audit["matched_source_count"] == 2
        ), "preflight should prove packet sources were present in the source-candidate audit"
        assert not any(
            finding.code.startswith("source_candidate_") for finding in gated_preflight.findings
        ), "ready source candidates should not add candidate-gate errors"
        blocked_candidate_gate_report = {
            **candidate_gate_report,
            "status": "source_candidates_blocked",
            "blocked_count": 1,
            "rows": [
                candidate_gate_report["rows"][0],
                {
                    **candidate_gate_report["rows"][1],
                    "status": "candidate_blocked",
                },
            ],
        }
        blocked_candidate_gate_path = temp_root / "british_candidate_gate_blocked.json"
        blocked_candidate_gate_path.write_text(json.dumps(blocked_candidate_gate_report, ensure_ascii=False, indent=2), encoding="utf-8")
        blocked_preflight = CodexResearchPacketPreflight(data_source=SeedDataSource()).preflight_packet(
            preflight_manifest,
            source_candidate_report_path=blocked_candidate_gate_path,
        )
        assert not blocked_preflight.archive_precheck_can_archive, "blocked source candidates should block packet archive preflight"
        assert any(
            finding.code == "source_candidate_not_ready" for finding in blocked_preflight.findings
        ), "preflight should report packet sources whose audited candidate is not ready"
        missing_candidate_gate_report = {
            **candidate_gate_report,
            "candidate_count": 1,
            "review_ready_count": 1,
            "rows": [candidate_gate_report["rows"][0]],
        }
        missing_candidate_gate_path = temp_root / "british_candidate_gate_missing.json"
        missing_candidate_gate_path.write_text(json.dumps(missing_candidate_gate_report, ensure_ascii=False, indent=2), encoding="utf-8")
        missing_candidate_preflight = CodexResearchPacketPreflight(data_source=SeedDataSource()).preflight_packet(
            preflight_manifest,
            source_candidate_report_path=missing_candidate_gate_path,
        )
        assert not missing_candidate_preflight.archive_precheck_can_archive, "packet sources missing from candidate audit should block preflight"
        assert any(
            finding.code == "source_candidate_missing" for finding in missing_candidate_preflight.findings
        ), "preflight should report source URLs that bypassed candidate auditing"
        invalid_contract_manifest = {
            **preflight_manifest,
            "packet_id": "british_gp-preflight-invalid-contract",
            "sources": [
                {
                    **preflight_manifest["sources"][0],
                    "used_in_claim_ids": ["british_gp-preflight-invalid-contract-001"],
                }
            ],
            "claims": [
                {
                    **preflight_manifest["claims"][0],
                    "claim_id": "british_gp-preflight-invalid-contract-001",
                    "target_type": "event",
                    "target_id": "british_gp",
                    "claim_type": "weather",
                    "metric": "energy_recovery",
                }
            ],
        }
        invalid_contract_preflight = CodexResearchPacketPreflight(data_source=SeedDataSource()).preflight_packet(
            invalid_contract_manifest,
        )
        assert not invalid_contract_preflight.archive_precheck_can_archive, "factor contract mismatches should block archive preflight"
        invalid_contract_codes = {
            finding.code for finding in invalid_contract_preflight.findings
            if finding.claim_id == "british_gp-preflight-invalid-contract-001"
        }
        assert {
            "factor_contract_target_mismatch",
            "factor_contract_claim_type_mismatch",
        }.issubset(invalid_contract_codes), "preflight should name target and claim_type factor-contract failures"
        assert (
            invalid_contract_preflight.claims[0].factor_contract_codes
        ), "claim rows should carry factor-contract codes for frontend audit"
        missing_mechanism_manifest = {
            **preflight_manifest,
            "packet_id": "british_gp-preflight-missing-mechanism",
            "sources": [
                {
                    **preflight_manifest["sources"][0],
                    "used_in_claim_ids": ["british_gp-preflight-missing-mechanism-001"],
                }
            ],
            "claims": [
                {
                    **preflight_manifest["claims"][0],
                    "claim_id": "british_gp-preflight-missing-mechanism-001",
                    "target_type": "team",
                    "target_id": "mercedes",
                    "claim_type": "ers",
                    "metric": "energy_recovery",
                    "evidence_text": "Smoke source says Mercedes should be stronger this weekend.",
                    "reasoning": "General optimism is not enough to justify a technical simulator input.",
                }
            ],
        }
        missing_mechanism_preflight = CodexResearchPacketPreflight(data_source=SeedDataSource()).preflight_packet(
            missing_mechanism_manifest,
        )
        assert not missing_mechanism_preflight.archive_precheck_can_archive, "technical claims without mechanism/context should block archive preflight"
        missing_mechanism_codes = {
            finding.code for finding in missing_mechanism_preflight.findings
            if finding.claim_id == "british_gp-preflight-missing-mechanism-001"
        }
        assert {
            "factor_contract_missing_technical_mechanism",
            "factor_contract_missing_track_context",
        }.issubset(missing_mechanism_codes), "preflight should require both mechanism and track-context text for technical metrics"
        preflight_json = temp_root / "packet_preflight.json"
        preflight_md = temp_root / "packet_preflight.md"
        written_preflight = CodexResearchPacketPreflight.write_outputs(
            preflight,
            json_output=preflight_json,
            markdown_output=preflight_md,
        )
        assert preflight_json.exists(), "preflight JSON report should be writable"
        assert preflight_md.exists(), "preflight Markdown report should be writable"
        assert "json_output" in written_preflight and "markdown_output" in written_preflight
        assert "Research Packet Preflight" in preflight_md.read_text(encoding="utf-8")
    print("smoke_test: ok")


if __name__ == "__main__":
    main()
